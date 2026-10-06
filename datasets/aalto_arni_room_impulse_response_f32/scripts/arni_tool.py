#!/usr/bin/env python3
"""Local parsing/validation CLI used by discover.sh and download.sh.

All network I/O is performed by curl in the shell scripts; every subcommand
here only reads files that curl already wrote.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arni_zip as az  # noqa: E402

RECORD_ID = 6985104
LICENSE_ID = "cc-by-4.0"
CSV_NAME = "combinations_setup.csv"
ARCHIVE_FIELDS = [
    "archive",
    "size_bytes",
    "zenodo_md5",
    "eocd_kind",
    "cd_offset",
    "cd_size",
    "entries",
    "cd_sha256",
]
SELECTION_FIELDS = [
    "archive",
    "member",
    "num_closed",
    "num_comb",
    "mic",
    "sweep",
    "local_header_offset",
    "compressed_size",
    "uncompressed_size",
    "crc32",
    "range_start",
    "range_end",
]


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def record_files(record_path: Path) -> dict[str, dict]:
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if int(record.get("id") or 0) != RECORD_ID:
        raise SystemExit(f"unexpected Zenodo record id {record.get('id')!r}")
    metadata = record.get("metadata") or {}
    title = html.unescape(str(metadata.get("title", "")))
    if "arni" not in title.lower() or "impulse response" not in title.lower():
        raise SystemExit(f"record title does not identify the Arni impulse-response dataset: {title!r}")
    license_value = metadata.get("license")
    license_id = (
        str(license_value.get("id") or "") if isinstance(license_value, dict) else str(license_value or "")
    )
    if license_id.lower() != LICENSE_ID:
        raise SystemExit(f"record license changed: {license_id!r}")
    access = record.get("access") or {}
    if isinstance(access, dict) and access.get("files") not in (None, "public"):
        raise SystemExit(f"record files are not public: {access!r}")
    files = {}
    for item in record.get("files") or []:
        if isinstance(item, dict) and item.get("key"):
            files[item["key"]] = item
    return files


def cmd_archives_from_record(args: argparse.Namespace) -> None:
    files = record_files(Path(args.record))
    for key in sorted(files):
        if key.startswith("IR_Arni_upload_numClosed_") and key.endswith(".zip"):
            item = files[key]
            checksum = str(item.get("checksum") or "")
            print(f"{key}\t{int(item['size'])}\t{checksum.removeprefix('md5:')}")


def cmd_check_record(args: argparse.Namespace) -> None:
    files = record_files(Path(args.record))
    pinned = read_tsv(Path(args.archives))
    zips = sorted(k for k in files if k.endswith(".zip"))
    if zips != sorted(row["archive"] for row in pinned):
        raise SystemExit(f"record ZIP inventory changed: {zips}")
    for row in pinned:
        item = files[row["archive"]]
        if int(item.get("size") or 0) != int(row["size_bytes"]):
            raise SystemExit(f"{row['archive']}: size changed to {item.get('size')!r}")
        if str(item.get("checksum") or "").lower() != f"md5:{row['zenodo_md5']}":
            raise SystemExit(f"{row['archive']}: checksum changed to {item.get('checksum')!r}")
    csv_item = files.get(CSV_NAME)
    if not csv_item or int(csv_item.get("size") or 0) != args.csv_size or str(
        csv_item.get("checksum") or ""
    ).lower() != f"md5:{args.csv_md5}":
        raise SystemExit(f"{CSV_NAME} metadata changed: {csv_item!r}")
    print(f"record_validation=ok record={RECORD_ID} license={LICENSE_ID} archives={len(pinned)}")


def check_range_response(headers: Path, payload: Path, start: int, end: int, total: int) -> None:
    status, content_range = az.parse_final_http_status(headers.read_text(encoding="iso-8859-1"))
    if status != 206 or content_range is None:
        raise SystemExit(f"{payload.name}: server did not honour the byte range (status={status})")
    if content_range != (start, end, total):
        raise SystemExit(f"{payload.name}: Content-Range {content_range} != expected {(start, end, total)}")
    size = payload.stat().st_size
    if size != end - start + 1:
        raise SystemExit(f"{payload.name}: received {size} bytes, expected {end - start + 1}")


def cmd_check_range(args: argparse.Namespace) -> None:
    check_range_response(Path(args.headers), Path(args.file), args.start, args.end, args.total)
    print(f"range_ok file={Path(args.file).name} start={args.start} end={args.end} total={args.total}")


def cmd_locate(args: argparse.Namespace) -> None:
    tail_path = Path(args.tail)
    tail = tail_path.read_bytes()
    start = args.size - len(tail)
    check_range_response(Path(args.headers), tail_path, start, args.size - 1, args.size)
    loc = az.locate_central_directory(tail, start, args.size)
    print(f"{loc.cd_offset}\t{loc.cd_offset + loc.cd_size - 1}")


def load_archive(meta_dir: Path, archive: str, size: int) -> tuple[az.CentralDirectoryLocation, bytes, list[az.Member]]:
    tail_path = meta_dir / f"{archive}.tail.bin"
    tail = tail_path.read_bytes()
    check_range_response(meta_dir / f"{archive}.tail.headers", tail_path, size - len(tail), size - 1, size)
    loc = az.locate_central_directory(tail, size - len(tail), size)
    cd_path = meta_dir / f"{archive}.cd.bin"
    check_range_response(
        meta_dir / f"{archive}.cd.headers", cd_path, loc.cd_offset, loc.cd_offset + loc.cd_size - 1, size
    )
    cd = cd_path.read_bytes()
    members = az.parse_central_directory(cd, loc.entries)
    for member in members:
        if az.parse_member_name(member.name) is None:
            raise SystemExit(f"{archive}: unexpected member name {member.name!r}")
    return loc, cd, members


def cmd_derive(args: argparse.Namespace) -> None:
    meta_dir = Path(args.meta_dir)
    inventory = [line.split("\t") for line in Path(args.inventory).read_text(encoding="utf-8").splitlines() if line]
    archive_rows = []
    members_by_archive: dict[str, list[az.Member]] = {}
    locations: dict[str, az.CentralDirectoryLocation] = {}
    total_entries = 0
    for archive, size_text, md5 in inventory:
        size = int(size_text)
        loc, cd, members = load_archive(meta_dir, archive, size)
        members_by_archive[archive] = members
        locations[archive] = loc
        total_entries += len(members)
        archive_rows.append(
            {
                "archive": archive,
                "size_bytes": size,
                "zenodo_md5": md5,
                "eocd_kind": "zip64" if loc.zip64 else "classic",
                "cd_offset": loc.cd_offset,
                "cd_size": loc.cd_size,
                "entries": loc.entries,
                "cd_sha256": hashlib.sha256(cd).hexdigest(),
            }
        )
    selected = az.select_members(members_by_archive)
    selection_rows = []
    for archive, member, key in selected:
        if member.uncompressed_size != az.WAV_MEMBER_BYTES or member.method != 8:
            raise SystemExit(f"{member.name}: unexpected size/method {member.uncompressed_size}/{member.method}")
        start, end = az.member_fetch_range(member, locations[archive].cd_offset)
        selection_rows.append(
            {
                "archive": archive,
                "member": member.name,
                "num_closed": key[0],
                "num_comb": key[1],
                "mic": key[2],
                "sweep": key[3],
                "local_header_offset": member.local_header_offset,
                "compressed_size": member.compressed_size,
                "uncompressed_size": member.uncompressed_size,
                "crc32": f"{member.crc32:08x}",
                "range_start": start,
                "range_end": end,
            }
        )
    write_tsv(Path(args.archives_out), ARCHIVE_FIELDS, archive_rows)
    write_tsv(Path(args.selection_out), SELECTION_FIELDS, selection_rows)
    range_bytes = sum(int(r["range_end"]) - int(r["range_start"]) + 1 for r in selection_rows)
    print(
        f"derive_ok archives={len(archive_rows)} entries={total_entries} selected={len(selection_rows)} "
        f"member_range_bytes={range_bytes}"
    )


def cmd_compare(args: argparse.Namespace) -> None:
    for derived, pinned in ((args.derived_archives, args.pinned_archives), (args.derived_selection, args.pinned_selection)):
        a = Path(derived).read_text(encoding="utf-8")
        b = Path(pinned).read_text(encoding="utf-8")
        if a != b:
            raise SystemExit(f"derived table {derived} differs from pinned {pinned}; upstream archive changed")
    print("pinned_tables=ok")


def cmd_cd_ok(args: argparse.Namespace) -> None:
    """Exit 0 when a cached central directory still matches its pinned SHA-256."""
    pinned = {row["archive"]: row for row in read_tsv(Path(args.archives))}
    cd_path = Path(args.cd)
    ok = cd_path.is_file() and sha256_file(cd_path) == pinned[args.archive]["cd_sha256"]
    raise SystemExit(0 if ok else 1)


def selection_row(selection: Path, member: str) -> dict[str, str]:
    rows = [row for row in read_tsv(selection) if row["member"] == member]
    if len(rows) != 1:
        raise SystemExit(f"member {member!r} not found exactly once in {selection}")
    return rows[0]


def member_from_row(row: dict[str, str]) -> az.Member:
    name = row["member"]
    return az.Member(
        name=name,
        flags=0,
        method=8,
        crc32=int(row["crc32"], 16),
        compressed_size=int(row["compressed_size"]),
        uncompressed_size=int(row["uncompressed_size"]),
        local_header_offset=int(row["local_header_offset"]),
        cd_name_len=len(name.encode("utf-8")),
        cd_extra_len=0,
    )


def validate_wav_bytes(wav: bytes, row: dict[str, str]) -> dict:
    if len(wav) != int(row["uncompressed_size"]):
        raise SystemExit(f"{row['member']}: WAV size {len(wav)} != {row['uncompressed_size']}")
    crc = zlib.crc32(wav) & 0xFFFFFFFF
    if f"{crc:08x}" != row["crc32"]:
        raise SystemExit(f"{row['member']}: CRC-32 {crc:08x} != pinned {row['crc32']}")
    data, _chunks = az.parse_wav_float32(wav, row["member"])
    return az.float32_stats(data, row["member"])


def cmd_extract(args: argparse.Namespace) -> None:
    row = selection_row(Path(args.selection), args.member)
    range_path = Path(args.range_file)
    check_range_response(Path(args.headers), range_path, int(row["range_start"]), int(row["range_end"]), args.total)
    wav = az.extract_member(range_path.read_bytes(), member_from_row(row))
    stats = validate_wav_bytes(wav, row)
    out = Path(args.out)
    part = out.with_name(out.name + ".part")
    part.write_bytes(wav)
    part.replace(out)
    print(
        f"member_ok {row['member']} peak={stats['peak_abs']:.6g}@{stats['peak_index']} "
        f"int16_lattice={stats['int16_lattice_fraction']:.4f} distinct={stats['distinct_bit_patterns']}"
    )


def cmd_final_check(args: argparse.Namespace) -> None:
    rows = read_tsv(Path(args.selection))
    wav_dir = Path(args.wav_dir)
    expected = {row["member"] for row in rows}
    present = {p.name for p in wav_dir.glob("*.wav")}
    stale = sorted(present - expected)
    if stale and args.prune:
        # Members cached under an earlier pinned selection are not part of
        # the current one: remove them so wav/ mirrors selection.tsv exactly.
        for name in stale:
            (wav_dir / name).unlink()
            print(f"prune_stale removed {name}")
        print(f"prune_stale removed={len(stale)}")
    elif stale:
        raise SystemExit(f"unexpected WAV files in {wav_dir}: {stale[:5]}")
    bad = []
    max_lattice = 0.0
    min_distinct = None
    for row in rows:
        path = wav_dir / row["member"]
        if not path.is_file():
            if not args.prune:
                bad.append(f"missing {row['member']}")
            continue
        try:
            stats = validate_wav_bytes(path.read_bytes(), row)
            max_lattice = max(max_lattice, stats["int16_lattice_fraction"])
            if min_distinct is None or stats["distinct_bit_patterns"] < min_distinct:
                min_distinct = stats["distinct_bit_patterns"]
        except (SystemExit, ValueError) as exc:
            bad.append(str(exc))
            path.unlink()
    if args.prune:
        print(f"prune_cached removed={len(bad)} {bad[:5]}")
        return
    if bad:
        raise SystemExit(f"{len(bad)} WAV members missing or invalid (invalid ones removed; re-run download.sh): {bad[:5]}")
    print(
        f"final_check=ok wav_members={len(rows)} max_int16_lattice_fraction={max_lattice:.6f} "
        f"min_distinct_bit_patterns={min_distinct}"
    )


def cmd_distinctness(args: argparse.Namespace) -> None:
    """Fatal check that the five receivers of each configuration differ.

    Zero-lag Pearson r over sample indices [1500, 17884) for all 10 receiver
    pairs of every selected configuration must satisfy max |r| < 0.5.  The
    largest cross-configuration same-receiver |r| is logged, not enforced.
    """
    rows = read_tsv(Path(args.selection))
    wav_dir = Path(args.wav_dir)
    windows: dict[tuple[int, int], dict[int, list[float]]] = {}
    for row in rows:
        data, _chunks = az.parse_wav_float32((wav_dir / row["member"]).read_bytes(), row["member"])
        config = (int(row["num_closed"]), int(row["num_comb"]))
        windows.setdefault(config, {})[int(row["mic"])] = az.normalized_window(data, row["member"])
    failures = []
    worst = (0.0, None)
    for config in sorted(windows):
        mics = windows[config]
        if sorted(mics) != list(az.MICS):
            raise SystemExit(f"configuration {config}: receivers {sorted(mics)} != {list(az.MICS)}")
        pair_r = {
            (a, b): az.correlation(mics[a], mics[b]) for a in az.MICS for b in az.MICS if a < b
        }
        (a, b), r = max(pair_r.items(), key=lambda item: abs(item[1]))
        print(f"receiver_distinctness numClosed={config[0]} numComb={config[1]} max_abs_r={abs(r):.4f} pair=mic{a}/mic{b}")
        if abs(r) > worst[0]:
            worst = (abs(r), config)
        if not abs(r) < az.DISTINCT_MAX_ABS_R:
            failures.append(f"numClosed={config[0]} numComb={config[1]} mic{a}/mic{b} r={r:.4f}")
    configs = sorted(windows)
    cross = (0.0, None)
    for mic in az.MICS:
        for i, first in enumerate(configs):
            for second in configs[i + 1 :]:
                r = abs(az.correlation(windows[first][mic], windows[second][mic]))
                if r > cross[0]:
                    cross = (r, (mic, first, second))
    print(f"receiver_distinctness_worst max_abs_r={worst[0]:.4f} config={worst[1]} threshold<{az.DISTINCT_MAX_ABS_R}")
    print(f"cross_configuration_same_mic_max_abs_r={cross[0]:.4f} (mic, configA, configB)={cross[1]} (informational)")
    if failures:
        raise SystemExit(f"{len(failures)} configurations repeat one response under several receiver labels: {failures}")
    print(f"receiver_distinctness=ok configurations={len(configs)}")


def cmd_check_csv(args: argparse.Namespace) -> None:
    path = Path(args.csv)
    if path.stat().st_size != args.size or md5_file(path) != args.md5 or sha256_file(path) != args.sha256:
        raise SystemExit(f"{path.name}: size/MD5/SHA-256 mismatch")
    text = path.read_text(encoding="utf-8-sig")
    lines = [line for line in re.split(r"\r?\n", text) if line.strip()]
    if not lines[0].startswith('"Panel number?'):
        raise SystemExit(f"{path.name}: unexpected header")
    print(f"csv_ok bytes={args.size} md5={args.md5}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("archives-from-record")
    p.add_argument("--record", required=True)
    p.set_defaults(func=cmd_archives_from_record)

    p = sub.add_parser("check-record")
    p.add_argument("--record", required=True)
    p.add_argument("--archives", required=True)
    p.add_argument("--csv-size", type=int, required=True)
    p.add_argument("--csv-md5", required=True)
    p.set_defaults(func=cmd_check_record)

    p = sub.add_parser("check-range")
    p.add_argument("--headers", required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--start", type=int, required=True)
    p.add_argument("--end", type=int, required=True)
    p.add_argument("--total", type=int, required=True)
    p.set_defaults(func=cmd_check_range)

    p = sub.add_parser("locate")
    p.add_argument("--tail", required=True)
    p.add_argument("--headers", required=True)
    p.add_argument("--size", type=int, required=True)
    p.set_defaults(func=cmd_locate)

    p = sub.add_parser("derive")
    p.add_argument("--meta-dir", required=True)
    p.add_argument("--inventory", required=True, help="TSV lines: archive, size, md5")
    p.add_argument("--archives-out", required=True)
    p.add_argument("--selection-out", required=True)
    p.set_defaults(func=cmd_derive)

    p = sub.add_parser("compare")
    p.add_argument("--derived-archives", required=True)
    p.add_argument("--pinned-archives", required=True)
    p.add_argument("--derived-selection", required=True)
    p.add_argument("--pinned-selection", required=True)
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("cd-ok")
    p.add_argument("--archives", required=True)
    p.add_argument("--archive", required=True)
    p.add_argument("--cd", required=True)
    p.set_defaults(func=cmd_cd_ok)

    p = sub.add_parser("extract")
    p.add_argument("--selection", required=True)
    p.add_argument("--member", required=True)
    p.add_argument("--headers", required=True)
    p.add_argument("--range-file", required=True)
    p.add_argument("--total", type=int, required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("final-check")
    p.add_argument("--selection", required=True)
    p.add_argument("--wav-dir", required=True)
    p.add_argument("--prune", action="store_true", help="delete invalid or unselected cached WAVs and exit 0")
    p.set_defaults(func=cmd_final_check)

    p = sub.add_parser("distinctness")
    p.add_argument("--selection", required=True)
    p.add_argument("--wav-dir", required=True)
    p.set_defaults(func=cmd_distinctness)

    p = sub.add_parser("check-csv")
    p.add_argument("--csv", required=True)
    p.add_argument("--size", type=int, required=True)
    p.add_argument("--md5", required=True)
    p.add_argument("--sha256", required=True)
    p.set_defaults(func=cmd_check_csv)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
