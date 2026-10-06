#!/usr/bin/env python3
"""Independent verifier for cesnet_ts24_institution_traffic_bytes_u64.

Re-reads the pinned archive with a separate parser (csv module + array),
re-derives every institution's uint64 n_bytes and uint32 id_time arrays, and
compares them byte for byte with the emitted samples, the sample index, the
manifest counts and the pinned per-institution expectations. Shares no code
with build_samples.py.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import statistics
import sys
import tarfile
import tomllib
from array import array
from pathlib import Path

DATASET_ID = "cesnet_ts24_institution_traffic_bytes_u64"
PRIMARY = "institution_n_bytes_u64"
AUX = "institution_id_time_u32"
TEN_MINUTE_PREFIX = "institutions/agg_10_minutes/"
LIMIT_U64 = 18446744073709551615
LIMIT_U32 = 4294967295
MIN_TOTAL_VALUES = 10_000
MIN_MEDIAN_VALUES = 1_000


class VerifyError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerifyError(message)


def ascii_digits(text: str) -> bool:
    return text.isascii() and text.isdigit()


def file_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1 << 22)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def little_endian(values: list[int], code: str, itemsize: int) -> bytes:
    packed = array(code, values)
    require(packed.itemsize == itemsize, f"array('{code}') itemsize {packed.itemsize} != {itemsize}")
    if sys.byteorder != "little":
        packed.byteswap()
    return packed.tobytes()


def grid_size(times_path: Path) -> int:
    with tarfile.open(times_path, mode="r:gz") as archive:
        handle = archive.extractfile("times/times_10_minutes.csv")
        text = handle.read().decode("ascii")
    reader = csv.reader(io.StringIO(text, newline=""))
    header = next(reader)
    require(header == ["id_time", "time"], f"time grid header {header}")
    count = 0
    for row in reader:
        require(len(row) == 2 and ascii_digits(row[0]) and int(row[0]) == count, f"time grid row {count}: {row}")
        count += 1
    return count


def rederive(text: str, member: str, windows: int) -> tuple[list[int], list[int]]:
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    header = next(reader)
    require(header.count("id_time") == 1 and header.count("n_bytes") == 1, f"{member}: header {header[:6]}")
    t_col = header.index("id_time")
    b_col = header.index("n_bytes")
    times: list[int] = []
    counts: list[int] = []
    for row in reader:
        require(len(row) == len(header), f"{member}: row width {len(row)} != {len(header)} at row {len(counts) + 2}")
        t_text, b_text = row[t_col], row[b_col]
        require(ascii_digits(t_text), f"{member}: bad id_time {t_text!r}")
        require(ascii_digits(b_text), f"{member}: bad n_bytes {b_text!r} (missing or non-integer values are fatal)")
        t_value, b_value = int(t_text), int(b_text)
        require(not times or t_value > times[-1], f"{member}: id_time {t_value} not increasing")
        require(0 <= t_value < windows, f"{member}: id_time {t_value} outside grid")
        require(b_value <= LIMIT_U64, f"{member}: n_bytes {b_value} exceeds uint64")
        times.append(t_value)
        counts.append(b_value)
    return times, counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--times", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--archive-bytes", type=int, default=479428489)
    parser.add_argument("--archive-md5", default="ab3e15fb8dc9b7120ddb2318795b6812")
    parser.add_argument("--times-md5", default="a03813763e07646ca38f17ffd53e549e")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--expected-institutions", type=int, default=283)
    parser.add_argument("--expected-empty", default="148,260,267,279,283")
    args = parser.parse_args()
    try:
        run(args)
    except VerifyError as exc:
        print(f"VERIFY FAILED: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


def run(args: argparse.Namespace) -> None:
    require(args.archive.stat().st_size == args.archive_bytes, "archive size mismatch")
    require(file_md5(args.archive) == args.archive_md5, "archive md5 mismatch")
    require(file_md5(args.times) == args.times_md5, "times.tar.gz md5 mismatch")
    record = json.loads(args.record.read_text(encoding="utf-8"))
    require(record["metadata"]["license"]["id"] == "cc-by-4.0", "record license is not cc-by-4.0")
    windows = grid_size(args.times)
    print(f"identity_ok archive_md5={args.archive_md5} grid_windows={windows}", flush=True)

    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    require(manifest["dataset_id"] == DATASET_ID, "manifest dataset_id mismatch")
    series_meta = {entry["id"]: entry for entry in manifest["series"]}
    require(set(series_meta) == {PRIMARY, AUX}, f"manifest series {sorted(series_meta)}")
    require(series_meta[PRIMARY]["role"] == "primary" and series_meta[AUX]["role"] == "auxiliary", "manifest roles")

    expected: dict[int, dict[str, str]] = {}
    with args.expected.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            expected[int(row["institution_id"])] = row

    data_root: Path = args.data_root
    sample_dir = {series: data_root / "samples" / DATASET_ID / series for series in (PRIMARY, AUX)}
    pinned_empty = sorted({int(item) for item in args.expected_empty.split(",") if item.strip()})
    identifiers: list[int] | None = None
    seen: dict[int, dict] = {}
    empty: set[int] = set()
    with tarfile.open(args.archive, mode="r|gz", bufsize=1 << 20) as archive:
        for member in archive:
            if member.name == "institutions/identifiers.csv":
                text = archive.extractfile(member).read().decode("ascii")
                rows = list(csv.reader(io.StringIO(text, newline="")))
                require(rows[0] == ["id_institution"], f"identifiers header {rows[0]}")
                require(all(len(row) == 1 and ascii_digits(row[0]) for row in rows[1:]), "identifiers rows")
                identifiers = [int(row[0]) for row in rows[1:]]
                continue
            if not (member.isfile() and member.name.startswith(TEN_MINUTE_PREFIX)):
                continue
            stem = member.name[len(TEN_MINUTE_PREFIX):]
            if not stem.endswith(".csv") or not ascii_digits(stem[:-4]):
                continue
            institution = int(stem[:-4])
            require(institution not in seen and institution not in empty, f"duplicate member {member.name}")
            text = archive.extractfile(member).read().decode("ascii")
            require("\r" not in text, f"{member.name}: carriage return found; expected LF-only CSV")
            times, counts = rederive(text, member.name, windows)
            if not counts:
                empty.add(institution)
                continue
            primary_bytes = little_endian(counts, "Q", 8)
            aux_bytes = little_endian(times, "I", 4)
            name = f"institution_{institution:03d}.bin"
            require((sample_dir[PRIMARY] / name).read_bytes() == primary_bytes, f"primary sample {name} differs from source")
            require((sample_dir[AUX] / name).read_bytes() == aux_bytes, f"auxiliary sample {name} differs from source")
            distinct = len(set(counts))
            require(distinct >= 2, f"primary sample {name} is constant")
            seen[institution] = {
                "value_count": len(counts),
                "first_id_time": times[0],
                "last_id_time": times[-1],
                "min": min(counts),
                "max": max(counts),
                "values_ge_2_32": sum(value > LIMIT_U32 for value in counts),
                "distinct_values": distinct,
                "primary_sha256": hashlib.sha256(primary_bytes).hexdigest(),
                "aux_sha256": hashlib.sha256(aux_bytes).hexdigest(),
            }
    require(identifiers is not None, "identifiers.csv missing")
    require(len(identifiers) == args.expected_institutions, f"{len(identifiers)} identifiers")
    require(len(expected) == args.expected_institutions - len(pinned_empty),
            f"expectation file has {len(expected)} rows, expected {args.expected_institutions - len(pinned_empty)}")
    require(sorted(empty) == pinned_empty, f"header-only members {sorted(empty)} differ from pinned {pinned_empty}")
    require(sorted(set(seen) | empty) == sorted(identifiers), "re-derived institutions disagree with identifiers.csv")
    require(sorted(expected) == sorted(seen), "expectation file institutions disagree with archive")
    for institution, info in seen.items():
        pinned = expected[institution]
        for key, value in info.items():
            require(str(value) == pinned[key], f"institution {institution}: {key}={value} but pinned {pinned[key]}")
    print(f"rederive_ok institutions={len(seen)} pinned_expectations_match=1", flush=True)

    for series in (PRIMARY, AUX):
        on_disk = sorted(path.name for path in sample_dir[series].iterdir())
        wanted = sorted(f"institution_{institution:03d}.bin" for institution in seen)
        require(on_disk == wanted, f"{series}: sample files on disk do not match the institution set")

    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    index_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    require(len(index_rows) == 2 * len(seen), f"index has {len(index_rows)} rows, expected {2 * len(seen)}")
    totals = {PRIMARY: [0, 0], AUX: [0, 0]}
    keyed = {}
    for row in index_rows:
        key = (row["series_id"], row["institution_id"])
        require(key not in keyed, f"duplicate index row {key}")
        keyed[key] = row
    for institution, info in seen.items():
        for series, element, width, digest in ((PRIMARY, 8, 64, "primary_sha256"), (AUX, 4, 32, "aux_sha256")):
            row = keyed.get((series, institution))
            require(row is not None, f"index lacks {series} institution {institution}")
            want = {
                "dataset_id": DATASET_ID,
                "series_id": series,
                "role": "primary" if series == PRIMARY else "auxiliary",
                "sample_path": f"samples/{DATASET_ID}/{series}/institution_{institution:03d}.bin",
                "numeric_kind": "uint",
                "bit_width": width,
                "endianness": "little",
                "element_size_bytes": element,
                "sample_size_bytes": info["value_count"] * element,
                "value_count": info["value_count"],
                "first_id_time": info["first_id_time"],
                "last_id_time": info["last_id_time"],
                "sha256": info[digest],
            }
            if series == PRIMARY:
                want["min"] = info["min"]
                want["max"] = info["max"]
            for key, value in want.items():
                require(row.get(key) == value, f"index {series}/{institution}: {key}={row.get(key)!r}, expected {value!r}")
            totals[series][0] += 1
            totals[series][1] += info["value_count"] * element
    for series in (PRIMARY, AUX):
        meta = series_meta[series]
        require(meta["numeric_kind"] == "uint" and meta["endianness"] == "little", f"manifest {series} kind/endianness")
        require(meta["bit_width"] == (64 if series == PRIMARY else 32), f"manifest {series} bit_width")
        require(meta["sample_count"] == totals[series][0], f"manifest {series} sample_count {meta['sample_count']} != {totals[series][0]}")
        require(meta["total_size_bytes"] == totals[series][1], f"manifest {series} total_size_bytes {meta['total_size_bytes']} != {totals[series][1]}")

    counts = [info["value_count"] for info in seen.values()]
    total = sum(counts)
    median = statistics.median(counts)
    require(total >= MIN_TOTAL_VALUES, f"primary values {total} below floor")
    require(median >= MIN_MEDIAN_VALUES, f"median primary sample values {median} below floor")
    ge32 = sum(info["values_ge_2_32"] for info in seen.values())
    print(
        f"verify_ok samples={len(seen)} empty_source_members={sorted(empty)} primary_values={total} primary_bytes={total * 8} "
        f"median_values={median} fraction_ge_2_32={ge32 / total:.6f}",
        flush=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
