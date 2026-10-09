#!/usr/bin/env python3
"""Build and verify USCRN subhourly 5-minute relative-humidity uint8 samples.

build:  whitespace-split parse of each pinned station-year file; keep rows
        with RH_FLAG == 0 and 0 <= RELATIVE_HUMIDITY <= 100, in file (UTC
        time) order, one uint8 sample per station-year.
verify: independent fixed-width re-derivation (readme cols 95-99 for RH,
        col 101 for RH_FLAG), byte comparison with every sample, index and
        manifest consistency, and degeneracy checks.

Pure standard library.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import tomllib
from collections import Counter
from pathlib import Path

DATASET_ID = "noaa_uscrn_subhourly_relative_humidity_u8"
SERIES_ID = "uscrn_rh_5min_u8"
PREFIX = "CRNS0101-05-2024-"
LINE_BYTES = 135
MIN_VALUES = 1000  # station-years with fewer valid RH values are excluded
EXPECTED_SOURCES = 159


def load_sources(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            parts += [""] * (len(header) - len(parts))
            rows.append(dict(zip(header, parts)))
    if len(rows) != EXPECTED_SOURCES:
        raise SystemExit(f"expected {EXPECTED_SOURCES} sources, found {len(rows)}")
    return rows


def station_of(filename: str) -> str:
    if not (filename.startswith(PREFIX) and filename.endswith(".txt")):
        raise SystemExit(f"unexpected source filename {filename}")
    return filename[len(PREFIX):-4]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def classify(rh: int, flag: str) -> str:
    if flag == "0" and 0 <= rh <= 100:
        return "kept"
    if rh == -9999:
        return "missing_sentinel_-9999"
    if flag == "3":
        return "flag3_erroneous"
    if flag == "1":
        return "flag1_overflow"
    if flag == "0":
        return "flag0_out_of_range"
    return f"flag{flag}_other"


def parse_split(path: Path) -> tuple[bytearray, Counter, str, str, str, int]:
    """Build-side parser: whitespace split, 23 fields, RH = field 15, flag = 16."""
    values = bytearray()
    counts: Counter = Counter()
    wbanno = None
    prev = ""
    first = last = ""
    rows = 0
    with path.open("r", encoding="ascii") as fh:
        for lineno, line in enumerate(fh, 1):
            fields = line.split()
            if len(fields) != 23:
                raise SystemExit(f"{path.name}:{lineno}: expected 23 fields, got {len(fields)}")
            if wbanno is None:
                wbanno = fields[0]
            elif fields[0] != wbanno:
                raise SystemExit(f"{path.name}:{lineno}: WBANNO changed")
            stamp = fields[1] + fields[2]
            if len(stamp) != 12 or not stamp.isdigit() or stamp <= prev:
                raise SystemExit(f"{path.name}:{lineno}: UTC timestamp not strictly increasing ({stamp})")
            prev = stamp
            rows += 1
            rh = int(fields[15])
            flag = fields[16]
            kind = classify(rh, flag)
            counts[kind] += 1
            if kind == "kept":
                values.append(rh)
                if not first:
                    first = stamp
                last = stamp
    return values, counts, wbanno or "", first, last, rows


def parse_fixed(path: Path) -> tuple[bytes, Counter, int]:
    """Verify-side parser: fixed-width columns documented in readme.txt."""
    data = path.read_bytes()
    if len(data) % LINE_BYTES:
        raise SystemExit(f"{path.name}: size not a multiple of {LINE_BYTES}")
    out = bytearray()
    counts: Counter = Counter()
    rows = len(data) // LINE_BYTES
    for i in range(rows):
        line = data[i * LINE_BYTES:(i + 1) * LINE_BYTES]
        if line[-1:] != b"\n" or line[93:94] != b" " or line[99:100] != b" " or line[101:102] != b" ":
            raise SystemExit(f"{path.name}:{i + 1}: fixed-width layout violated")
        rh = int(line[94:99])
        flag = line[100:101].decode("ascii")
        kind = classify(rh, flag)
        counts[kind] += 1
        if kind == "kept":
            out.append(rh)
    return bytes(out), counts, rows


def value_stats(values: bytes) -> dict:
    hist = Counter(values)
    top_value, top_count = hist.most_common(1)[0]
    return {
        "min": min(values),
        "max": max(values),
        "distinct_values": len(hist),
        "top_value": top_value,
        "top_value_fraction": round(top_count / len(values), 6),
        "mean": round(sum(values) / len(values), 4),
    }


def paths(repo_root: Path, data_dir: str) -> dict:
    root = Path(data_dir)
    if not root.is_absolute():
        root = repo_root / root
    return {
        "root": root,
        "downloads": root / "downloads" / DATASET_ID / "2024",
        "samples": root / "samples" / DATASET_ID / SERIES_ID,
        "index": root / "index" / DATASET_ID / "samples.jsonl",
        "stats": root / "filtered" / DATASET_ID / "ingest_stats.json",
    }


def build(args: argparse.Namespace) -> None:
    p = paths(Path(args.repo_root), args.data_dir)
    sources = load_sources(Path(args.sources))
    p["samples"].mkdir(parents=True, exist_ok=True)
    p["index"].parent.mkdir(parents=True, exist_ok=True)
    p["stats"].parent.mkdir(parents=True, exist_ok=True)
    for stale in p["samples"].glob("*.bin"):
        stale.unlink()

    index_rows = []
    per_source = []
    totals: Counter = Counter()
    for src in sources:
        filename = src["filename"]
        station = station_of(filename)
        path = p["downloads"] / filename
        if not path.is_file():
            raise SystemExit(f"missing local source {path}; run download.sh first")
        if path.stat().st_size != int(src["size_bytes"]):
            raise SystemExit(f"size mismatch for {filename}")
        source_sha = sha256_file(path)
        if src.get("sha256", "-") not in ("", "-") and src["sha256"] != source_sha:
            raise SystemExit(f"SHA-256 mismatch for {filename}")
        values, counts, wbanno, first, last, rows = parse_split(path)
        totals.update(counts)
        totals["rows_total"] += rows
        record = {
            "station": station,
            "wbanno": wbanno,
            "source_file": filename,
            "source_sha256": source_sha,
            "rows_total": rows,
            "dropped": {k: v for k, v in sorted(counts.items()) if k != "kept"},
            "value_count": len(values),
        }
        if len(values) < MIN_VALUES:
            record["excluded"] = f"fewer than {MIN_VALUES} valid RH values"
            per_source.append(record)
            print(f"exclude station={station} kept={len(values)} rows={rows}")
            continue
        vstats = value_stats(bytes(values))
        if vstats["distinct_values"] < 2:
            raise SystemExit(f"constant RH series for {station}")
        out = p["samples"] / f"{station}.bin"
        out.write_bytes(bytes(values))
        record.update(vstats)
        record.update({"first_kept_utc": first, "last_kept_utc": last,
                       "sample_sha256": hashlib.sha256(values).hexdigest()})
        per_source.append(record)
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": str(out.relative_to(p["root"])),
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": len(values),
            "value_count": len(values),
            "station": station,
            "wbanno": wbanno,
            "source_file": filename,
            "source_sha256": source_sha,
            "rows_total": rows,
            "rows_dropped": rows - len(values),
            "first_kept_utc": first,
            "last_kept_utc": last,
            "min": vstats["min"],
            "max": vstats["max"],
            "distinct_values": vstats["distinct_values"],
            "top_value_fraction": vstats["top_value_fraction"],
            "sample_sha256": record["sample_sha256"],
        })
        print(f"sample station={station} values={len(values)} dropped={rows - len(values)} "
              f"range={vstats['min']}..{vstats['max']} top={vstats['top_value']}@{vstats['top_value_fraction']}")

    index_rows.sort(key=lambda r: r["sample_path"])
    with p["index"].open("w", encoding="utf-8") as fh:
        for row in index_rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    sizes = [r["value_count"] for r in index_rows]
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sources": len(sources),
        "samples": len(index_rows),
        "excluded": [r["station"] for r in per_source if "excluded" in r],
        "total_values": sum(sizes),
        "total_size_bytes": sum(sizes),
        "min_sample_values": min(sizes),
        "median_sample_values": statistics.median(sizes),
        "max_sample_values": max(sizes),
        "row_totals": dict(sorted(totals.items())),
        "per_source": per_source,
    }
    p["stats"].write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "per_source"}, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    repo_root = Path(args.repo_root)
    p = paths(repo_root, args.data_dir)
    sources = load_sources(Path(args.sources))
    manifest = tomllib.loads((Path(args.sources).parent / "manifest.toml").read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1 or series[0].get("role") != "primary":
        raise SystemExit("manifest must declare exactly one primary series " + SERIES_ID)
    series = series[0]

    rows = [json.loads(l) for l in p["index"].read_text(encoding="utf-8").splitlines() if l.strip()]
    by_path = {r["sample_path"]: r for r in rows}
    if len(by_path) != len(rows):
        raise SystemExit("duplicate sample_path in index")
    on_disk = {str(f.relative_to(p["root"])) for f in p["samples"].glob("*")}
    if on_disk != set(by_path):
        raise SystemExit(f"sample files and index disagree: extra={sorted(on_disk - set(by_path))[:5]} "
                         f"missing={sorted(set(by_path) - on_disk)[:5]}")

    expected_paths = set()
    hashes = set()
    total_bytes = 0
    sizes = []
    excluded = []
    dominated = []
    for src in sources:
        filename = src["filename"]
        station = station_of(filename)
        path = p["downloads"] / filename
        if path.stat().st_size != int(src["size_bytes"]):
            raise SystemExit(f"size mismatch for {filename}")
        if src.get("sha256", "-") not in ("", "-") and sha256_file(path) != src["sha256"]:
            raise SystemExit(f"SHA-256 mismatch for {filename}")
        expected, counts, nrows = parse_fixed(path)
        rel = f"samples/{DATASET_ID}/{SERIES_ID}/{station}.bin"
        if len(expected) < MIN_VALUES:
            excluded.append(station)
            if rel in by_path:
                raise SystemExit(f"{station}: below {MIN_VALUES} values but present in output")
            continue
        expected_paths.add(rel)
        row = by_path.get(rel)
        if row is None:
            raise SystemExit(f"{station}: expected sample missing from index")
        actual = (p["root"] / rel).read_bytes()
        if actual != expected:
            raise SystemExit(f"{station}: sample bytes differ from fixed-width re-derivation")
        if counts["flag0_out_of_range"]:
            print(f"note station={station} flag0_out_of_range={counts['flag0_out_of_range']}")
        hist = Counter(actual)
        if len(hist) < 2:
            raise SystemExit(f"{station}: constant series")
        if max(actual) > 100:
            raise SystemExit(f"{station}: RH above 100")
        top_fraction = hist.most_common(1)[0][1] / len(actual)
        if top_fraction > 0.5:
            dominated.append((station, hist.most_common(1)[0][0], round(top_fraction, 4)))
        checks = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "uint",
            "bit_width": 8, "endianness": "little", "element_size_bytes": 1,
            "sample_size_bytes": len(actual), "value_count": len(actual),
            "rows_total": nrows, "rows_dropped": nrows - len(actual),
            "min": min(actual), "max": max(actual), "distinct_values": len(hist),
            "sample_sha256": hashlib.sha256(actual).hexdigest(),
        }
        for key, want in checks.items():
            if row.get(key) != want:
                raise SystemExit(f"{station}: index {key}={row.get(key)!r}, expected {want!r}")
        digest = checks["sample_sha256"]
        if digest in hashes:
            raise SystemExit(f"{station}: duplicate sample content")
        hashes.add(digest)
        total_bytes += len(actual)
        sizes.append(len(actual))

    if expected_paths != set(by_path):
        raise SystemExit("index contains samples not derived from pinned sources")
    if series.get("sample_count") != len(sizes):
        raise SystemExit(f"manifest sample_count={series.get('sample_count')} realized={len(sizes)}")
    if series.get("total_size_bytes") != total_bytes:
        raise SystemExit(f"manifest total_size_bytes={series.get('total_size_bytes')} realized={total_bytes}")
    median = statistics.median(sizes)
    if total_bytes < 10_000 or median < 1000:  # u8: values == bytes; floor is 10k values or 100 KB
        raise SystemExit(f"below floor: total={total_bytes} median={median}")
    if total_bytes > 1_000_000_000:
        raise SystemExit("primary output exceeds 1 GB")
    for station, value, fraction in dominated:
        print(f"note dominated station={station} value={value} fraction={fraction}")
    print(json.dumps({"samples": len(sizes), "total_bytes": total_bytes, "median_values": median,
                      "min_values": min(sizes), "max_values": max(sizes), "excluded": excluded,
                      "dominated_samples": len(dominated)}, sort_keys=True))
    print("verify ok")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["build", "verify"])
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--data-dir", default=".data")
    ap.add_argument("--sources", required=True)
    args = ap.parse_args()
    (build if args.mode == "build" else verify)(args)


if __name__ == "__main__":
    sys.exit(main())
