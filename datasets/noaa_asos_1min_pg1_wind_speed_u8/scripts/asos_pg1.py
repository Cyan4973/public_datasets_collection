#!/usr/bin/env python3
"""NOAA ASOS one-minute page-1 (DSI 6405) wind-speed extraction.

Subcommands:
  validate  check downloaded station-month files (used by download.sh)
  build     emit uint8 wind-speed samples + index + ingest stats
  verify    independently re-parse the downloads (regex parser, not the
            fixed-slice parser used by build) and compare every sample

Record layout (DSI 6405 documentation, confirmed on 2024 files): fixed-width
ASCII lines, 112 characters + LF.
  [0:5]   WBAN number           [5:9]   ICAO call sign
  [10:13] station call sign     [13:17] year (LST)  [17:19] month (LST)
  [19:21] day (LST)             [21:25] HHMM local  [25:29] HHMM UTC
  [29:69] two visibility extinction coefficients with D/N flags
  [69:74] 2-minute average wind direction (deg)
  [74:79] 2-minute average wind speed (kt)
  [79:84] 5-second peak wind direction (deg)
  [84:89] 5-second peak wind speed (kt)
  [89:]   runway visual range group (optional)
Each wind field is right-justified digits, "M" (missing), or blank (missing).
Wind fields are taken from fixed columns, so a missing visibility sensor
(blank columns 45-66) does not shift them.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
from pathlib import Path

DATASET_ID = "noaa_asos_1min_pg1_wind_speed_u8"
SERIES = (
    # series_id, wind field index (0=dir2, 1=spd2, 2=dirG, 3=spdG)
    ("wind_speed_2min_avg_kt_u8", 1),
    ("wind_speed_5s_peak_kt_u8", 3),
)
FIELD_SLICES = ((69, 74), (74, 79), (79, 84), (84, 89))
MIN_SAMPLE_VALUES = 1000
MAX_MODE_SHARE = 0.80
MAX_BAD_ROW_SHARE = 0.05


def read_sources(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    rows = [dict(zip(header, line.split("\t"))) for line in lines[1:] if line]
    for row in rows:
        row["size_bytes"] = int(row["size_bytes"])
    return rows


# --------------------------------------------------------------------------
# build parser: fixed slices
# --------------------------------------------------------------------------

def parse_field(text: str):
    """Return int value, None for missing, or raise ValueError if malformed.

    Digits must be right-justified (1-3 digits); the missing marker 'M' sits
    at offset 3 of the 5-character field ('   M '), as in every 2024 file.
    """
    if text == "     " or text == "   M ":
        return None
    stripped = text.lstrip(" ")
    if 1 <= len(stripped) <= 3 and stripped.isdigit() and len(text) == 5:
        return int(stripped)
    raise ValueError(text)


def _is_extinction_value(token: str) -> bool:
    if token == "M":
        return True
    body = token[1:] if token.startswith("-") else token
    whole, dot, frac = body.partition(".")
    return dot == "." and whole.isdigit() and len(frac) == 3 and frac.isdigit()


def visibility_region_ok(region: str) -> bool:
    """[29:69]: up to three (extinction value, one-letter flag) pairs.

    Square brackets (an undocumented per-value marker) are ignored here.
    """
    tokens = region.replace("[", " ").replace("]", " ").split()
    if len(tokens) % 2 or len(tokens) > 6:
        return False
    for value, flag in zip(tokens[0::2], tokens[1::2]):
        if not _is_extinction_value(value):
            return False
        if not (len(flag) == 1 and flag.isascii() and flag.isalpha()):
            return False
    return True


def rvr_tail_ok(tail: str) -> bool:
    """[89:]: blank, 'M', or one runway group like '35L60+', '31 55', '04RFFF'."""
    group = tail.replace("[", " ").replace("]", " ").strip(" ")
    if group in ("", "M"):
        return True
    if len(group) not in (5, 6) or not group[:2].isdigit() or group[2] not in "LRC ":
        return False
    rest = group[3:]
    return rest == "FFF" or (rest[:2].isdigit() and rest[2:] in ("", "+"))


def parse_file_fixed(path: Path, station: str, yyyymm: str) -> dict:
    """Two passes: structural screening, then removal of duplicated minutes.

    Some files carry two different records for the same LST minute (blocks of
    a day appearing twice with different wind); every row whose LST stamp
    occurs more than once among structural rows is dropped, since neither copy
    can be preferred.
    """
    year, month = yyyymm[:4], yyyymm[5:7]
    values = {sid: bytearray() for sid, _ in SERIES}
    counts = collections.Counter()
    kept = []  # (stamp, fields)
    with path.open("rb") as handle:
        for raw in handle:
            counts["rows"] += 1
            try:
                line = raw.decode("ascii").rstrip("\r\n")
            except UnicodeDecodeError:
                counts["bad_rows_non_ascii"] += 1
                continue
            if not line.isprintable():
                counts["bad_rows_non_ascii"] += 1
                continue
            if len(line) < 89:
                counts["bad_rows_short"] += 1
                continue
            if not (line[0:5].isdigit() and line[5:9] == station and line[9] == " "
                    and line[13:29].isdigit()):
                counts["bad_rows_prefix"] += 1
                continue
            if line[13:17] != year or line[17:19] != month:
                counts["bad_rows_other_month"] += 1
                continue
            try:
                fields = [parse_field(line[a:b]) for a, b in FIELD_SLICES]
            except ValueError:
                counts["bad_rows_wind_fields"] += 1
                continue
            if not visibility_region_ok(line[29:69]):
                counts["bad_rows_visibility_region"] += 1
                continue
            if not rvr_tail_ok(line[89:]):
                counts["bad_rows_rvr_tail"] += 1
                continue
            kept.append((line[13:25], fields))
    stamp_counts = collections.Counter(stamp for stamp, _ in kept)
    previous_stamp = None
    for stamp, fields in kept:
        if stamp_counts[stamp] > 1:
            counts["duplicate_minute_rows"] += 1
            continue
        if previous_stamp is not None and stamp < previous_stamp:
            counts["rows_out_of_order"] += 1
        previous_stamp = stamp
        counts["structural_rows"] += 1
        for sid, index in SERIES:
            value = fields[index]
            if value is None:
                counts[f"missing_{sid}"] += 1
            elif value > 255:
                counts[f"out_of_range_{sid}"] += 1
            else:
                values[sid].append(value)
    return {"values": values, "counts": dict(counts)}


# --------------------------------------------------------------------------
# verify parser: independent regex
# --------------------------------------------------------------------------

LINE_RE = re.compile(
    rb"^(?P<wban>\d{5})(?P<icao>[A-Z0-9]{4}) [ -~]{3}(?P<stamp>(?P<year>\d{4})(?P<month>\d{2})\d{6})"
    rb"\d{4}(?P<vis>[ -~]{40})"
    rb"(?P<f0>[ -~]{5})(?P<f1>[ -~]{5})(?P<f2>[ -~]{5})(?P<f3>[ -~]{5})(?P<tail>[ -~]*)\r?$"
)
FIELD_RE = re.compile(rb"^(?: *\d{1,3}|   M | {5})$")
DIGITS_RE = re.compile(rb"^ *(\d{1,3})$")
VIS_RE = re.compile(rb"^ *(?:(?:-?\d+\.\d{3}|M) +[A-Za-z](?: +|$)){0,3}$")
TAIL_RE = re.compile(rb"^ *(?:\d\d[LRC ](?:\d\d\+?|FFF)|M)? *$")
BRACKETS = bytes.maketrans(b"[]", b"  ")


def parse_file_regex(path: Path, station: str, yyyymm: str) -> dict:
    year, month = yyyymm[:4].encode(), yyyymm[5:7].encode()
    st = station.encode()
    values = {sid: bytearray() for sid, _ in SERIES}
    counts = collections.Counter()
    data = path.read_bytes()
    lines = data.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    accepted = []
    for raw in lines:
        counts["rows"] += 1
        match = LINE_RE.match(raw)
        if not match or match["icao"] != st:
            counts["bad_rows"] += 1
            continue
        if match["year"] != year or match["month"] != month:
            counts["bad_rows"] += 1
            continue
        fields = [match[f"f{i}"] for i in range(4)]
        if not all(FIELD_RE.match(f) for f in fields):
            counts["bad_rows"] += 1
            continue
        if not VIS_RE.match(match["vis"].translate(BRACKETS)):
            counts["bad_rows"] += 1
            continue
        if not TAIL_RE.match(match["tail"].translate(BRACKETS)):
            counts["bad_rows"] += 1
            continue
        accepted.append((match["stamp"], fields))
    seen = collections.Counter(stamp for stamp, _ in accepted)
    for stamp, fields in accepted:
        if seen[stamp] != 1:
            counts["duplicate_minute_rows"] += 1
            continue
        counts["structural_rows"] += 1
        for sid, index in SERIES:
            digits = DIGITS_RE.match(fields[index])
            if digits is None:
                counts[f"missing_{sid}"] += 1
                continue
            value = int(digits.group(1))
            if value > 255:
                counts[f"out_of_range_{sid}"] += 1
                continue
            values[sid].append(value)
    return {"values": values, "counts": dict(counts)}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def mode_share(data: bytes) -> float:
    if not data:
        return 1.0
    hist = collections.Counter(data)
    return max(hist.values()) / len(data)


def sample_relpath(sid: str, station: str, yyyymm: str) -> str:
    return f"samples/{DATASET_ID}/{sid}/{station}_{yyyymm}.u8.bin"


def bad_row_total(counts: dict) -> int:
    return sum(v for k, v in counts.items() if k.startswith("bad_rows"))


# --------------------------------------------------------------------------
# validate (download.sh)
# --------------------------------------------------------------------------

def cmd_validate(args) -> int:
    rows = read_sources(Path(args.sources))
    download_dir = Path(args.download_dir)
    failures = []
    invalid = []
    for row in rows:
        path = download_dir / row["month"] / row["filename"]
        if not path.is_file():
            failures.append(f"missing {path}")
            continue
        size = path.stat().st_size
        if size != row["size_bytes"]:
            failures.append(f"size mismatch {path}: {size} != {row['size_bytes']}")
            invalid.append(path)
            continue
        data = path.read_bytes()
        if not data.endswith(b"\n"):
            failures.append(f"truncated (no trailing LF) {path}")
            invalid.append(path)
            continue
        lines = data.split(b"\n")[:-1]
        prefix = re.compile(
            rb"^\d{5}" + row["station"].encode() + rb" [ -~]{3}"
            + row["month"].replace("-", "").encode() + rb"\d{10}"
        )
        good = sum(1 for line in lines if prefix.match(line))
        if not lines or good / len(lines) < 0.99 or not prefix.match(lines[0]):
            failures.append(f"semantic check failed {path}: {good}/{len(lines)} lines carry the expected station/month prefix")
            invalid.append(path)
            continue
        print(f"ok {row['station']} {row['month']} bytes={size} lines={len(lines)}")
    if failures:
        for failure in failures:
            print("FAIL", failure, file=sys.stderr)
        if args.delete_invalid:
            for path in invalid:
                print(f"deleting invalid payload {path}", file=sys.stderr)
                path.unlink()
        return 1
    print(f"validated station_months={len(rows)}")
    return 0


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------

def cmd_build(args) -> int:
    rows = read_sources(Path(args.sources))
    data_root = Path(args.data_root)
    download_dir = data_root / "downloads" / DATASET_ID
    samples_root = data_root / "samples" / DATASET_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    for sid, _ in SERIES:
        out_dir = samples_root / sid
        out_dir.mkdir(parents=True, exist_ok=True)
        for stale in out_dir.glob("*.bin"):
            stale.unlink()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    index_rows = []
    totals = collections.Counter()
    per_file = []
    for row in rows:
        station, yyyymm = row["station"], row["month"]
        path = download_dir / yyyymm / row["filename"]
        if not path.is_file() or path.stat().st_size != row["size_bytes"]:
            raise SystemExit(f"missing or wrong-size download {path}; run download.sh")
        parsed = parse_file_fixed(path, station, yyyymm)
        counts = parsed["counts"]
        bad = bad_row_total(counts)
        if counts.get("rows", 0) == 0 or bad / counts["rows"] > MAX_BAD_ROW_SHARE:
            raise SystemExit(f"{path}: malformed row share too high ({bad}/{counts.get('rows', 0)})")
        totals.update(counts)
        file_entry = {"station": station, "month": yyyymm, "counts": counts, "series": {}}
        for sid, _ in SERIES:
            data = bytes(parsed["values"][sid])
            if len(data) < MIN_SAMPLE_VALUES:
                raise SystemExit(f"{station} {yyyymm} {sid}: only {len(data)} values")
            share = mode_share(data)
            if share >= MAX_MODE_SHARE or len(set(data)) < 3:
                raise SystemExit(f"{station} {yyyymm} {sid}: degenerate (mode share {share:.3f})")
            rel = sample_relpath(sid, station, yyyymm)
            (data_root / rel).write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            index_rows.append({
                "dataset_id": DATASET_ID,
                "series_id": sid,
                "sample_path": rel,
                "numeric_kind": "uint",
                "bit_width": 8,
                "endianness": "little",
                "element_size_bytes": 1,
                "sample_size_bytes": len(data),
                "value_count": len(data),
                "station": station,
                "month": yyyymm,
                "source_file": row["filename"],
                "min": min(data),
                "max": max(data),
                "mode_share": round(share, 6),
                "sha256": digest,
            })
            file_entry["series"][sid] = {"values": len(data), "mode_share": round(share, 4)}
            totals[f"values_{sid}"] += len(data)
        per_file.append(file_entry)
        print(f"{station} {yyyymm} rows={counts['rows']} bad={bad} "
              + " ".join(f"{sid}={file_entry['series'][sid]['values']}" for sid, _ in SERIES))

    with index_path.open("w", encoding="utf-8") as handle:
        for entry in index_rows:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
    summary = {"dataset_id": DATASET_ID, "station_months": len(rows), "totals": dict(totals),
               "series": {}}
    for sid, _ in SERIES:
        sel = [r for r in index_rows if r["series_id"] == sid]
        summary["series"][sid] = {
            "sample_count": len(sel),
            "total_size_bytes": sum(r["sample_size_bytes"] for r in sel),
            "max_mode_share": max(r["mode_share"] for r in sel),
            "median_mode_share": sorted(r["mode_share"] for r in sel)[len(sel) // 2],
            "min": min(r["min"] for r in sel),
            "max": max(r["max"] for r in sel),
        }
    summary["per_file"] = per_file
    stats_path.write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "per_file"}, indent=1, sort_keys=True))
    return 0


# --------------------------------------------------------------------------
# verify
# --------------------------------------------------------------------------

def load_manifest_series(manifest: Path) -> dict:
    import tomllib
    data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    return {s["id"]: s for s in data.get("series", [])}


def cmd_verify(args) -> int:
    rows = read_sources(Path(args.sources))
    data_root = Path(args.data_root)
    download_dir = data_root / "downloads" / DATASET_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    failures = []
    index = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line]
    by_path = {r["sample_path"]: r for r in index}
    if len(by_path) != len(index):
        failures.append("duplicate sample_path in index")
    expected_paths = set()
    totals = collections.Counter()
    for row in rows:
        station, yyyymm = row["station"], row["month"]
        path = download_dir / yyyymm / row["filename"]
        parsed = parse_file_regex(path, station, yyyymm)
        counts = parsed["counts"]
        totals.update(counts)
        for sid, _ in SERIES:
            rel = sample_relpath(sid, station, yyyymm)
            expected_paths.add(rel)
            want = bytes(parsed["values"][sid])
            entry = by_path.get(rel)
            sample = data_root / rel
            if entry is None or not sample.is_file():
                failures.append(f"missing sample/index row {rel}")
                continue
            got = sample.read_bytes()
            if got != want:
                failures.append(f"content mismatch {rel}: {len(got)} vs re-derived {len(want)} values")
                continue
            checks = {
                "dataset_id": DATASET_ID, "series_id": sid, "numeric_kind": "uint", "bit_width": 8,
                "endianness": "little", "element_size_bytes": 1, "sample_size_bytes": len(got),
                "value_count": len(got), "min": min(got), "max": max(got),
                "sha256": hashlib.sha256(got).hexdigest(),
            }
            for key, value in checks.items():
                if entry.get(key) != value:
                    failures.append(f"index field {key} mismatch for {rel}: {entry.get(key)!r} != {value!r}")
            share = mode_share(got)
            if len(got) < MIN_SAMPLE_VALUES or len(set(got)) < 3 or share >= MAX_MODE_SHARE:
                failures.append(f"degenerate sample {rel}: values={len(got)} distinct={len(set(got))} mode_share={share:.3f}")
            totals[f"values_{sid}"] += len(got)
    extra = set(by_path) - expected_paths
    if extra:
        failures.append(f"{len(extra)} unexpected index rows, e.g. {sorted(extra)[0]}")
    for sid, _ in SERIES:
        on_disk = {f"samples/{DATASET_ID}/{sid}/{p.name}" for p in (data_root / "samples" / DATASET_ID / sid).glob("*")}
        stray = on_disk - expected_paths
        if stray:
            failures.append(f"{len(stray)} stray files in {sid}, e.g. {sorted(stray)[0]}")

    # cross-check the build's ingest counts with the independent parser
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    built = stats["totals"]
    pairs = [("rows", "rows"), ("structural_rows", "structural_rows"),
             ("duplicate_minute_rows", "duplicate_minute_rows")]
    for sid, _ in SERIES:
        pairs += [(f"missing_{sid}", f"missing_{sid}"), (f"out_of_range_{sid}", f"out_of_range_{sid}"),
                  (f"values_{sid}", f"values_{sid}")]
    for build_key, verify_key in pairs:
        if int(built.get(build_key, 0)) != int(totals.get(verify_key, 0)):
            failures.append(f"count mismatch {build_key}: build={built.get(build_key, 0)} verify={totals.get(verify_key, 0)}")
    built_bad = sum(v for k, v in built.items() if k.startswith("bad_rows"))
    if built_bad != totals.get("bad_rows", 0):
        failures.append(f"bad-row mismatch: build={built_bad} verify={totals.get('bad_rows', 0)}")

    # manifest consistency
    manifest_series = load_manifest_series(Path(args.manifest))
    for sid, _ in SERIES:
        sel = [r for r in index if r["series_id"] == sid]
        count, size = len(sel), sum(r["sample_size_bytes"] for r in sel)
        spec = manifest_series.get(sid)
        if spec is None:
            failures.append(f"manifest lacks series {sid}")
            continue
        if spec.get("sample_count") != count or spec.get("total_size_bytes") != size:
            failures.append(f"manifest {sid}: sample_count/total_size_bytes {spec.get('sample_count')}/{spec.get('total_size_bytes')} != realized {count}/{size}")
        print(f"series {sid}: samples={count} bytes={size}")

    print(json.dumps(dict(totals), sort_keys=True))
    if failures:
        for failure in failures[:50]:
            print("FAIL", failure, file=sys.stderr)
        print(f"verify FAILED ({len(failures)} problems)", file=sys.stderr)
        return 1
    print("verify ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("validate")
    p.add_argument("--sources", required=True)
    p.add_argument("--download-dir", required=True)
    p.add_argument("--delete-invalid", action="store_true")
    p.set_defaults(func=cmd_validate)
    for name, func in (("build", cmd_build), ("verify", cmd_verify)):
        p = sub.add_parser(name)
        p.add_argument("--sources", required=True)
        p.add_argument("--data-root", required=True)
        p.add_argument("--manifest", required=(name == "verify"))
        p.set_defaults(func=func)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
