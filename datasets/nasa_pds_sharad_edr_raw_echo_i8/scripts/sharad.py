#!/usr/bin/env python3
"""MRO SHARAD EDR (MRO-M-SHARAD-3-EDR-V1.0, volume MROSH_0001) SS19 echo recipe helper.

Subcommands
  select    pick products from a local INDEX.TAB (discover.sh)
  pin       pin selected products from their local labels + volume MD5 list (discover.sh)
  plan      expand sources.tsv into the download plan (download.sh)
  validate  semantic validation of downloaded labels and *_S.DAT tables (download.sh)
  build     emit one int8 sample per product + samples.jsonl (build.sh)

Pure standard library. No network I/O: discover.sh and download.sh fetch with curl.
"""
import argparse
import collections
import datetime
import hashlib
import json
import os
import re
import sys

DATASET_ID = "nasa_pds_sharad_edr_raw_echo_i8"
SERIES_ID = "sharad_edr_ss19_echo_i8"
BASE_URL = "https://pds-geosciences.wustl.edu/mro/mro-m-sharad-3-edr-v1/mrosh_0001/"
VOLUME_ID = "MROSH_0001"
FMT_PATH = "label/science8bit.fmt"
FMT_MD5 = "3bb1ee6b3bb4ed09a6e20f1ab37db517"

RECORD_BYTES = 3786
HEADER_BYTES = 186
ECHO_SAMPLES = 3600
SS19_OPERATIVE_MODE = 51  # 33..53 = subsurface sounding modes SS01..SS21
ZERO_ROW = bytes(RECORD_BYTES)  # gap-fill row: all 3786 bytes zero
MAX_FILL_FRACTION = 0.01

# Selection rule (documented in README/manifest).
MIN_DURATION_S = 45.0
MAX_DURATION_S = 70.0
LAT_BANDS = [(-90, -60), (-60, -30), (-30, 0), (0, 30), (30, 60), (60, 90)]
PER_BAND = 4

SOURCE_COLUMNS = [
    "ordinal", "product_id", "lbl_path", "sdat_path", "orbit", "start_time", "stop_time",
    "start_lat", "stop_lat", "start_lon", "stop_lon", "lat_band", "file_records",
    "sdat_bytes", "sdat_md5", "lbl_md5", "manual_gain",
]


def die(msg):
    print("ERROR: " + msg, file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------- index / select

def parse_index(path):
    rows = []
    with open(path, encoding="ascii") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if not line:
                continue
            parts = [p.strip().strip('"').strip() for p in line.split(",")]
            if len(parts) != 20:
                die("unexpected INDEX.TAB row: %r" % line[:80])
            rows.append({
                "volume": parts[0], "file_spec": parts[2], "product_id": parts[3],
                "orbit": int(parts[9]), "start_time": parts[10], "stop_time": parts[11],
                "start_lat": float(parts[14]), "stop_lat": float(parts[15]),
                "start_lon": float(parts[16]), "stop_lon": float(parts[17]),
                "mode": parts[18], "dq": parts[19],
            })
    return rows


def pds_time(s):
    return datetime.datetime.strptime(s, "%Y-%jT%H:%M:%S.%f")


def duration_s(r):
    return (pds_time(r["stop_time"]) - pds_time(r["start_time"])).total_seconds()


def band_of(r):
    mid = (r["start_lat"] + r["stop_lat"]) / 2.0
    for i, (lo, hi) in enumerate(LAT_BANDS):
        if lo <= mid < hi or (hi == 90 and mid == 90):
            return i
    die("latitude out of range for %s" % r["product_id"])


def cmd_select(a):
    rows = parse_index(a.index)
    cand = [r for r in rows
            if r["volume"] == VOLUME_ID and r["mode"] == "SS19" and r["dq"] == "0"
            and r["product_id"].split("_")[3:5] == ["SS19", "700"]
            and MIN_DURATION_S <= duration_s(r) <= MAX_DURATION_S]
    by_band = collections.defaultdict(list)
    for r in cand:
        by_band[band_of(r)].append(r)
    used_orbits = set()
    chosen = []
    for b in range(len(LAT_BANDS)):
        lst = sorted(by_band[b], key=lambda r: (r["orbit"], r["product_id"]))
        n = len(lst)
        if n < PER_BAND:
            die("band %d has only %d candidates" % (b, n))
        for k in range(PER_BAND):
            i = int((k + 0.5) * n / PER_BAND)
            while lst[i]["orbit"] in used_orbits:
                i += 1
                if i >= n:
                    die("ran out of distinct orbits in band %d" % b)
            used_orbits.add(lst[i]["orbit"])
            r = dict(lst[i])
            r["lat_band"] = b
            chosen.append(r)
    print("select: %d candidates (SS19, DQ 0, %.0f-%.0f s), chosen %d" %
          (len(cand), MIN_DURATION_S, MAX_DURATION_S, len(chosen)), file=sys.stderr)
    with open(a.out, "w") as fh:
        fh.write("product_id\tlbl_path\torbit\tstart_time\tstop_time\tstart_lat\tstop_lat\tstart_lon\tstop_lon\tlat_band\n")
        for r in chosen:
            fh.write("\t".join(str(x) for x in [
                r["product_id"], r["file_spec"].lower(), r["orbit"], r["start_time"], r["stop_time"],
                r["start_lat"], r["stop_lat"], r["start_lon"], r["stop_lon"], r["lat_band"]]) + "\n")


# ---------------------------------------------------------------- labels

def parse_label(text):
    """Return list of (key, value) for top-level-ish PDS3 statements, values joined across lines."""
    items = []
    cur_key, cur_val = None, []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("/*"):
            continue
        m = re.match(r"^\s*([A-Z0-9_:^]+)\s*=\s*(.*)$", line)
        if m:
            if cur_key is not None:
                items.append((cur_key, " ".join(cur_val).strip()))
            cur_key, cur_val = m.group(1), [m.group(2).strip()]
        elif line.strip() == "END":
            break
        elif cur_key is not None:
            cur_val.append(line.strip())
    if cur_key is not None:
        items.append((cur_key, " ".join(cur_val).strip()))
    return items


def science_object(items):
    """Extract the fields of the label relevant to the science telemetry file."""
    out = {}
    in_first_file = False
    file_count = 0
    for k, v in items:
        if k == "OBJECT" and v == "FILE":
            file_count += 1
            in_first_file = file_count == 1
            continue
        if k in ("PRODUCT_ID", "DATA_SET_ID", "TARGET_NAME", "ORBIT_NUMBER", "START_TIME", "STOP_TIME"):
            out.setdefault(k, v.strip('"'))
        if not in_first_file:
            continue
        if k in ("RECORD_TYPE", "RECORD_BYTES", "FILE_RECORDS", "^SCIENCE_TELEMETRY_TABLE",
                 "INSTRUMENT_MODE_ID", "INSTRUMENT_MODE_DESC", "MRO:PULSE_REPETITION_INTERVAL",
                 "MRO:MANUAL_GAIN_CONTROL", "MRO:COMPRESSION_SELECTION_FLAG",
                 "MRO:PHASE_COMPENSATION_TYPE", "MRO:CLOSED_LOOP_TRACKING_FLAG",
                 "DATA_QUALITY_ID", "INTERCHANGE_FORMAT", "ROW_BYTES", "ROWS", "^STRUCTURE"):
            out.setdefault(k, v.strip('"').strip())
    return out


def check_label(text, product_id):
    s = science_object(parse_label(text))
    desc = re.sub(r"\s+", " ", s.get("INSTRUMENT_MODE_DESC", ""))
    expect = {
        "PRODUCT_ID": product_id,
        "DATA_SET_ID": "MRO-M-SHARAD-3-EDR-V1.0",
        "TARGET_NAME": "MARS",
        "RECORD_TYPE": "FIXED_LENGTH",
        "RECORD_BYTES": str(RECORD_BYTES),
        "^SCIENCE_TELEMETRY_TABLE": product_id + "_S.DAT",
        "INSTRUMENT_MODE_ID": "SS19",
        "MRO:PULSE_REPETITION_INTERVAL": "1428 <MICROSECONDS>",
        "MRO:COMPRESSION_SELECTION_FLAG": "STATIC",
        "MRO:PHASE_COMPENSATION_TYPE": "NO COMPENSATION",
        "MRO:CLOSED_LOOP_TRACKING_FLAG": "DISABLED",
        "DATA_QUALITY_ID": "0",
        "INTERCHANGE_FORMAT": "BINARY",
        "ROW_BYTES": str(RECORD_BYTES),
        "^STRUCTURE": "SCIENCE8BIT.FMT",
    }
    for k, v in expect.items():
        if s.get(k) != v:
            die("%s: label %s=%r, expected %r" % (product_id, k, s.get(k), v))
    if "summing 04 sequential echoes" not in desc or "to 08-bit precision" not in desc:
        die("%s: INSTRUMENT_MODE_DESC lacks presum-4 / 8-bit text: %r" % (product_id, desc))
    if s.get("ROWS") != s.get("FILE_RECORDS"):
        die("%s: ROWS != FILE_RECORDS" % product_id)
    s["file_records"] = int(s["FILE_RECORDS"])
    s["manual_gain"] = int(s["MRO:MANUAL_GAIN_CONTROL"])
    return s


def load_md5_list(path):
    out = {}
    with open(path, encoding="ascii", errors="replace") as fh:
        for line in fh:
            parts = line.strip().split(None, 1)
            if len(parts) != 2:
                continue
            md5, name = parts
            name = name.replace("\\", "/").lower()
            out[name] = md5.lower()
    return out


def cmd_pin(a):
    md5s = load_md5_list(a.md5_list)
    if md5s.get("mrosh_0001/" + FMT_PATH) != FMT_MD5:
        die("science8bit.fmt MD5 in volume list differs from pinned value")
    out_rows = []
    with open(a.selected, encoding="ascii") as fh:
        hdr = fh.readline().rstrip("\n").split("\t")
        for n, line in enumerate(fh, 1):
            r = dict(zip(hdr, line.rstrip("\n").split("\t")))
            lbl_local = os.path.join(a.label_dir, os.path.basename(r["lbl_path"]))
            with open(lbl_local, "rb") as lf:
                raw = lf.read()
            lbl_md5 = hashlib.md5(raw).hexdigest()
            key = "mrosh_0001/" + r["lbl_path"]
            if md5s.get(key) != lbl_md5:
                die("label MD5 mismatch vs volume list: %s" % key)
            s = check_label(raw.decode("ascii"), r["product_id"])
            sdat_path = r["lbl_path"][:-4] + "_s.dat"
            sdat_md5 = md5s.get("mrosh_0001/" + sdat_path)
            if not sdat_md5:
                die("no MD5 for %s" % sdat_path)
            out_rows.append([n, r["product_id"], r["lbl_path"], sdat_path, r["orbit"], r["start_time"],
                             r["stop_time"], r["start_lat"], r["stop_lat"], r["start_lon"], r["stop_lon"],
                             r["lat_band"], s["file_records"], s["file_records"] * RECORD_BYTES,
                             sdat_md5, lbl_md5, s["manual_gain"]])
    with open(a.out, "w") as fh:
        fh.write("\t".join(SOURCE_COLUMNS) + "\n")
        for row in out_rows:
            fh.write("\t".join(str(x) for x in row) + "\n")
    tot = sum(r[13] for r in out_rows)
    prim = sum(r[12] for r in out_rows) * ECHO_SAMPLES
    print("pin: %d products, sdat bytes %d, primary bytes %d" % (len(out_rows), tot, prim), file=sys.stderr)


# ---------------------------------------------------------------- sources / plan

def load_sources(path):
    with open(path, encoding="ascii") as fh:
        hdr = fh.readline().rstrip("\n").split("\t")
        if hdr != SOURCE_COLUMNS:
            die("sources.tsv header mismatch")
        rows = []
        for line in fh:
            if not line.strip():
                continue
            r = dict(zip(hdr, line.rstrip("\n").split("\t")))
            for k in ("ordinal", "orbit", "lat_band", "file_records", "sdat_bytes", "manual_gain"):
                r[k] = int(r[k])
            if r["sdat_bytes"] != r["file_records"] * RECORD_BYTES:
                die("sources.tsv size != rows*3786 for %s" % r["product_id"])
            rows.append(r)
    return rows


def local_name(r, kind):
    return "%02d_%s%s" % (r["ordinal"], r["product_id"].lower(), ".lbl" if kind == "lbl" else "_s.dat")


def cmd_plan(a):
    rows = load_sources(a.sources)
    with open(a.out, "w") as fh:
        fh.write("kind\tlocal_filename\turl\tbytes\tmd5\n")
        fh.write("fmt\tscience8bit.fmt\t%s%s\t-\t%s\n" % (BASE_URL, FMT_PATH, FMT_MD5))
        for r in rows:
            fh.write("lbl\t%s\t%s%s\t-\t%s\n" % (local_name(r, "lbl"), BASE_URL, r["lbl_path"], r["lbl_md5"]))
        for r in rows:
            fh.write("sdat\t%s\t%s%s\t%d\t%s\n" % (local_name(r, "sdat"), BASE_URL, r["sdat_path"],
                                                     r["sdat_bytes"], r["sdat_md5"]))
    print("plan: %d products, %d sdat bytes" % (len(rows), sum(r["sdat_bytes"] for r in rows)), file=sys.stderr)


def cmd_probe_rows(a):
    """Check header flags of range-fetched rows (first/middle/last) of every pinned product."""
    rows = load_sources(a.sources)
    bad = 0
    for r in rows:
        for which in ("first", "mid", "last"):
            path = os.path.join(a.probe_dir, "%02d_%s.bin" % (r["ordinal"], which))
            row = open(path, "rb").read()
            if len(row) != RECORD_BYTES:
                die("probe row %s has %d bytes" % (path, len(row)))
            h = row[:HEADER_BYTES]
            status = (h[44] << 8) | h[45]
            ok = (h[26] == SS19_OPERATIVE_MODE and h[27] == r["manual_gain"] and (status >> 15) & 1
                  and not (status >> 3) & 1 and not (status >> 2) & 1 and (status >> 1) & 1 and not status & 1)
            echo = row[HEADER_BYTES:]
            if not ok or echo.count(echo[0]) == ECHO_SAMPLES:
                bad += 1
                print("probe FAIL %s %s mode=%d gain=%d status=%04x" % (r["product_id"], which, h[26], h[27], status))
    if bad:
        die("%d probe rows failed" % bad)
    print("probe-rows: %d products x 3 rows OK" % len(rows), file=sys.stderr)


# ---------------------------------------------------------------- table scan

def check_fmt(path):
    raw = open(path, "rb").read()
    if hashlib.md5(raw).hexdigest() != FMT_MD5:
        die("science8bit.fmt MD5 mismatch")
    t = re.sub(r"\s+", " ", raw.decode("ascii"))
    for frag in ("NAME = ECHO_SAMPLES", "BIT_DATA_TYPE = MSB_INTEGER", "START_BYTE = 187",
                 "BYTES = 3600", "ITEMS = 3600", "ITEM_BITS = 8"):
        if frag not in t:
            die("science8bit.fmt lacks %r" % frag)


def scan_table(path, r, emit=None):
    """Validate every row header and gather echo statistics; optionally write echo bytes."""
    size = os.path.getsize(path)
    if size != r["sdat_bytes"]:
        die("%s: size %d != pinned %d" % (path, size, r["sdat_bytes"]))
    hist = [0] * 256
    const_rows = 0
    fill_rows = 0
    flag_counts = collections.Counter()
    prev_key = None
    sha = hashlib.sha256()
    with open(path, "rb") as fh:
        for i in range(r["file_records"]):
            row = fh.read(RECORD_BYTES)
            if len(row) != RECORD_BYTES:
                die("%s: short row %d" % (path, i))
            h = row[:HEADER_BYTES]
            echo = row[HEADER_BYTES:]
            if row == ZERO_ROW:
                # Archive gap-fill block: header and echo entirely zero. Preserved in
                # place (row alignment kept), counted, and capped below.
                fill_rows += 1
                const_rows += 1
                hist[0] += ECHO_SAMPLES
                sha.update(echo)
                if emit is not None:
                    emit.write(echo)
                continue
            op_mode = h[26]
            gain = h[27]
            status = (h[44] << 8) | h[45]
            sci = (status >> 15) & 1
            dma = (status >> 3) & 1
            tco = (status >> 2) & 1
            fifo_ok = (status >> 1) & 1
            test = status & 1
            if op_mode != SS19_OPERATIVE_MODE:
                die("%s row %d: OPERATIVE_MODE %d != 51 (SS19)" % (path, i, op_mode))
            if gain != r["manual_gain"]:
                die("%s row %d: MANUAL_GAIN_CONTROL %d != label %d" % (path, i, gain, r["manual_gain"]))
            if not sci:
                flag_counts["tracking_data_type"] += 1
            if dma or tco or not fifo_ok or test:
                flag_counts["fpga_error_or_test"] += 1
            key = (int.from_bytes(h[0:4], "big"), int.from_bytes(h[4:6], "big"))
            if prev_key is not None and key < prev_key:
                flag_counts["scet_nonmonotonic"] += 1
            prev_key = key
            if echo.count(echo[0]) == ECHO_SAMPLES:
                const_rows += 1
            for b, c in collections.Counter(echo).items():
                hist[b] += c
            sha.update(echo)
            if emit is not None:
                emit.write(echo)
    if flag_counts["tracking_data_type"] or flag_counts["fpga_error_or_test"]:
        die("%s: rows with tracking/error/test flags: %s" % (path, dict(flag_counts)))
    n = r["file_records"] * ECHO_SAMPLES
    vals = [(b - 256 if b > 127 else b) for b in range(256) if hist[b]]
    s = sum((b - 256 if b > 127 else b) * hist[b] for b in range(256))
    stats = {
        "min": min(vals), "max": max(vals), "mean": round(s / n, 6),
        "distinct_values": len(vals), "zero_fraction": round(hist[0] / n, 6),
        "max_value_fraction": round(max(hist) / n, 6),
        "constant_rows": const_rows, "zero_fill_rows": fill_rows, "scet_nonmonotonic_rows": flag_counts["scet_nonmonotonic"],
        "sha256": sha.hexdigest(),
    }
    if (len(vals) < 32 or const_rows > 0.05 * r["file_records"] or fill_rows > MAX_FILL_FRACTION * r["file_records"]
            or max(hist) > 0.5 * n):
        die("%s: degenerate echo payload %s" % (path, stats))
    return stats


def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_validate(a):
    rows = load_sources(a.sources)
    check_fmt(os.path.join(a.download_dir, "science8bit.fmt"))
    for r in rows:
        lp = os.path.join(a.download_dir, local_name(r, "lbl"))
        raw = open(lp, "rb").read()
        if hashlib.md5(raw).hexdigest() != r["lbl_md5"]:
            die("label MD5 mismatch: %s" % lp)
        s = check_label(raw.decode("ascii"), r["product_id"])
        if s["file_records"] != r["file_records"] or s["manual_gain"] != r["manual_gain"]:
            die("label disagrees with sources.tsv: %s" % r["product_id"])
        dp = os.path.join(a.download_dir, local_name(r, "sdat"))
        if a.check_md5 and md5_file(dp) != r["sdat_md5"]:
            die("S.DAT MD5 mismatch: %s" % dp)
        st = scan_table(dp, r)
        print("valid %02d %s rows=%d distinct=%d zero=%.4f const_rows=%d zero_fill_rows=%d" % (
            r["ordinal"], r["product_id"], r["file_records"], st["distinct_values"],
            st["zero_fraction"], st["constant_rows"], st["zero_fill_rows"]))
    print("validate: %d products OK" % len(rows))


# ---------------------------------------------------------------- build

def cmd_build(a):
    rows = load_sources(a.sources)
    dl = a.download_dir
    out_dir = os.path.join(a.data_root, "samples", DATASET_ID, SERIES_ID)
    idx_dir = os.path.join(a.data_root, "index", DATASET_ID)
    filt_dir = os.path.join(a.data_root, "filtered", DATASET_ID)
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(idx_dir, exist_ok=True)
    os.makedirs(filt_dir, exist_ok=True)
    for f in os.listdir(out_dir):
        if f.endswith(".i8") or f.endswith(".tmp"):
            os.remove(os.path.join(out_dir, f))
    check_fmt(os.path.join(dl, "science8bit.fmt"))
    index_rows = []
    for r in rows:
        raw = open(os.path.join(dl, local_name(r, "lbl")), "rb").read()
        if hashlib.md5(raw).hexdigest() != r["lbl_md5"]:
            die("label MD5 mismatch for %s" % r["product_id"])
        s = check_label(raw.decode("ascii"), r["product_id"])
        if s["file_records"] != r["file_records"]:
            die("label rows mismatch for %s" % r["product_id"])
        name = "%02d_%s.i8" % (r["ordinal"], r["product_id"].lower())
        out = os.path.join(out_dir, name)
        with open(out + ".tmp", "wb") as fh:
            st = scan_table(os.path.join(dl, local_name(r, "sdat")), r, emit=fh)
        os.replace(out + ".tmp", out)
        nbytes = os.path.getsize(out)
        if nbytes != r["file_records"] * ECHO_SAMPLES:
            die("output size mismatch for %s" % name)
        index_rows.append({
            "dataset_id": DATASET_ID, "series_id": SERIES_ID,
            "sample_path": os.path.relpath(out, a.data_root),
            "numeric_kind": "int", "bit_width": 8, "endianness": "little",
            "element_size_bytes": 1, "sample_size_bytes": nbytes,
            "value_count": nbytes, "shape": [r["file_records"], ECHO_SAMPLES],
            "axes": ["echo_row", "fast_time_sample"],
            "product_id": r["product_id"], "orbit": r["orbit"],
            "start_time": r["start_time"], "stop_time": r["stop_time"],
            "start_lat": float(r["start_lat"]), "stop_lat": float(r["stop_lat"]),
            "start_lon": float(r["start_lon"]), "stop_lon": float(r["stop_lon"]),
            "lat_band": r["lat_band"], "manual_gain_control": r["manual_gain"],
            "source_sdat_md5": r["sdat_md5"], **st,
        })
        print("built %s rows=%d bytes=%d min=%d max=%d distinct=%d zero=%.4f const_rows=%d" % (
            name, r["file_records"], nbytes, st["min"], st["max"], st["distinct_values"],
            st["zero_fraction"], st["constant_rows"]))
    with open(os.path.join(idx_dir, "samples.jsonl.tmp"), "w") as fh:
        for ir in index_rows:
            fh.write(json.dumps(ir, sort_keys=True) + "\n")
    os.replace(os.path.join(idx_dir, "samples.jsonl.tmp"), os.path.join(idx_dir, "samples.jsonl"))
    summary = {"sample_count": len(index_rows),
               "total_size_bytes": sum(x["sample_size_bytes"] for x in index_rows),
               "constant_rows": sum(x["constant_rows"] for x in index_rows),
               "zero_fill_rows": sum(x["zero_fill_rows"] for x in index_rows)}
    with open(os.path.join(filt_dir, "build_summary.json"), "w") as fh:
        json.dump(summary, fh, indent=1, sort_keys=True)
    print("build: %s" % json.dumps(summary))


def main():
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("select"); s.add_argument("--index", required=True); s.add_argument("--out", required=True)
    s = sp.add_parser("pin"); s.add_argument("--selected", required=True); s.add_argument("--label-dir", required=True)
    s.add_argument("--md5-list", required=True); s.add_argument("--out", required=True)
    s = sp.add_parser("probe-rows"); s.add_argument("--sources", required=True); s.add_argument("--probe-dir", required=True)
    s = sp.add_parser("plan"); s.add_argument("--sources", required=True); s.add_argument("--out", required=True)
    s = sp.add_parser("validate"); s.add_argument("--sources", required=True); s.add_argument("--download-dir", required=True)
    s.add_argument("--check-md5", action="store_true")
    s = sp.add_parser("build"); s.add_argument("--sources", required=True); s.add_argument("--download-dir", required=True)
    s.add_argument("--data-root", required=True)
    a = p.parse_args()
    {"select": cmd_select, "pin": cmd_pin, "plan": cmd_plan, "probe-rows": cmd_probe_rows, "validate": cmd_validate, "build": cmd_build}[a.cmd](a)


if __name__ == "__main__":
    main()
