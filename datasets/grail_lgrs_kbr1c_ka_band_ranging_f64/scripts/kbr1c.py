#!/usr/bin/env python3
"""Parser and validators for GRAIL LGRS KBR1C (Level-1B dual-one-way Ka-band
ranging) ASCII products, GRAIL-L-LGRS-3-CDR-V1.0, DPSIS Table 43.

Pure standard library. Commands:
  self-test                         parse a synthetic product and check results
  check-md5   --sources --md5       every pinned file is listed with the pinned MD5
  check-label --sources --date --label
  check-asc   --sources --date --asc
"""
import argparse
import hashlib
import math
import os
import re
import sys
import tempfile

NCOLS = 20  # DPSIS Table 43: 20 whitespace-separated columns
CADENCE_S = 2  # extended-mission KBR1C cadence
FLAG_COL = 15  # column 16 (0-based 15): 8-digit data quality flag string
CALSLEW_DIGIT = 1  # digit 1 = 'From raw data for Ka boresight calibration slew'
# Generous physical plausibility bounds (fatal outside): biased range in m,
# range rate in m/s, range acceleration in m/s^2.
BOUNDS = ((1.0e7, "biased_range"), (100.0, "range_rate"), (10.0, "range_accl"))
REBIAS_THRESHOLD_M = 1.0  # |d range - mean rate * dt| above this marks a new phase arc


class KbrError(Exception):
    pass


def read_sources(path):
    rows = []
    with open(path, encoding="ascii") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        for line in fh:
            if not line.strip():
                continue
            rows.append(dict(zip(header, line.rstrip("\n").split("\t"))))
    return rows


def source_row(sources, date):
    hits = [r for r in sources if r["date"] == date]
    if len(hits) != 1:
        raise KbrError(f"date {date} not pinned exactly once in sources.tsv")
    return hits[0]


def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_kbr1c(data):
    """Parse a KBR1C product (bytes). Returns a dict with the header fields,
    tdb (list of int), the three primary columns (lists of float) and
    per-record flag strings. Raises KbrError on any structural problem."""
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise KbrError(f"non-ASCII content: {exc}")
    if "\r\n" not in text[:4096]:
        raise KbrError("expected CRLF line endings")
    lines = text.split("\r\n")
    if lines and lines[-1] == "":
        lines.pop()
    else:
        raise KbrError("file does not end with CRLF")
    header = {}
    end = None
    for i, ln in enumerate(lines[:200]):
        if ln.startswith("END OF HEADER"):
            end = i
            break
        key, sep, val = ln.partition(":")
        if not sep:
            raise KbrError(f"header line {i + 1} has no ':' separator")
        header.setdefault(key.strip(), val.strip())
    if end is None:
        raise KbrError("END OF HEADER not found in the first 200 lines")
    need = ["FILE FORMAT 0=BINARY 1=ASCII", "NUMBER OF HEADER RECORDS", "SATELLITE NAME",
            "TIME EPOCH", "TIME FIRST OBS(SEC PAST EPOCH)", "TIME LAST OBS(SEC PAST EPOCH)",
            "NUMBER OF DATA RECORDS", "FILENAME", "PROCESS LEVEL 1C"]
    for k in need:
        if k not in header:
            raise KbrError(f"header field missing: {k}")
    if header["FILE FORMAT 0=BINARY 1=ASCII"] != "1":
        raise KbrError("FILE FORMAT is not ASCII")
    if int(header["NUMBER OF HEADER RECORDS"]) != end:
        raise KbrError(f"NUMBER OF HEADER RECORDS {header['NUMBER OF HEADER RECORDS']} != {end}")
    if header["SATELLITE NAME"] != "GRAIL A+B":
        raise KbrError(f"unexpected SATELLITE NAME {header['SATELLITE NAME']!r}")
    if header["TIME EPOCH"] != "2000-01-01 12:00:00":
        raise KbrError(f"unexpected TIME EPOCH {header['TIME EPOCH']!r}")
    if header["PROCESS LEVEL 1C"] != "1C":
        raise KbrError("PROCESS LEVEL is not 1C")
    tdb, rng, rate, accl, flags = [], [], [], [], []
    for n, ln in enumerate(lines[end + 1:], start=end + 2):
        parts = ln.split()
        if len(parts) != NCOLS:
            raise KbrError(f"line {n}: {len(parts)} columns, expected {NCOLS}")
        if not re.fullmatch(r"[0-9]+", parts[0]):
            raise KbrError(f"line {n}: TDB {parts[0]!r} is not a non-negative integer")
        try:
            v = (float(parts[1]), float(parts[2]), float(parts[3]))
        except ValueError:
            raise KbrError(f"line {n}: unparseable range/rate/accel")
        for x, (bound, name) in zip(v, BOUNDS):
            if not math.isfinite(x) or abs(x) >= bound:
                raise KbrError(f"line {n}: {name} {x!r} non-finite or beyond {bound}")
        if not re.fullmatch(r"[01]{8}", parts[FLAG_COL]):
            raise KbrError(f"line {n}: quality flag {parts[FLAG_COL]!r} is not 8 binary digits")
        tdb.append(int(parts[0]))
        rng.append(v[0])
        rate.append(v[1])
        accl.append(v[2])
        flags.append(parts[FLAG_COL])
    if not tdb:
        raise KbrError("no data records")
    if len(tdb) != int(header["NUMBER OF DATA RECORDS"]):
        raise KbrError(f"{len(tdb)} records != header NUMBER OF DATA RECORDS {header['NUMBER OF DATA RECORDS']}")
    first = float(header["TIME FIRST OBS(SEC PAST EPOCH)"].split()[0])
    last = float(header["TIME LAST OBS(SEC PAST EPOCH)"].split()[0])
    if first != tdb[0] or last != tdb[-1]:
        raise KbrError(f"header first/last {first}/{last} != records {tdb[0]}/{tdb[-1]}")
    for i in range(1, len(tdb)):
        dt = tdb[i] - tdb[i - 1]
        if dt <= 0 or dt % CADENCE_S:
            raise KbrError(f"record {i}: TDB step {dt} s is not a positive multiple of {CADENCE_S}")
    return {"header": header, "header_records": end, "tdb": tdb, "range": rng,
            "rate": rate, "accl": accl, "flags": flags}


def summarize(rec):
    """Gap, flag and re-bias statistics recorded in the index."""
    tdb, rng, rate = rec["tdb"], rec["range"], rec["rate"]
    gaps = [(tdb[i - 1], tdb[i] - tdb[i - 1]) for i in range(1, len(tdb)) if tdb[i] - tdb[i - 1] != CADENCE_S]
    rebias = 0
    for i in range(1, len(tdb)):
        dt = tdb[i] - tdb[i - 1]
        if abs(rng[i] - rng[i - 1] - 0.5 * (rate[i] + rate[i - 1]) * dt) > REBIAS_THRESHOLD_M:
            rebias += 1
    calslew = sum(1 for f in rec["flags"] if f[7 - CALSLEW_DIGIT] == "1")
    other = sum(1 for f in rec["flags"] if any(c == "1" for j, c in enumerate(f) if j != 7 - CALSLEW_DIGIT))
    day0 = tdb[0] - (tdb[0] - 43200) % 86400  # TDB seconds of 00:00:00 of the first record's day
    return {
        "record_count": len(tdb),
        "first_tdb": tdb[0],
        "last_tdb": tdb[-1],
        "gap_count": len(gaps),
        "missing_epochs": (tdb[-1] - tdb[0]) // CADENCE_S + 1 - len(tdb),
        "max_gap_s": max((g[1] for g in gaps), default=CADENCE_S),
        "gaps": [[g[0], g[1]] for g in gaps[:50]],
        "rebias_steps": rebias,
        "calslew_flag_records": calslew,
        "other_flag_records": other,
        "partial_day": not (tdb[0] == day0 and tdb[-1] == day0 + 86400 - CADENCE_S),
    }


def check_asc(sources, date, path):
    row = source_row(sources, date)
    size = os.path.getsize(path)
    if size != int(row["http_bytes"]):
        raise KbrError(f"{path}: {size} bytes, pinned {row['http_bytes']}")
    with open(path, "rb") as fh:
        data = fh.read()
    if hashlib.md5(data).hexdigest() != row["asc_md5"]:
        raise KbrError(f"{path}: MD5 differs from the published grail_0101_230316.md5 value")
    rec = parse_kbr1c(data)
    h = rec["header"]
    want_name = "KBR1C_" + date.replace("_", "-") + "_X_04.asc"
    if h["FILENAME"] != want_name:
        raise KbrError(f"header FILENAME {h['FILENAME']!r} != {want_name!r}")
    if (rec["header_records"] != int(row["header_records"]) or len(rec["tdb"]) != int(row["data_records"])
            or rec["tdb"][0] != int(row["first_tdb"]) or rec["tdb"][-1] != int(row["last_tdb"])
            or int(h["FILESIZE (BYTES)"]) != int(row["header_filesize"])):
        raise KbrError(f"{path}: header/record counts or times differ from sources.tsv")
    return rec


def check_label(sources, date, path):
    row = source_row(sources, date)
    if md5_file(path) != row["label_md5"]:
        raise KbrError(f"{path}: MD5 differs from the published value")
    text = open(path, encoding="ascii").read()
    want = "KBR1C_" + date.upper() + "_X_04.ASC"
    if f'PRODUCT_ID            = "{want}"' not in text:
        raise KbrError(f"{path}: PRODUCT_ID is not {want}")
    if 'DATA_SET_ID           = "GRAIL-L-LGRS-3-CDR-V1.0"' not in text or "Table 43" not in text:
        raise KbrError(f"{path}: unexpected DATA_SET_ID or format reference")


def check_md5_manifest(sources, path):
    listed = {}
    with open(path, encoding="ascii") as fh:
        for line in fh:
            parts = line.strip().split()
            if len(parts) == 2:
                listed[parts[1].replace("\\", "/").lower()] = parts[0].lower()
    for r in sources:
        base = f"grail_0101/level_1b/{r['date']}/{r['file'][:-4]}"
        if listed.get(base + ".asc") != r["asc_md5"] or listed.get(base + ".lbl") != r["label_md5"]:
            raise KbrError(f"{r['file']}: MD5 not listed as pinned in the volume manifest")
    n = sum(1 for k in listed if "/kbr1c_" in k and k.endswith(".asc"))
    if n != 197:
        raise KbrError(f"volume manifest lists {n} KBR1C .asc products, expected 197")


def self_test():
    hdr_lines = [
        "PRODUCER AGENCY               : NASA",
        "FILE TYPE ipKBR1CF            : 2",
        "FILE FORMAT 0=BINARY 1=ASCII  : 1",
        "NUMBER OF HEADER RECORDS      : 11",
        "SATELLITE NAME                : GRAIL A+B",
        "TIME EPOCH                    : 2000-01-01 12:00:00",
        "TIME FIRST OBS(SEC PAST EPOCH): 399643200.000000 (2012-08-31 00:00:00.00)",
        "TIME LAST OBS(SEC PAST EPOCH) : 399643208.000000 (2012-08-31 00:00:08.00)",
        "NUMBER OF DATA RECORDS        : 4",
        "FILENAME                      : KBR1C_2012-08-31_X_04.asc",
        "PROCESS LEVEL 1C              : 1C",
        "END OF HEADER",
    ]
    tail = "0 -0.001 1.5e-07 6.7e-10 1.99 -9.1e-10 3.7e-11  0 745  0 745  {flag} -0.0005 -0.0005 4.1e-08 8.5e-12"
    recs = [
        (399643200, "-29030.1360341154", "0.07050382816793005", "0.0008263486055854205", "00000000"),
        (399643202, "-29029.99337733407", "0.07215189711155687", "-1.218484839413313e-03", "00000010"),
        (399643206, "5000.25", "-0.4874026368468322", "0.001", "00000000"),  # 4 s gap + re-bias
        (399643208, "5000.249", "-0.5", "0.0", "00000000"),
    ]
    body = [f"{t} {a} {b} {c} " + tail.format(flag=f) for t, a, b, c, f in recs]
    data = ("\r\n".join(hdr_lines + body) + "\r\n").encode("ascii")
    rec = parse_kbr1c(data)
    assert rec["tdb"] == [r[0] for r in recs]
    assert rec["range"][0] == -29030.1360341154 and rec["rate"][1] == 0.07215189711155687
    assert rec["accl"][1] == -0.001218484839413313
    s = summarize(rec)
    assert s["gap_count"] == 1 and s["missing_epochs"] == 1 and s["max_gap_s"] == 4, s
    assert s["calslew_flag_records"] == 1 and s["other_flag_records"] == 0, s
    assert s["rebias_steps"] == 1 and s["partial_day"] is True, s
    bad_cases = [
        data.replace(b"\r\n", b"\n"),
        data.replace(b"NUMBER OF DATA RECORDS        : 4", b"NUMBER OF DATA RECORDS        : 5"),
        data.replace(b"399643208 5000.249", b"399643207 5000.249"),
        data.replace(b"5000.249 -0.5 0.0", b"5000.249 nan 0.0"),
        data.replace(b"00000010", b"0000002"),
        data.replace(b"5000.249 -0.5 0.0 ", b"5000.249 -0.5 "),
    ]
    for i, bad in enumerate(bad_cases):
        try:
            parse_kbr1c(bad)
        except KbrError:
            continue
        raise AssertionError(f"bad case {i} was accepted")
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "x.asc")
        with open(p, "wb") as fh:
            fh.write(data)
        assert md5_file(p) == hashlib.md5(data).hexdigest()
    print("kbr1c self-test ok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["self-test", "check-md5", "check-label", "check-asc"])
    ap.add_argument("--sources")
    ap.add_argument("--md5")
    ap.add_argument("--date")
    ap.add_argument("--label")
    ap.add_argument("--asc")
    a = ap.parse_args()
    try:
        if a.command == "self-test":
            self_test()
        elif a.command == "check-md5":
            check_md5_manifest(read_sources(a.sources), a.md5)
            print("volume md5 manifest ok")
        elif a.command == "check-label":
            check_label(read_sources(a.sources), a.date, a.label)
        elif a.command == "check-asc":
            rec = check_asc(read_sources(a.sources), a.date, a.asc)
            s = summarize(rec)
            print(f"check-asc ok {a.date} records={s['record_count']} gaps={s['gap_count']} "
                  f"missing={s['missing_epochs']} rebias={s['rebias_steps']} calslew={s['calslew_flag_records']}")
    except KbrError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
