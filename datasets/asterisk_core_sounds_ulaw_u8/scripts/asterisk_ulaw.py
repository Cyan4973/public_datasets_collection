#!/usr/bin/env python3
"""Preflight, build, and verify raw Asterisk G.711 mu-law prompt streams."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import statistics
import tarfile


DATASET_ID = "asterisk_core_sounds_ulaw_u8"
SERIES_ID = "asterisk_prompt_mulaw_u8"
EXPECTED_ARCHIVE_SIZE = 10_241_447
EXPECTED_ARCHIVE_SHA256 = "83ec602fb1f2cb06a5194a95f855b84bae35d49d5bdb6fbd9274d5d1a5d16b0e"
EXPECTED_LICENSE_MEMBER = "LICENSE-asterisk-core-en-1.6.1"
EXPECTED_LICENSE_SIZE = 16_118
EXPECTED_LICENSE_SHA256 = "d8c004dc5a97414413a1e7ee1fa5832519d020b1bd0b925d31af3ee325fe9dea"
MIN_MEMBERS = 100
MAX_MEMBERS = 5_000
MIN_TOTAL_VALUES = 100_000
MIN_MEDIAN_VALUES = 1_000
MAX_TOTAL_BYTES = 500_000_000
MAX_LICENSE_BYTES = 1_000_000
LICENSE_NAMES = re.compile(r"(^|/)(license|copying|copyright|readme|credits)([^/]*)$", re.I)


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_archive_identity(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"missing source archive: {path}")
    actual_size = path.stat().st_size
    actual_hash = file_hash(path)
    if actual_size != EXPECTED_ARCHIVE_SIZE or actual_hash != EXPECTED_ARCHIVE_SHA256:
        raise SystemExit(f"archive identity mismatch: size={actual_size} sha256={actual_hash}")


def safe_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    total = 0
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise SystemExit(f"unsafe TAR member path: {member.name}")
        if not (member.isfile() or member.isdir()):
            raise SystemExit(f"unsupported TAR member type: {member.name}")
        if member.size < 0:
            raise SystemExit(f"negative TAR member size: {member.name}")
        total += member.size
        if total > MAX_TOTAL_BYTES:
            raise SystemExit("expanded archive exceeds 500 MB")
    return members


def read_member(archive: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    handle = archive.extractfile(member)
    if handle is None:
        raise SystemExit(f"cannot read regular TAR member: {member.name}")
    payload = handle.read(member.size + 1)
    if len(payload) != member.size:
        raise SystemExit(f"short TAR member read: {member.name}")
    return payload


def license_evidence(archive: tarfile.TarFile, members: list[tarfile.TarInfo]) -> dict[str, object]:
    evidence = []
    combined = []
    for member in members:
        if not member.isfile() or member.size > MAX_LICENSE_BYTES or not LICENSE_NAMES.search(member.name):
            continue
        raw = read_member(archive, member)
        text = raw.decode("utf-8", errors="replace")
        lower = re.sub(r"\s+", " ", text.lower())
        if "creative commons" in lower or "creativecommons.org" in lower or "license" in lower:
            evidence.append({
                "source_member": member.name,
                "size_bytes": member.size,
                "sha256": hashlib.sha256(raw).hexdigest(),
            })
            combined.append(lower)
    expected = next((item for item in evidence if item["source_member"] == EXPECTED_LICENSE_MEMBER), None)
    if expected is None or expected["size_bytes"] != EXPECTED_LICENSE_SIZE or expected["sha256"] != EXPECTED_LICENSE_SHA256:
        raise SystemExit("embedded Asterisk voice-prompt license identity mismatch")
    text = " ".join(combined)
    required_terms = (
        "license for voice prompt files",
        "copyright (c) 2003-2008 allison smith",
        '"license elements" means the following high-level license attributes',
        "attribution, sharealike",
        "attribution-sharealike 3.0 (unported)",
    )
    if not all(term in text for term in required_terms):
        raise SystemExit("archive lacks explicit Creative Commons BY-SA 3.0 evidence")
    return {"license": "CC BY-SA 3.0 Unported", "evidence_members": evidence}


def is_silence_member(name: str) -> bool:
    parts = [part.lower() for part in PurePosixPath(name).parts]
    return "silence" in parts


def sample_slug(index: int, member: str) -> str:
    stem = re.sub(r"[^a-z0-9]+", "_", str(PurePosixPath(member).with_suffix("")).lower()).strip("_")[-90:]
    suffix = hashlib.sha256(member.encode("utf-8")).hexdigest()[:8]
    return f"prompt_{index:04d}_{stem}_{suffix}"


def scan_archive(path: Path) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    validate_archive_identity(path)
    if not tarfile.is_tarfile(path):
        raise SystemExit(f"missing or invalid source archive: {path}")
    samples: list[dict[str, object]] = []
    duplicates: list[dict[str, object]] = []
    excluded_silence: list[dict[str, object]] = []
    seen: dict[str, str] = {}
    with tarfile.open(path, "r:gz") as archive:
        members = safe_members(archive)
        rights = license_evidence(archive, members)
        audio = sorted(
            (member for member in members if member.isfile() and PurePosixPath(member.name).suffix.lower() == ".ulaw"),
            key=lambda member: member.name,
        )
        if not MIN_MEMBERS <= len(audio) <= MAX_MEMBERS:
            raise SystemExit(f"raw mu-law member count outside bounds: {len(audio)}")
        for member in audio:
            if is_silence_member(member.name):
                excluded_silence.append({"source_member": member.name, "size_bytes": member.size})
                continue
            payload = read_member(archive, member)
            if not payload:
                raise SystemExit(f"empty nonsilence mu-law member: {member.name}")
            if len(set(payload)) < 2:
                raise SystemExit(f"constant nonsilence mu-law member: {member.name}")
            digest = hashlib.sha256(payload).hexdigest()
            if digest in seen:
                duplicates.append({
                    "source_member": member.name,
                    "size_bytes": member.size,
                    "sha256": digest,
                    "kept_source_member": seen[digest],
                })
                continue
            seen[digest] = member.name
            samples.append({
                "source_member": member.name,
                "source_size_bytes": member.size,
                "sha256": digest,
                "payload": payload,
            })
    lengths = [len(sample["payload"]) for sample in samples]
    if not lengths or sum(lengths) < MIN_TOTAL_VALUES:
        raise SystemExit("mu-law primary payload does not meet aggregate floor")
    if statistics.median(lengths) < MIN_MEDIAN_VALUES:
        raise SystemExit(f"median natural prompt is below {MIN_MEDIAN_VALUES} codes")
    return samples, duplicates, excluded_silence, rights


def make_summary(
    samples: list[dict[str, object]],
    duplicates: list[dict[str, object]],
    excluded_silence: list[dict[str, object]],
    rights: dict[str, object],
) -> dict[str, object]:
    lengths = [len(sample["payload"]) for sample in samples]
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(samples),
        "value_count": sum(lengths),
        "total_size_bytes": sum(lengths),
        "minimum_sample_value_count": min(lengths),
        "median_sample_value_count": statistics.median(lengths),
        "maximum_sample_value_count": max(lengths),
        "duplicate_count": len(duplicates),
        "duplicates": duplicates,
        "excluded_silence_count": len(excluded_silence),
        "excluded_silence_members": excluded_silence,
        **rights,
    }


def preflight(args: argparse.Namespace) -> None:
    samples, duplicates, excluded_silence, rights = scan_archive(args.archive)
    result = {
        **make_summary(samples, duplicates, excluded_silence, rights),
        "archive_size_bytes": args.archive.stat().st_size,
        "archive_sha256": file_hash(args.archive),
    }
    args.profile.parent.mkdir(parents=True, exist_ok=True)
    args.profile.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    samples, duplicates, excluded_silence, rights = scan_archive(args.archive)
    series_dir = args.samples_dir / SERIES_ID
    if args.samples_dir.exists():
        shutil.rmtree(args.samples_dir)
    series_dir.mkdir(parents=True)
    rows = []
    for sample_index, sample in enumerate(samples):
        payload = sample["payload"]
        output = series_dir / f"{sample_slug(sample_index, str(sample['source_member']))}_u8_n{len(payload)}.bin"
        output.write_bytes(payload)
        rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "source_sample": args.archive.relative_to(args.data_root).as_posix(),
            "source_member": sample["source_member"],
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "value_count": len(payload),
            "sample_size_bytes": len(payload),
            "sample_format": "raw homogeneous uint8 G.711 mu-law code timeline",
            "sample_geometry": "g711_mulaw_prompt_time_series_1d",
            "sample_rank": 1,
            "sample_shape": [len(payload)],
            "sample_axes": ["audio_sample_time"],
            "natural_record_kind": "individual_telephony_prompt_recording",
            "sample_rate_hz": 8000,
            "minimum": min(payload),
            "maximum": max(payload),
            "distinct_values": len(set(payload)),
            "sha256": sample["sha256"],
        })
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    result = make_summary(samples, duplicates, excluded_silence, rights)
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    samples, duplicates, excluded_silence, rights = scan_archive(args.archive)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or ingest stats; run build first")
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != len(samples):
        raise SystemExit("index row count differs from fresh archive parse")
    expected_outputs: set[Path] = set()
    for sample, row in zip(samples, rows, strict=True):
        payload = sample["payload"]
        if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID or row.get("role") != "primary":
            raise SystemExit("dataset/series/role mismatch")
        if row.get("source_member") != sample["source_member"]:
            raise SystemExit("source member ordering mismatch")
        if row.get("numeric_kind") != "uint" or row.get("bit_width") != 8 or row.get("endianness") != "little" or row.get("element_size_bytes") != 1:
            raise SystemExit("numeric schema mismatch")
        if row.get("value_count") != len(payload) or row.get("sample_shape") != [len(payload)]:
            raise SystemExit("sample length mismatch")
        output = args.data_root / str(row["sample_path"])
        if not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"output differs from fresh archive parse: {output}")
        if row.get("sha256") != hashlib.sha256(payload).hexdigest():
            raise SystemExit(f"indexed hash mismatch: {output}")
        expected_outputs.add(output.resolve())
    actual_outputs = {path.resolve() for path in (args.data_root / "samples" / DATASET_ID).glob("*/*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contains missing, stale, or extra outputs")
    expected_summary = make_summary(samples, duplicates, excluded_silence, rights)
    if json.loads(args.stats.read_text(encoding="utf-8")) != expected_summary:
        raise SystemExit("ingest stats differ from fresh archive parse")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_samples": len(samples),
        "verified_values": expected_summary["value_count"],
        "verified_bytes": expected_summary["total_size_bytes"],
        "median_sample_value_count": expected_summary["median_sample_value_count"],
        "duplicate_streams_excluded": len(duplicates),
        "silence_utilities_excluded": len(excluded_silence),
    }, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    pre = commands.add_parser("preflight")
    pre.add_argument("--archive", type=Path, required=True)
    pre.add_argument("--profile", type=Path, required=True)
    for command in ("build", "verify"):
        sub = commands.add_parser(command)
        sub.add_argument("--archive", type=Path, required=True)
        sub.add_argument("--index", type=Path, required=True)
        sub.add_argument("--stats", type=Path, required=True)
        sub.add_argument("--data-root", type=Path, required=True)
        if command == "build":
            sub.add_argument("--samples-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "preflight":
        preflight(args)
    elif args.command == "build":
        build(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
