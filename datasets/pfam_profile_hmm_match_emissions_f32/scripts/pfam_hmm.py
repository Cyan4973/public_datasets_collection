#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import statistics
import struct
import sys
from typing import Iterator, TextIO


DATASET_ID = "pfam_profile_hmm_match_emissions_f32"
SERIES_ID = "pfam_profile_hmm_match_emissions_f32"
SOURCE_BYTES = 418160514
SOURCE_MD5 = "7ab3c4e215d0daaea3004e37c4e24f8a"
SOURCE_SHA256 = "2d82087b6c5c60d762cc767f98e8260b273134c215ab7efccf7440614a4e5dab"
EXPECTED_PROFILES = 30134
EXPECTED_SAMPLES = 27496
EXPECTED_VALUES = 93130540
EXPECTED_SAMPLE_BYTES = 372522160
EXPECTED_TRANSITION_STARS = 90402
MIN_PROFILE_LENGTH = 50
AMINO_ACIDS = ("A", "C", "D", "E", "F", "G", "H", "I", "K", "L", "M", "N", "P", "Q", "R", "S", "T", "V", "W", "Y")
TRANSITIONS = ("m->m", "m->i", "m->d", "i->m", "i->i", "d->m", "d->d")
ACCESSION_RE = re.compile(r"PF\d{5}\.\d+")


@dataclass(frozen=True)
class Profile:
    name: str
    accession: str
    length: int
    match_values: tuple[float, ...]
    transition_stars: int


class HMMReader:
    def __init__(self, handle: TextIO) -> None:
        self.handle = handle
        self.line_number = 0

    def read(self, context: str) -> str:
        line = self.handle.readline()
        if not line:
            raise ValueError(f"unexpected EOF while reading {context}")
        self.line_number += 1
        return line.rstrip("\r\n")

    def optional(self) -> str | None:
        line = self.handle.readline()
        if not line:
            return None
        self.line_number += 1
        return line.rstrip("\r\n")


def parse_scores(tokens: list[str], count: int, context: str, allow_stars: bool) -> tuple[list[float], int]:
    if len(tokens) < count:
        raise ValueError(f"{context}: expected {count} score tokens, found {len(tokens)}")
    values: list[float] = []
    stars = 0
    for token in tokens[:count]:
        if token == "*":
            stars += 1
            if not allow_stars:
                raise ValueError(f"{context}: unsupported `*` match-emission sentinel")
            continue
        try:
            value = float(token)
        except ValueError as exc:
            raise ValueError(f"{context}: invalid score token {token!r}") from exc
        if not math.isfinite(value):
            raise ValueError(f"{context}: non-finite score token {token!r}")
        values.append(value)
    return values, stars


def iter_profiles(archive: Path) -> Iterator[Profile]:
    with gzip.open(archive, "rt", encoding="ascii", errors="strict", newline="") as handle:
        reader = HMMReader(handle)
        while True:
            first = reader.optional()
            if first is None:
                return
            if not first:
                continue
            if not first.startswith("HMMER3/"):
                raise ValueError(
                    f"line {reader.line_number}: expected HMMER3 record header, got {first!r}"
                )

            name = ""
            accession = ""
            length = 0
            alphabet: tuple[str, ...] | None = None
            while True:
                line = reader.read("profile header")
                parts = line.split()
                if not parts:
                    continue
                key = parts[0]
                if key == "NAME" and len(parts) >= 2:
                    name = parts[1]
                elif key == "ACC" and len(parts) >= 2:
                    accession = parts[1]
                elif key == "LENG" and len(parts) == 2:
                    length = int(parts[1])
                elif key == "HMM":
                    alphabet = tuple(parts[1:])
                    break
                elif key == "//":
                    raise ValueError(f"line {reader.line_number}: profile ended before HMM matrix")

            if not name or not ACCESSION_RE.fullmatch(accession) or length <= 0:
                raise ValueError(
                    f"line {reader.line_number}: incomplete profile header "
                    f"name={name!r} accession={accession!r} length={length}"
                )
            if alphabet != AMINO_ACIDS:
                raise ValueError(f"line {reader.line_number}: unexpected amino-acid order {alphabet!r}")
            transition_header = tuple(reader.read("transition header").split())
            if transition_header != TRANSITIONS:
                raise ValueError(
                    f"line {reader.line_number}: unexpected transition columns {transition_header!r}"
                )

            compo = reader.read("COMPO match row").split()
            if not compo or compo[0] != "COMPO":
                raise ValueError(f"line {reader.line_number}: expected COMPO row")
            _, compo_stars = parse_scores(
                compo[1:], 20, f"line {reader.line_number} COMPO match row", allow_stars=True
            )
            _, insert_stars = parse_scores(
                reader.read("COMPO insert row").split(),
                20,
                f"line {reader.line_number} COMPO insert row",
                allow_stars=True,
            )
            _, transition_stars = parse_scores(
                reader.read("COMPO transition row").split(),
                7,
                f"line {reader.line_number} COMPO transition row",
                allow_stars=True,
            )
            if compo_stars or insert_stars:
                raise ValueError(
                    f"profile {accession}: unexpected COMPO/insert sentinel before position rows"
                )

            match_values: list[float] = []
            for position in range(1, length + 1):
                match = reader.read(f"match row {position}").split()
                if not match or match[0] != str(position):
                    raise ValueError(
                        f"line {reader.line_number}: expected profile position {position}, got {match[:1]!r}"
                    )
                values, _ = parse_scores(
                    match[1:], 20, f"line {reader.line_number} match row", allow_stars=False
                )
                match_values.extend(values)
                _, stars = parse_scores(
                    reader.read(f"insert row {position}").split(),
                    20,
                    f"line {reader.line_number} insert row",
                    allow_stars=True,
                )
                insert_stars += stars
                _, stars = parse_scores(
                    reader.read(f"transition row {position}").split(),
                    7,
                    f"line {reader.line_number} transition row",
                    allow_stars=True,
                )
                transition_stars += stars

            if reader.read("record terminator").strip() != "//":
                raise ValueError(f"line {reader.line_number}: missing profile terminator")
            if insert_stars:
                raise ValueError(f"profile {accession}: unexpected insert-emission sentinel")
            if len(match_values) != length * 20:
                raise ValueError(f"profile {accession}: match-emission size mismatch")
            if len(set(match_values)) < 2:
                raise ValueError(f"profile {accession}: constant match-emission matrix")
            yield Profile(name, accession, length, tuple(match_values), transition_stars)


def validate_source(archive: Path) -> None:
    if not archive.is_file():
        raise ValueError(f"missing source archive: {archive}")
    if archive.stat().st_size != SOURCE_BYTES:
        raise ValueError(
            f"source byte size mismatch: expected {SOURCE_BYTES}, got {archive.stat().st_size}"
        )
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    with archive.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            md5.update(chunk)
            sha256.update(chunk)
    if md5.hexdigest() != SOURCE_MD5:
        raise ValueError(f"source MD5 mismatch: {md5.hexdigest()}")
    if sha256.hexdigest() != SOURCE_SHA256:
        raise ValueError(f"source SHA-256 mismatch: {sha256.hexdigest()}")


def sample_filename(accession: str) -> str:
    return accession.replace(".", "_") + ".bin"


def pack_profile(profile: Profile) -> bytes:
    return struct.pack(f"<{len(profile.match_values)}f", *profile.match_values)


def relative_to_data(path: Path, data_root: Path) -> str:
    try:
        return path.relative_to(data_root).as_posix()
    except ValueError as exc:
        raise ValueError(f"path is outside data root: {path}") from exc


def validate_totals(profiles: int, samples: int, values: int, sample_bytes: int, stars: int) -> None:
    observed = (profiles, samples, values, sample_bytes, stars)
    expected = (
        EXPECTED_PROFILES,
        EXPECTED_SAMPLES,
        EXPECTED_VALUES,
        EXPECTED_SAMPLE_BYTES,
        EXPECTED_TRANSITION_STARS,
    )
    if observed != expected:
        raise ValueError(f"aggregate mismatch: expected={expected} observed={observed}")


def build(args: argparse.Namespace) -> None:
    archive = args.archive.resolve()
    samples_root = args.samples_dir.resolve()
    index_path = args.index.resolve()
    stats_path = args.stats.resolve()
    data_root = args.data_root.resolve()
    validate_source(archive)

    output_dir = samples_root / SERIES_ID
    temporary_dir = samples_root / f".{SERIES_ID}.tmp"
    if temporary_dir.exists():
        shutil.rmtree(temporary_dir)
    temporary_dir.mkdir(parents=True)

    rows: list[dict[str, object]] = []
    profile_count = 0
    transition_stars = 0
    total_values = 0
    total_bytes = 0
    aggregate_sha256 = hashlib.sha256()
    accessions: set[str] = set()
    try:
        for profile in iter_profiles(archive):
            profile_count += 1
            transition_stars += profile.transition_stars
            if profile.accession in accessions:
                raise ValueError(f"duplicate accession: {profile.accession}")
            accessions.add(profile.accession)
            if profile.length < MIN_PROFILE_LENGTH:
                continue
            payload = pack_profile(profile)
            filename = sample_filename(profile.accession)
            temporary_path = temporary_dir / filename
            temporary_path.write_bytes(payload)
            final_path = output_dir / filename
            digest = hashlib.sha256(payload).hexdigest()
            aggregate_sha256.update(payload)
            value_count = len(profile.match_values)
            rows.append(
                {
                    "dataset_id": DATASET_ID,
                    "series_id": SERIES_ID,
                    "role": "primary",
                    "sample_path": relative_to_data(final_path, data_root),
                    "numeric_kind": "float",
                    "bit_width": 32,
                    "endianness": "little",
                    "element_size_bytes": 4,
                    "sample_size_bytes": len(payload),
                    "value_count": value_count,
                    "shape": [profile.length, 20],
                    "natural_record_kind": "complete_pfam_family_profile_hmm_match_emission_matrix",
                    "source_accession": profile.accession,
                    "source_name": profile.name,
                    "sample_sha256": digest,
                }
            )
            total_values += value_count
            total_bytes += len(payload)
            if profile_count % 1_000 == 0:
                print(f"profiles_parsed={profile_count} samples_written={len(rows)}", flush=True)
        validate_totals(profile_count, len(rows), total_values, total_bytes, transition_stars)
        if output_dir.exists():
            shutil.rmtree(output_dir)
        temporary_dir.replace(output_dir)
    except Exception:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
        raise

    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_tmp = index_path.with_suffix(index_path.suffix + ".tmp")
    with index_tmp.open("w", encoding="utf-8") as destination:
        for row in rows:
            destination.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    index_tmp.replace(index_path)

    value_counts = [int(row["value_count"]) for row in rows]
    stats = {
        "dataset_id": DATASET_ID,
        "source": {
            "release": "Pfam 38.2",
            "bytes": SOURCE_BYTES,
            "md5": SOURCE_MD5,
            "sha256": SOURCE_SHA256,
        },
        "profiles_parsed": profile_count,
        "profiles_excluded_below_50_positions": profile_count - len(rows),
        "transition_stars_validated_not_emitted": transition_stars,
        "sample_count": len(rows),
        "total_values": total_values,
        "total_size_bytes": total_bytes,
        "minimum_sample_values": min(value_counts),
        "median_sample_values": statistics.median(value_counts),
        "maximum_sample_values": max(value_counts),
        "aggregate_decoded_sha256": aggregate_sha256.hexdigest(),
    }
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_tmp = stats_path.with_suffix(stats_path.suffix + ".tmp")
    stats_tmp.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    stats_tmp.replace(stats_path)
    print(json.dumps(stats, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    archive = args.archive.resolve()
    output_dir = args.samples_dir.resolve() / SERIES_ID
    index_path = args.index.resolve()
    stats_path = args.stats.resolve()
    data_root = args.data_root.resolve()
    validate_source(archive)
    if not output_dir.is_dir() or not index_path.is_file() or not stats_path.is_file():
        raise ValueError("missing built samples, index, or ingest statistics")

    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line]
    by_accession: dict[str, dict[str, object]] = {}
    for row in rows:
        accession = str(row.get("source_accession", ""))
        if not ACCESSION_RE.fullmatch(accession) or accession in by_accession:
            raise ValueError(f"invalid or duplicate indexed accession: {accession!r}")
        by_accession[accession] = row

    profile_count = 0
    sample_count = 0
    total_values = 0
    total_bytes = 0
    transition_stars = 0
    aggregate_sha256 = hashlib.sha256()
    expected_files: set[Path] = set()
    value_counts: list[int] = []
    for profile in iter_profiles(archive):
        profile_count += 1
        transition_stars += profile.transition_stars
        if profile.length < MIN_PROFILE_LENGTH:
            if profile.accession in by_accession:
                raise ValueError(f"short profile unexpectedly indexed: {profile.accession}")
            continue
        row = by_accession.get(profile.accession)
        if row is None:
            raise ValueError(f"eligible profile missing from index: {profile.accession}")
        payload = pack_profile(profile)
        path = data_root / str(row["sample_path"])
        expected_path = output_dir / sample_filename(profile.accession)
        if path != expected_path:
            raise ValueError(f"unexpected sample path for {profile.accession}: {path}")
        if not path.is_file():
            raise ValueError(f"missing sample: {path}")
        actual = path.read_bytes()
        if actual != payload:
            raise ValueError(f"sample differs from source conversion: {profile.accession}")
        digest = hashlib.sha256(actual).hexdigest()
        expected_metadata = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": len(actual),
            "value_count": len(profile.match_values),
            "shape": [profile.length, 20],
            "natural_record_kind": "complete_pfam_family_profile_hmm_match_emission_matrix",
            "source_name": profile.name,
            "sample_sha256": digest,
        }
        for key, expected in expected_metadata.items():
            if row.get(key) != expected:
                raise ValueError(
                    f"index mismatch accession={profile.accession} key={key}: "
                    f"expected={expected!r} actual={row.get(key)!r}"
                )
        expected_files.add(path)
        aggregate_sha256.update(actual)
        sample_count += 1
        total_values += len(profile.match_values)
        total_bytes += len(actual)
        value_counts.append(len(profile.match_values))
        if profile_count % 1_000 == 0:
            print(f"profiles_verified={profile_count} samples_verified={sample_count}", flush=True)

    validate_totals(profile_count, sample_count, total_values, total_bytes, transition_stars)
    if len(rows) != sample_count:
        raise ValueError(f"index row count mismatch: rows={len(rows)} samples={sample_count}")
    actual_files = set(output_dir.glob("*.bin"))
    if actual_files != expected_files:
        missing = sorted(str(path) for path in expected_files - actual_files)[:5]
        extra = sorted(str(path) for path in actual_files - expected_files)[:5]
        raise ValueError(f"sample file set mismatch: missing={missing} extra={extra}")

    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    expected_stats = {
        "profiles_parsed": profile_count,
        "profiles_excluded_below_50_positions": profile_count - sample_count,
        "transition_stars_validated_not_emitted": transition_stars,
        "sample_count": sample_count,
        "total_values": total_values,
        "total_size_bytes": total_bytes,
        "minimum_sample_values": min(value_counts),
        "median_sample_values": statistics.median(value_counts),
        "maximum_sample_values": max(value_counts),
        "aggregate_decoded_sha256": aggregate_sha256.hexdigest(),
    }
    for key, expected in expected_stats.items():
        if stats.get(key) != expected:
            raise ValueError(
                f"ingest stats mismatch key={key}: expected={expected!r} actual={stats.get(key)!r}"
            )
    if statistics.median(value_counts) < 1_000:
        raise ValueError("median natural-record sample is below the 1,000-value floor")
    if total_bytes > 1_000_000_000:
        raise ValueError("primary output exceeds the 1 GB cap")
    print(
        f"verified profiles={profile_count} samples={sample_count} values={total_values} "
        f"bytes={total_bytes} median_values={statistics.median(value_counts):g} "
        f"aggregate_sha256={aggregate_sha256.hexdigest()}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--samples-dir", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "build":
        build(args)
    else:
        verify(args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, EOFError, UnicodeError, ValueError, struct.error) as exc:
        raise SystemExit(f"{DATASET_ID}: {exc}") from exc
