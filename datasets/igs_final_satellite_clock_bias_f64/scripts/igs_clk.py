#!/usr/bin/env python3
"""Parse IGS final combined RINEX 3.00 clock files into per-satellite-day float64 samples.

Subcommands:
  check-downloads  light semantic validation of the downloaded gzip CLK files
  build            full validation plus sample, index and stats generation
  selftest         parse a synthetic CLK file (continuation lines, gaps, errors)

Pure standard library. The verifier (verify_igs_clk.py) is an independent
fixed-column re-implementation and does not import this module.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import re
import struct
import sys
import tempfile
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

DATASET_ID = "igs_final_satellite_clock_bias_f64"
SERIES_ID = "igs_final_gps_satellite_clock_bias_s_f64"
YEAR = 2024
EPOCHS_PER_DAY = 2880
EPOCH_SECONDS = 30
MIN_EPOCHS = 1000
EXPECTED_FILES = 182
GPS_WEEK0 = 2295  # 2024 day 0 (2023-12-31) starts GPS week 2295
TOKEN_RE = re.compile(r"^-?\d\.\d{12}[eEdD][+-]\d{2}$")
PRN_RE = re.compile(r"^G\d{2}$")
REQUIRED_COMMENTS = (
    "THE COMBINED CLOCKS ARE A WEIGHTED AVERAGE OF:",
    "THE COMBINED CLOCKS ARE ALIGNED TO GPS TIME",
    "All clocks have been re-aligned to the IGS time scale: IGST",
)


class ClkError(ValueError):
    pass


def read_sources(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").rstrip("\n").split("\n")
    header = lines[0].split("\t")
    rows = [dict(zip(header, line.split("\t"))) for line in lines[1:]]
    if len(rows) != EXPECTED_FILES:
        raise ClkError(f"sources.tsv lists {len(rows)} files, expected {EXPECTED_FILES}")
    for number, row in enumerate(rows, 1):
        doy = int(row["doy"])
        if doy != number:
            raise ClkError(f"sources.tsv row {number} has doy {doy}")
        expected = f"IGS0OPSFIN_{YEAR}{doy:03d}0000_01D_30S_CLK.CLK.gz"
        if row["filename"] != expected or int(row["gps_week"]) != GPS_WEEK0 + doy // 7:
            raise ClkError(f"sources.tsv row {number} names {row['filename']} week {row['gps_week']}")
    return rows


def parse_header(lines: list[str], source_row: dict) -> tuple[dict, int]:
    end = None
    for index, line in enumerate(lines):
        if line[60:73] == "END OF HEADER":
            end = index
            break
    if end is None:
        raise ClkError("no END OF HEADER")
    header = lines[: end + 1]
    labels = [line[60:].strip() for line in header]
    first = header[0]
    if labels[0] != "RINEX VERSION / TYPE" or first[:9].strip() != "3.00" or first[20:21] != "C":
        raise ClkError(f"not a RINEX 3.00 clock file: {first!r}")
    by_label: dict[str, list[str]] = defaultdict(list)
    for line, label in zip(header, labels):
        by_label[label].append(line[:60])
    if not by_label.get("ANALYSIS CENTER") or not by_label["ANALYSIS CENTER"][0].startswith("IGS "):
        raise ClkError(f"analysis center is not IGS: {by_label.get('ANALYSIS CENTER')}")
    types = by_label.get("# / TYPES OF DATA", [""])[0].split()
    if not types or int(types[0]) != len(types) - 1 or "AS" not in types[1:]:
        raise ClkError(f"bad # / TYPES OF DATA: {types}")
    for value in by_label.get("TIME SYSTEM ID", []):
        if value.strip() != "GPS":
            raise ClkError(f"time system is not GPS: {value!r}")
    comments = [value.rstrip() for value in by_label.get("COMMENT", [])]
    for needle in REQUIRED_COMMENTS:
        if needle not in comments:
            raise ClkError(f"missing header comment {needle!r}")
    acs_index = comments.index(REQUIRED_COMMENTS[0]) + 1
    contributing = comments[acs_index].split() if acs_index < len(comments) else []
    if not contributing:
        raise ClkError("no contributing analysis centers listed")
    week_match = None
    for value in comments:
        week_match = re.match(r"^GPS week:\s+(\d+)\s+Day:\s+(\d)\s+MJD:\s+(\d+)", value)
        if week_match:
            break
    doy = int(source_row["doy"])
    if not week_match or int(week_match.group(1)) != int(source_row["gps_week"]) or int(week_match.group(2)) != doy % 7:
        raise ClkError(f"GPS week/day comment does not match source row: {week_match and week_match.groups()}")
    mjd = int(week_match.group(3))
    if date(1858, 11, 17) + timedelta(days=mjd) != date(YEAR, 1, 1) + timedelta(days=doy - 1):
        raise ClkError(f"MJD {mjd} does not match {YEAR}-{doy:03d}")
    sats = by_label.get("# OF SOLN SATS")
    prns: list[str] = []
    for value in by_label.get("PRN LIST", []):
        prns.extend(value.split())
    if not sats or int(sats[0].split()[0]) != len(prns) or len(set(prns)) != len(prns):
        raise ClkError(f"# OF SOLN SATS {sats} disagrees with PRN LIST {prns}")
    if not all(PRN_RE.match(prn) for prn in prns):
        raise ClkError(f"PRN LIST is not GPS-only: {prns}")
    pcvs = by_label.get("SYS / PCVS APPLIED", [""])[0]
    return (
        {
            "header_lines": end + 1,
            "types_of_data": types[1:],
            "contributing_acs": contributing,
            "prn_list": prns,
            "mjd": mjd,
            "pcvs_applied": pcvs.split()[1] if len(pcvs.split()) > 1 else "",
            "leap_seconds": by_label.get("LEAP SECONDS", [""])[0].strip(),
        },
        end + 1,
    )


def parse_float_token(token: str) -> float:
    if not TOKEN_RE.match(token):
        raise ClkError(f"value token is not a 12-decimal mantissa: {token!r}")
    normalized = token.replace("D", "e").replace("d", "e").replace("E", "e")
    value = float(normalized)
    if not math.isfinite(value):
        raise ClkError(f"non-finite value {token!r}")
    if "%.12e" % value != normalized:
        raise ClkError(f"float64 does not reproduce token {token!r}")
    return value


def parse_clk(text: str, source_row: dict) -> tuple[dict, dict[str, list[tuple[int, float]]]]:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    meta, start = parse_header(lines, source_row)
    doy = int(source_row["doy"])
    day = date(YEAR, 1, 1) + timedelta(days=doy - 1)
    allowed_types = set(meta["types_of_data"])
    series: dict[str, list[tuple[int, float]]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    last_epoch = -1
    index = start
    while index < len(lines):
        line = lines[index]
        index += 1
        fields = line.split()
        if not fields:
            raise ClkError(f"blank data line {index}")
        rtype = fields[0]
        if rtype not in allowed_types or line[2:3] != " ":
            raise ClkError(f"unexpected record type at line {index}: {line[:20]!r}")
        if len(fields) < 10:
            raise ClkError(f"short data line {index}: {line!r}")
        nvalues = int(fields[8])
        if not 1 <= nvalues <= 6:
            raise ClkError(f"bad value count at line {index}: {nvalues}")
        first_line_values = min(nvalues, 2)
        if len(fields) != 9 + first_line_values:
            raise ClkError(f"field count mismatch at line {index}: {line!r}")
        values = fields[9:]
        if nvalues > 2:
            if index >= len(lines):
                raise ClkError("missing continuation line at end of file")
            continuation = lines[index].split()
            index += 1
            if len(continuation) != nvalues - 2:
                raise ClkError(f"continuation line {index} has {len(continuation)} values, expected {nvalues - 2}")
            values += continuation
        counts[rtype] += 1
        year, month, mday, hour, minute = (int(item) for item in fields[2:7])
        seconds = fields[7]
        if date(year, month, mday) != day:
            raise ClkError(f"epoch date {year}-{month}-{mday} outside file day {day} at line {index}")
        if not re.match(r"^\d{1,2}\.000000$", seconds) or int(seconds.split(".")[0]) % EPOCH_SECONDS:
            raise ClkError(f"epoch seconds off the 30 s lattice at line {index}: {seconds}")
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ClkError(f"bad epoch time at line {index}")
        epoch = (hour * 3600 + minute * 60 + int(seconds.split(".")[0])) // EPOCH_SECONDS
        if epoch < last_epoch:
            raise ClkError(f"epochs not in nondecreasing file order at line {index}")
        last_epoch = epoch
        if rtype != "AS":
            continue
        prn = fields[1]
        if not PRN_RE.match(prn) or line[3:7] != prn + " ":
            raise ClkError(f"bad satellite name at line {index}: {line[:12]!r}")
        bias = parse_float_token(values[0])
        for extra in values[1:]:
            parse_float_token(extra)
        records = series[prn]
        if records and records[-1][0] >= epoch:
            raise ClkError(f"duplicate or reversed epoch for {prn} at line {index}")
        records.append((epoch, bias))
    if set(series) != set(meta["prn_list"]):
        raise ClkError(f"AS PRNs {sorted(series)} != PRN LIST {sorted(meta['prn_list'])}")
    meta["record_counts"] = dict(sorted(counts.items()))
    return meta, dict(sorted(series.items()))


def resolve_data_root(repo_root: Path, data_dir: str) -> Path:
    path = Path(data_dir)
    return path if path.is_absolute() else repo_root / path


def source_path(data_root: Path, row: dict) -> Path:
    return data_root / "downloads" / DATASET_ID / "clk" / row["filename"]


def load_source(data_root: Path, row: dict) -> tuple[str, str]:
    path = source_path(data_root, row)
    raw = path.read_bytes()
    if len(raw) != int(row["size_bytes"]):
        raise ClkError(f"{row['filename']}: size {len(raw)} != pinned {row['size_bytes']}")
    digest = hashlib.sha256(raw).hexdigest()
    if row.get("sha256") and digest != row["sha256"]:
        raise ClkError(f"{row['filename']}: sha256 {digest} != pinned {row['sha256']}")
    return gzip.decompress(raw).decode("ascii"), digest


def command_check_downloads(args: argparse.Namespace) -> int:
    data_root = resolve_data_root(Path(args.repo_root), args.data_dir)
    rows = read_sources(Path(args.sources))
    total_as = 0
    for row in rows:
        text, _ = load_source(data_root, row)
        meta, series = parse_clk(text, row)
        values = sum(len(records) for records in series.values())
        total_as += values
        print(
            f"ok doy={row['doy']} week={row['gps_week']} header_lines={meta['header_lines']} "
            f"prns={len(series)} as_records={values} acs={','.join(meta['contributing_acs'])}"
        )
    print(f"check_downloads=ok files={len(rows)} as_records={total_as}")
    return 0


def summarize_gaps(epochs: list[int]) -> dict:
    present = set(epochs)
    missing = [epoch for epoch in range(EPOCHS_PER_DAY) if epoch not in present]
    max_gap = 0
    for left, right in zip(epochs, epochs[1:]):
        max_gap = max(max_gap, right - left - 1)
    return {"missing": missing, "max_internal_gap_epochs": max_gap}


def command_build(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root)
    data_root = resolve_data_root(repo_root, args.data_dir)
    rows = read_sources(Path(args.sources))
    sample_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_dir = data_root / "index" / DATASET_ID
    filtered_dir = data_root / "filtered" / DATASET_ID
    for directory in (sample_dir, index_dir, filtered_dir):
        directory.mkdir(parents=True, exist_ok=True)
    for stale in sample_dir.glob("*.bin"):
        stale.unlink()
    index_rows: list[dict] = []
    file_stats: list[dict] = []
    excluded: list[dict] = []
    gapped: list[dict] = []
    total_values = 0
    for row in rows:
        text, digest = load_source(data_root, row)
        meta, series = parse_clk(text, row)
        doy = int(row["doy"])
        day = date(YEAR, 1, 1) + timedelta(days=doy - 1)
        emitted = 0
        for prn, records in series.items():
            epochs = [epoch for epoch, _ in records]
            values = [value for _, value in records]
            gaps = summarize_gaps(epochs)
            if len(values) < MIN_EPOCHS:
                excluded.append({"doy": doy, "prn": prn, "epoch_count": len(values), "reason": f"fewer than {MIN_EPOCHS} AS epochs"})
                continue
            if len(set(values)) < 2:
                raise ClkError(f"{row['filename']} {prn}: constant clock series")
            payload = struct.pack(f"<{len(values)}d", *values)
            name = f"{YEAR}_{doy:03d}_{prn}.bin"
            (sample_dir / name).write_bytes(payload)
            stored = struct.unpack(f"<{len(values)}d", payload)
            entry = {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": f"samples/{DATASET_ID}/{SERIES_ID}/{name}",
                "numeric_kind": "float",
                "bit_width": 64,
                "endianness": "little",
                "element_size_bytes": 8,
                "sample_size_bytes": len(payload),
                "value_count": len(values),
                "source_file": row["filename"],
                "source_doy": doy,
                "date": day.isoformat(),
                "gps_week": int(row["gps_week"]),
                "prn": prn,
                "first_epoch_index": epochs[0],
                "last_epoch_index": epochs[-1],
                "missing_epoch_count": len(gaps["missing"]),
                "max_internal_gap_epochs": gaps["max_internal_gap_epochs"],
                "contributing_acs": " ".join(meta["contributing_acs"]),
                "min": min(stored),
                "max": max(stored),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            index_rows.append(entry)
            if gaps["missing"]:
                gapped.append({"doy": doy, "prn": prn, "epoch_count": len(values), "missing_epoch_indices": gaps["missing"]})
            emitted += 1
            total_values += len(values)
        file_stats.append(
            {
                "doy": doy,
                "filename": row["filename"],
                "sha256": digest,
                "header_lines": meta["header_lines"],
                "contributing_acs": meta["contributing_acs"],
                "prn_count": len(meta["prn_list"]),
                "record_counts": meta["record_counts"],
                "pcvs_applied": meta["pcvs_applied"],
                "samples_emitted": emitted,
            }
        )
        print(
            f"built doy={doy:03d} prns={len(series)} samples={emitted} "
            f"as={meta['record_counts'].get('AS', 0)} ar_excluded={meta['record_counts'].get('AR', 0)} "
            f"acs={','.join(meta['contributing_acs'])}"
        )
    hashes = [entry["sha256"] for entry in index_rows]
    if len(set(hashes)) != len(hashes):
        raise ClkError("duplicate sample payloads")
    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as handle:
        for entry in index_rows:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
    ac_sets: dict[str, int] = defaultdict(int)
    for stats in file_stats:
        ac_sets[" ".join(stats["contributing_acs"])] += 1
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "files": len(file_stats),
        "samples": len(index_rows),
        "values": total_values,
        "bytes": total_values * 8,
        "min_epochs_per_sample": MIN_EPOCHS,
        "complete_samples": sum(1 for entry in index_rows if entry["value_count"] == EPOCHS_PER_DAY),
        "gapped_samples": len(gapped),
        "excluded_short_satellite_days": excluded,
        "gapped_satellite_days": gapped,
        "contributing_ac_sets": dict(sorted(ac_sets.items())),
        "per_file": file_stats,
    }
    (filtered_dir / "ingest_stats.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    counts = sorted(entry["value_count"] for entry in index_rows)
    median = counts[len(counts) // 2] if len(counts) % 2 else (counts[len(counts) // 2 - 1] + counts[len(counts) // 2]) / 2
    print(
        f"build_summary samples={len(index_rows)} values={total_values} bytes={total_values * 8} "
        f"median_values={median} complete={summary['complete_samples']} gapped={len(gapped)} "
        f"excluded_short={len(excluded)} ac_sets={dict(ac_sets)}"
    )
    return 0


SYNTHETIC_HEADER = """     3.00           C                                       RINEX VERSION / TYPE
CCLOCK              IGSACC @ GA MIT                         PGM / RUN BY / DATE
GPS week: 2295   Day: 1   MJD: 60310                        COMMENT
THE COMBINED CLOCKS ARE A WEIGHTED AVERAGE OF:              COMMENT
  esa gfz grg                                               COMMENT
THE COMBINED CLOCKS ARE ALIGNED TO GPS TIME                 COMMENT
All clocks have been re-aligned to the IGS time scale: IGST COMMENT
    18                                                      LEAP SECONDS
     2    AR    AS                                          # / TYPES OF DATA
IGS  IGSACC @ GA MIT                                        ANALYSIS CENTER
     2                                                      # OF SOLN SATS
G01 G02                                                     PRN LIST
G                   igs20_2290.atx                          SYS / PCVS APPLIED
                                                            END OF HEADER
"""


def synthetic_line(rtype: str, name: str, epoch: int, values: list[float]) -> str:
    seconds = epoch * EPOCH_SECONDS
    hour, rem = divmod(seconds, 3600)
    minute, sec = divmod(rem, 60)
    head = f"{rtype} {name:<4} {YEAR:4d} {1:02d} {1:02d} {hour:02d} {minute:02d} {sec:9.6f} {len(values):2d}   "
    tokens = [f"{value:19.12e}" for value in values]
    line = head + " ".join(tokens[:2])
    if len(tokens) > 2:
        line += "\n" + " ".join(tokens[2:])
    return line


def command_selftest(_: argparse.Namespace) -> int:
    row = {"doy": "1", "gps_week": "2295", "filename": "synthetic"}
    lines = [SYNTHETIC_HEADER.rstrip("\n")]
    expected: dict[str, list[tuple[int, float]]] = {"G01": [], "G02": []}
    for epoch in range(6):
        lines.append(synthetic_line("AR", "ALGO", epoch, [1e-9 * epoch, 3e-11]))
        value = 1.649896549438e-04 + epoch * 7.25e-11
        value = float("%.12e" % value)
        lines.append(synthetic_line("AS", "G01", epoch, [value, 1.5e-11]))
        expected["G01"].append((epoch, value))
        if epoch != 3:  # G02 gap at epoch 3; G02 uses a four-value record with a continuation line
            value2 = float("%.12e" % (-6.016993513839e-04 - epoch * 1.1e-10))
            lines.append(synthetic_line("AS", "G02", epoch, [value2, 4.2e-12, 1.0e-13, -2.0e-15]))
            expected["G02"].append((epoch, value2))
    text = "\n".join(lines) + "\n"
    meta, series = parse_clk(text, row)
    assert series == expected, (series, expected)
    assert meta["contributing_acs"] == ["esa", "gfz", "grg"], meta
    assert meta["record_counts"] == {"AR": 6, "AS": 11}, meta
    assert summarize_gaps([epoch for epoch, _ in series["G02"]])["max_internal_gap_epochs"] == 1
    failures = {
        "off-lattice seconds": text.replace("01 00 00  0.000000", "01 00 00  1.000000", 1),
        "missing PRN LIST satellite": text.replace("AS G02 ", "AS G03 "),
        "duplicate epoch": text.replace("AS G01  2024 01 01 00 00 30", "AS G01  2024 01 01 00 00  0", 1),
        "non-GPS satellite": text.replace("AS G02 ", "AS R02 "),
        "NaN token": text.replace("1.649896549438e-04", "nan               ", 1),
        "11-decimal token": text.replace("1.649896549438e-04", "1.64989654944e-04 ", 1),
        "PRN list mismatch": text.replace("G01 G02     ", "G01 G03     ", 1),
        "wrong day": text.replace("2024 01 01 00 00 30", "2024 01 02 00 00 30", 1),
        "truncated continuation": text.rsplit("\n", 2)[0] + "\n",
        "unknown record type": text.replace("AR ALGO", "CR ALGO", 1),
    }
    for label, broken in failures.items():
        assert broken != text, f"selftest mutation {label} did not change the input"
        try:
            parse_clk(broken, row)
        except (ClkError, ValueError):
            continue
        raise AssertionError(f"selftest: {label} was not rejected")
    with tempfile.TemporaryDirectory() as tmp:
        packed = struct.pack("<2d", *[value for _, value in expected["G01"][:2]])
        Path(tmp, "x.bin").write_bytes(packed)
        assert struct.unpack("<2d", Path(tmp, "x.bin").read_bytes()) == tuple(value for _, value in expected["G01"][:2])
    print("selftest=ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("check-downloads", "build"):
        command = sub.add_parser(name)
        command.add_argument("--repo-root", required=True)
        command.add_argument("--data-dir", required=True)
        command.add_argument("--sources", required=True)
    sub.add_parser("selftest")
    args = parser.parse_args()
    handlers = {"check-downloads": command_check_downloads, "build": command_build, "selftest": command_selftest}
    try:
        return handlers[args.command](args)
    except ClkError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
