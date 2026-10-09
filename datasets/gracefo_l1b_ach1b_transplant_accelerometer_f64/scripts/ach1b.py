#!/usr/bin/env python3
"""Validate, build and verify gracefo_l1b_ach1b_transplant_accelerometer_f64.

Subcommands
  selftest            synthetic tarball + ACH1B text round trip through both parsers
  validate-downloads  semantic check of every pinned ACX2 tarball (used by download.sh)
  build               emit one raw <f8 [records, 3] lin_accl sample per pinned day
  verify              independently re-derive every sample and check index/manifest/policy

Source member: ``ACH1B_<YYYY-MM-DD>_D_04.txt`` inside the daily JPL RL04
``gracefo_1B_<YYYY-MM-DD>_RL04.ascii.ACX2.tgz``. Every other member (AC01B,
AC11B thruster-model products, ACU1B, .rpt reports) is hashed against the
tarball's ``checksum`` member and then discarded. Nothing else is extracted.

Missing-value policy (shared by build and verify): ACH1B has no fill value.
Every data row must have exactly one token per declared header variable,
GRACEFO_id must be 'D', and gps_time must be an integer second on the 1 s
lattice of the file's UTC day (the day starts at gps_time
(date - 2000-01-01) * 86400 - 43200, because the epoch is 2000-01-01 12:00
GPS time). gps_time must be strictly increasing, the row count must equal the
header num_records, and lin_accl_x/y/z must parse as finite floats with
|value| < 1e-4 m/s^2 (a decode sanity bound about 10x the largest
non-gravitational acceleration at GRACE-FO altitude). Absent lattice seconds
(a partial day) are not filled. They are counted and listed per sample in the
index, and a day with fewer than MIN_RECORDS rows is fatal. Any other deviation
is fatal. Nothing is dropped, imputed or reordered. qualflg is not used to drop
rows; its nonzero-row count is recorded per sample.
"""
from __future__ import annotations

import argparse
import array
import datetime as dt
import hashlib
import io
import json
import math
import re
import struct
import sys
import tarfile
import tomllib
from pathlib import Path

sys.dont_write_bytecode = True

DATASET_ID = "gracefo_l1b_ach1b_transplant_accelerometer_f64"
SERIES_ID = "gracefo_ach1b_lin_accl_srf_f64"
EXPECTED_FILES = 97
DAY_SECONDS = 86_400
MIN_RECORDS = 43_200
COLUMNS = ("lin_accl_x", "lin_accl_y", "lin_accl_z")
TITLE = "GRACE-FO Level-1B Hybrid Transplant Accelerometer Data"
SOFTWARE_VERSION = "V04.10.2020-11-09-82-gd120e-dirty"
L1A_INPUT = "ACH1A"
LICENSE_URL = "https://science.nasa.gov/earth-science/earth-science-data/data-information-policy"
DOI = "10.5067/GFJPL-L1B04"
ABS_BOUND = 1e-4
END_MARK = "# End of YAML header"
GPS_EPOCH_DATE = dt.date(2000, 1, 1)
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
MD5_LINE_RE = re.compile(r"^([0-9a-f]{32})  (\S+)$")
ORDINAL = {1: "1st", 2: "2nd", 3: "3rd"}


class RecipeError(RuntimeError):
    pass


def require(cond: bool, message: str) -> None:
    if not cond:
        raise RecipeError(message)


def data_root(repo_root: Path, data_dir: str) -> Path:
    path = Path(data_dir)
    return path if path.is_absolute() else repo_root / path


def day_start_gps(date: dt.date) -> int:
    return (date - GPS_EPOCH_DATE).days * DAY_SECONDS - 43_200


def member_name(date: dt.date) -> str:
    return f"ACH1B_{date.isoformat()}_D_04.txt"


def read_sources(path: Path) -> list[dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    want = ["candidate_index", "date", "filename", "size_bytes", "last_modified", "etag", "sha256", "url"]
    require(header == want, f"unexpected sources.tsv header {header}")
    rows = [dict(zip(header, line.split("\t"))) for line in lines[1:] if line.strip()]
    require(len(rows) == EXPECTED_FILES, f"sources.tsv has {len(rows)} rows, expected {EXPECTED_FILES}")
    dates = [r["date"] for r in rows]
    require(dates == sorted(set(dates)), "sources.tsv dates must be unique and sorted")
    for r in rows:
        require(r["filename"] == f"gracefo_1B_{r['date']}_RL04.ascii.ACX2.tgz", f"bad filename {r['filename']}")
        require(r["sha256"] == "pending" or SHA_RE.match(r["sha256"]) is not None, f"bad sha256 for {r['date']}")
    return rows


# ---------------------------------------------------------------------------
# Tarball reading (build path: streaming 'r|gz', one pass, md5 of every member)
# ---------------------------------------------------------------------------

def parse_checksum(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        m = MD5_LINE_RE.match(line)
        require(m is not None, f"malformed checksum line {line!r}")
        md5, name = m.groups()
        require(name not in out, f"duplicate checksum entry {name}")
        out[name] = md5
    return out


def stream_tarball(path: Path, wanted: str) -> tuple[bytes, dict]:
    """Return the wanted member's bytes and checksum facts; validate every member's md5."""
    digests: dict[str, str] = {}
    kept: bytes | None = None
    checksum_text: str | None = None
    with tarfile.open(path, mode="r|gz") as tf:
        for info in tf:
            require(info.isreg(), f"{path.name}: non-regular member {info.name}")
            require("/" not in info.name and info.name not in ("", ".", ".."), f"{path.name}: odd member {info.name}")
            fh = tf.extractfile(info)
            require(fh is not None, f"{path.name}: unreadable member {info.name}")
            body = fh.read()
            require(len(body) == info.size, f"{path.name}: short member {info.name}")
            if info.name == "checksum":
                require(checksum_text is None, f"{path.name}: duplicate checksum member")
                checksum_text = body.decode("ascii")
                continue
            require(info.name not in digests, f"{path.name}: duplicate member {info.name}")
            digests[info.name] = hashlib.md5(body).hexdigest()
            if info.name == wanted:
                kept = body
    require(kept is not None, f"{path.name}: member {wanted} missing")
    require(checksum_text is not None, f"{path.name}: checksum member missing")
    listed = parse_checksum(checksum_text)
    require(set(listed) == set(digests),
            f"{path.name}: checksum lists {sorted(set(listed) ^ set(digests))} inconsistently with members")
    for name, md5 in digests.items():
        require(listed[name] == md5, f"{path.name}: md5 mismatch for {name}")
    return kept, {"members": sorted(digests), "member_md5": digests[wanted]}


# ---------------------------------------------------------------------------
# ACH1B text parsing (build path)
# ---------------------------------------------------------------------------

def parse_header(header: str, date: dt.date) -> dict:
    lines = header.splitlines()
    require(lines and lines[0].strip() == "header:", "ACH1B header does not start with 'header:'")

    def scalar(key: str) -> str:
        vals = [ln.split(":", 1)[1].strip() for ln in lines if ln.strip().startswith(key + ":")]
        require(len(vals) == 1, f"header key {key} appears {len(vals)} times")
        return vals[0]

    facts = {
        "num_records": int(scalar("num_records")),
        "title": scalar("title"),
        "platform": scalar("platform"),
        "product_version": scalar("product_version"),
        "license": scalar("license"),
        "id": scalar("id"),
        "software_version": scalar("software_version"),
        "time_coverage_start": scalar("time_coverage_start"),
        "start_time_epoch_secs": int(scalar("start_time_epoch_secs")),
    }
    inputs = re.findall(r'INPUT FILE NAME\s*: ACC1A<-([A-Z0-9]{5})_(\d{4}-\d{2}-\d{2})_D_04\.dat', header)
    require(len(inputs) == 1, f"expected one ACC1A input line, got {inputs}")
    facts["l1a_input"] = inputs[0][0]
    require(inputs[0][1] == date.isoformat(), f"ACC1A input date {inputs[0][1]} != {date}")
    # Variables, in order, with their 'Nth column' comments.
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == "variables:")
    except StopIteration as exc:
        raise RecipeError("no variables: section") from exc
    names: list[str] = []
    comments: list[str] = []
    for ln in lines[start + 1:]:
        m = re.match(r"^    - (\w+):\s*$", ln)
        if m:
            names.append(m.group(1))
            continue
        m = re.match(r"^        comment: (\d+)(st|nd|rd|th) column\s*$", ln)
        if m:
            require(len(comments) == len(names) - 1, f"column comment out of place: {ln!r}")
            comments.append(int(m.group(1)))
    require(comments == list(range(1, len(names) + 1)), f"column comments {comments} do not match variable order")
    facts["variables"] = names
    for col in ("gps_time", "GRACEFO_id", *COLUMNS):
        require(col in names, f"variable {col} not declared")
    return facts


def check_header(facts: dict, date: dt.date) -> None:
    require(facts["title"] == TITLE, f"title {facts['title']!r}")
    require(facts["platform"] == "GRACE D", f"platform {facts['platform']!r}")
    require(facts["product_version"] == "04", f"product_version {facts['product_version']!r}")
    require(facts["license"] == LICENSE_URL, f"license {facts['license']!r}")
    require(facts["id"] == DOI, f"id {facts['id']!r}")
    require(facts["software_version"] == SOFTWARE_VERSION, f"software_version {facts['software_version']!r}")
    require(facts["l1a_input"] == L1A_INPUT, f"ACC1A input lineage {facts['l1a_input']!r}")
    require(facts["time_coverage_start"].startswith(date.isoformat()), "time_coverage_start date mismatch")


def split_member(text: str) -> tuple[str, list[str]]:
    idx = text.find("\n" + END_MARK + "\n")
    require(idx >= 0, "end-of-YAML marker not found")
    header = text[:idx]
    body = text[idx + len(END_MARK) + 2:]
    rows = body.split("\n")
    if rows and rows[-1] == "":
        rows.pop()
    return header, rows


def parse_member(raw: bytes, date: dt.date, min_records: int = MIN_RECORDS, check: bool = True) -> dict:
    text = raw.decode("ascii")
    header, rows = split_member(text)
    facts = parse_header(header, date)
    if check:
        check_header(facts, date)
    names = facts["variables"]
    ncol = len(names)
    i_t = names.index("gps_time")
    i_id = names.index("GRACEFO_id")
    i_xyz = [names.index(c) for c in COLUMNS]
    i_ang = [i for i, n in enumerate(names) if n.startswith("ang_accl_")]
    i_q = names.index("qualflg") if "qualflg" in names else None
    t0 = day_start_gps(date)
    values = array.array("d")
    seconds: list[int] = []
    prev = -1
    qual_nonzero = 0
    ang_nonzero = 0
    for line_no, row in enumerate(rows, 1):
        tok = row.split()
        require(len(tok) == ncol, f"row {line_no}: {len(tok)} tokens, expected {ncol}")
        require(tok[i_t].isdigit(), f"row {line_no}: gps_time {tok[i_t]!r} is not an integer second")
        sec = int(tok[i_t]) - t0
        require(0 <= sec < DAY_SECONDS, f"row {line_no}: gps_time outside the UTC day")
        require(sec > prev, f"row {line_no}: gps_time not strictly increasing")
        prev = sec
        require(tok[i_id] == "D", f"row {line_no}: GRACEFO_id {tok[i_id]!r}")
        for i in i_xyz:
            v = float(tok[i])
            require(math.isfinite(v) and abs(v) < ABS_BOUND, f"row {line_no}: lin_accl value {tok[i]!r} out of bounds")
            values.append(v)
        seconds.append(sec)
        if any(float(tok[i]) != 0.0 for i in i_ang):
            ang_nonzero += 1
        if i_q is not None and set(tok[i_q]) != {"0"}:
            qual_nonzero += 1
    n = len(seconds)
    require(n == facts["num_records"], f"row count {n} != header num_records {facts['num_records']}")
    require(n >= min_records, f"only {n} records (< {min_records})")
    present = set(seconds)
    missing = [s for s in range(DAY_SECONDS) if s not in present] if n < DAY_SECONDS else []
    return {
        "facts": facts,
        "values": values,
        "records": n,
        "missing_seconds": missing,
        "qualflg_nonzero_rows": qual_nonzero,
        "ang_accl_nonzero_rows": ang_nonzero,
        "first_second": seconds[0],
        "last_second": seconds[-1],
    }


def to_le_bytes(values: array.array) -> bytes:
    out = array.array("d", values)
    if sys.byteorder != "little":
        out.byteswap()
    return out.tobytes()


# ---------------------------------------------------------------------------
# Independent verify path: random-access tar, regex row parse, struct packing
# ---------------------------------------------------------------------------

ROW_RE = re.compile(r"^(\d+) ([CD]) (\S+) (\S+) (\S+)(?:\s+\S+)*\s*$")


def verify_extract(path: Path, wanted: str) -> bytes:
    with tarfile.open(path, mode="r:gz") as tf:
        names = tf.getnames()
        require(names.count(wanted) == 1 and names.count("checksum") == 1, f"{path.name}: member set {names}")
        body = tf.extractfile(wanted).read()
        listed = {}
        for line in tf.extractfile("checksum").read().decode("ascii").split("\n"):
            if line:
                md5, name = line.split("  ")
                listed[name] = md5
    require(listed.get(wanted) == hashlib.md5(body).hexdigest(), f"{path.name}: checksum mismatch for {wanted}")
    return body


def verify_rederive(raw: bytes, date: dt.date) -> tuple[bytes, int]:
    text = raw.decode("ascii")
    pos = text.index(END_MARK + "\n") + len(END_MARK) + 1
    header = text[:pos]
    # Column positions from the header's variable list, located independently.
    order = re.findall(r"^    - (\w+):$", header[header.index("  variables:"):], flags=re.M)
    require(order[:5] == ["gps_time", "GRACEFO_id", *COLUMNS],
            f"verify path assumes gps_time, id, lin_accl_x/y/z lead the row; header order {order[:5]}")
    t0 = day_start_gps(date)
    out = io.BytesIO()
    last = None
    n = 0
    for line in text[pos:].splitlines():
        m = ROW_RE.match(line)
        require(m is not None, f"verify: unparsable row {line[:80]!r}")
        t = int(m.group(1)) - t0
        require(0 <= t < DAY_SECONDS and (last is None or t > last), "verify: gps_time lattice violation")
        require(m.group(2) == "D", "verify: GRACEFO_id")
        last = t
        xyz = [float(m.group(k)) for k in (3, 4, 5)]
        require(all(math.isfinite(v) and abs(v) < ABS_BOUND for v in xyz), "verify: value bound")
        out.write(struct.pack("<3d", *xyz))
        n += 1
    require(len(order) == len(line.split()), "verify: token count of last row != declared variables")
    return out.getvalue(), n


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def tarball_path(root: Path, row: dict) -> Path:
    return root / "downloads" / DATASET_ID / "tgz" / row["filename"]


def cmd_validate(args) -> int:
    root = data_root(args.repo_root, args.data_dir)
    rows = read_sources(args.sources)
    total = 0
    for row in rows:
        path = tarball_path(root, row)
        require(path.is_file(), f"missing download {path}")
        require(path.stat().st_size == int(row["size_bytes"]), f"{path.name}: size mismatch")
        date = dt.date.fromisoformat(row["date"])
        try:
            raw, info = stream_tarball(path, member_name(date))
            header, _ = split_member(raw[:20000].decode("ascii", errors="replace") + "\n")
            facts = parse_header(header, date)
            check_header(facts, date)
        except (RecipeError, tarfile.TarError, OSError, EOFError, ValueError) as exc:
            if args.quarantine:
                path.rename(path.with_name(path.name + ".invalid"))
                print(f"QUARANTINED {path.name}: {exc}", file=sys.stderr)
            raise RecipeError(f"{path.name}: {exc}") from exc
        total += path.stat().st_size
        print(f"valid date={row['date']} members={len(info['members'])} ach1b_md5={info['member_md5']} "
              f"records={facts['num_records']}")
    print(f"validate_ok files={len(rows)} bytes={total}")
    return 0


def cmd_build(args) -> int:
    selftest()
    root = data_root(args.repo_root, args.data_dir)
    rows = read_sources(args.sources)
    out_dir = root / "samples" / DATASET_ID / SERIES_ID
    idx_dir = root / "index" / DATASET_ID
    filt_dir = root / "filtered" / DATASET_ID
    for d in (out_dir, idx_dir, filt_dir):
        d.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.bin"):
        stale.unlink()
    index_rows = []
    hashes = set()
    total_bytes = 0
    total_values = 0
    for row in rows:
        date = dt.date.fromisoformat(row["date"])
        path = tarball_path(root, row)
        require(path.stat().st_size == int(row["size_bytes"]), f"{path.name}: size mismatch")
        if row["sha256"] != "pending":
            require(hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"], f"{path.name}: sha256 mismatch")
        raw, info = stream_tarball(path, member_name(date))
        parsed = parse_member(raw, date)
        payload = to_le_bytes(parsed["values"])
        n = parsed["records"]
        require(len(payload) == n * 3 * 8, "payload size mismatch")
        stored = struct.unpack(f"<{n * 3}d", payload)
        comps = [stored[k::3] for k in range(3)]
        for k, comp in enumerate(comps):
            require(min(comp) != max(comp), f"{date}: {COLUMNS[k]} constant")
        distinct = [len(set(c)) for c in comps]
        digest = hashlib.sha256(payload).hexdigest()
        require(digest not in hashes, f"{date}: duplicate sample payload")
        hashes.add(digest)
        rel = f"samples/{DATASET_ID}/{SERIES_ID}/ACH1B_{date.isoformat()}_D.f64le.bin"
        (root / rel).write_bytes(payload)
        missing = parsed["missing_seconds"]
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": rel,
            "numeric_kind": "float",
            "bit_width": 64,
            "endianness": "little",
            "element_size_bytes": 8,
            "sample_size_bytes": len(payload),
            "value_count": n * 3,
            "shape": [n, 3],
            "axes": ["gps_second_of_utc_day", "srf_axis"],
            "components": list(COLUMNS),
            "units": "m/s2",
            "date": date.isoformat(),
            "source_file": row["filename"],
            "source_member": member_name(date),
            "source_member_md5": info["member_md5"],
            "tar_members": info["members"],
            "records": n,
            "first_gps_time": day_start_gps(date) + parsed["first_second"],
            "missing_second_count": len(missing),
            "missing_seconds": missing,
            "qualflg_nonzero_rows": parsed["qualflg_nonzero_rows"],
            "ang_accl_nonzero_rows": parsed["ang_accl_nonzero_rows"],
            "software_version": parsed["facts"]["software_version"],
            "l1a_input": parsed["facts"]["l1a_input"],
            "component_min": [min(c) for c in comps],
            "component_max": [max(c) for c in comps],
            "min": min(stored),
            "max": max(stored),
            "component_distinct_counts": distinct,
            "sha256": digest,
        })
        total_bytes += len(payload)
        total_values += n * 3
        print(f"sample date={date} records={n} missing={len(missing)} qual_rows={parsed['qualflg_nonzero_rows']} "
              f"ang_rows={parsed['ang_accl_nonzero_rows']} distinct={distinct} bytes={len(payload)}")
    with open(idx_dir / "samples.jsonl", "w", encoding="utf-8") as fh:
        for r in index_rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    stats = {
        "samples": len(index_rows),
        "total_values": total_values,
        "total_bytes": total_bytes,
        "partial_days": [r["date"] for r in index_rows if r["missing_second_count"]],
        "days_with_nonzero_ang_accl": [r["date"] for r in index_rows if r["ang_accl_nonzero_rows"]],
        "global_min": min(r["min"] for r in index_rows),
        "global_max": max(r["max"] for r in index_rows),
    }
    (filt_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n")
    print(f"build_ok samples={len(index_rows)} values={total_values} bytes={total_bytes}")
    return 0


def cmd_verify(args) -> int:
    selftest()
    root = data_root(args.repo_root, args.data_dir)
    rows = read_sources(args.sources)
    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    require(len(series) == 1, "manifest series missing")
    series = series[0]
    idx_rows = [json.loads(ln) for ln in (root / "index" / DATASET_ID / "samples.jsonl").read_text().splitlines()]
    require(len(idx_rows) == len(rows), f"index has {len(idx_rows)} rows, expected {len(rows)}")
    out_dir = root / "samples" / DATASET_ID / SERIES_ID
    on_disk = sorted(p.name for p in out_dir.iterdir())
    require(on_disk == sorted(Path(r["sample_path"]).name for r in idx_rows), "sample files != index rows")
    seen = set()
    total_bytes = 0
    values = []
    for row, ir in zip(rows, idx_rows):
        date = dt.date.fromisoformat(row["date"])
        require(ir["date"] == row["date"] and ir["source_file"] == row["filename"], f"{date}: index order")
        for key, val in (("dataset_id", DATASET_ID), ("series_id", SERIES_ID), ("numeric_kind", "float"),
                         ("bit_width", 64), ("endianness", "little"), ("element_size_bytes", 8)):
            require(ir[key] == val, f"{date}: index {key}={ir[key]!r}")
        raw = verify_extract(tarball_path(root, row), member_name(date))
        expected, n = verify_rederive(raw, date)
        sample = (root / ir["sample_path"]).read_bytes()
        require(sample == expected, f"{date}: sample bytes differ from independent re-derivation")
        require(ir["records"] == n and ir["shape"] == [n, 3] and ir["value_count"] == 3 * n, f"{date}: counts")
        require(ir["sample_size_bytes"] == len(sample) == 24 * n, f"{date}: size")
        require(ir["missing_second_count"] == DAY_SECONDS - n == len(ir["missing_seconds"]), f"{date}: missing")
        require(n >= MIN_RECORDS, f"{date}: too few records")
        stored = struct.unpack(f"<{3 * n}d", sample)
        require(all(math.isfinite(v) for v in stored), f"{date}: non-finite")
        for k in range(3):
            comp = stored[k::3]
            require(min(comp) < max(comp), f"{date}: component {k} constant")
            require(ir["component_min"][k] == min(comp) and ir["component_max"][k] == max(comp), f"{date}: min/max")
            require(ir["component_distinct_counts"][k] == len(set(comp)), f"{date}: distinct count")
        require(ir["min"] == min(stored) and ir["max"] == max(stored), f"{date}: global min/max")
        digest = hashlib.sha256(sample).hexdigest()
        require(ir["sha256"] == digest and digest not in seen, f"{date}: sha256")
        seen.add(digest)
        total_bytes += len(sample)
        values.append(3 * n)
        print(f"verified date={date} records={n}")
    require(series["sample_count"] == len(idx_rows), f"manifest sample_count {series['sample_count']} != {len(idx_rows)}")
    require(series["total_size_bytes"] == total_bytes, f"manifest total_size_bytes {series['total_size_bytes']} != {total_bytes}")
    values.sort()
    median = values[len(values) // 2]
    require(sum(values) >= 10_000 and median >= 1_000, "acceptance floor")
    print(f"verify_ok samples={len(idx_rows)} bytes={total_bytes} values={sum(values)} median_values={median}")
    return 0


# ---------------------------------------------------------------------------
# Synthetic self-test
# ---------------------------------------------------------------------------

def synthetic_member(date: dt.date, seconds: list[int], ncols_extra: bool = True) -> tuple[bytes, list[float]]:
    names = ["gps_time", "GRACEFO_id", *COLUMNS, "ang_accl_x", "ang_accl_y", "ang_accl_z",
             "acl_x_res", "acl_y_res", "acl_z_res", "qualflg"]
    var_lines = []
    for i, n in enumerate(names, 1):
        suffix = ORDINAL.get(i, f"{i}th")
        var_lines += [f"    - {n}:", f"        comment: {suffix} column", "        units: x"]
    t0 = day_start_gps(date)
    hdr = "\n".join([
        "header:", "  dimensions:", f"    num_records: {len(seconds)}", "  global_attributes:",
        "    history:",
        f'      - "INPUT FILE NAME               : ACC1A<-{L1A_INPUT}_{date.isoformat()}_D_04.dat"',
        f"    id: {DOI}", f"    license: {LICENSE_URL}", "    platform: GRACE D", "    product_version: 04",
        f"    time_coverage_start: {date.isoformat()}T00:00:00.00", f"    title: {TITLE}",
        "  non-standard_attributes:", f"    software_version: {SOFTWARE_VERSION}",
        f"    start_time_epoch_secs: {t0}", "  variables:", *var_lines, END_MARK,
    ])
    vals: list[float] = []
    rows = []
    for j, s in enumerate(seconds):
        xyz = [1.433859730278667e-07 + j * 1.1e-11, 1.075182061782305e-05 - j * 3.3e-12, -1.70982735176955e-07 * (1 + j % 7)]
        vals += [float(repr(v)) for v in xyz]
        rows.append(f"{t0 + s} D {xyz[0]!r} {xyz[1]!r} {xyz[2]!r} 0 0 {'1e-9' if j == 2 else '0'} "
                    f"1.3e-10 -7.7e-11 -5.9e-12  {'00000100' if j == 1 else '00000000'}")
    return (hdr + "\n" + "\n".join(rows) + "\n").encode("ascii"), vals


def synthetic_tar(members: dict[str, bytes], bad_md5: str | None = None) -> bytes:
    buf = io.BytesIO()
    lines = []
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, body in members.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(body)
            tf.addfile(ti, io.BytesIO(body))
            md5 = hashlib.md5(body).hexdigest() if name != bad_md5 else "0" * 32
            lines.append(f"{md5}  {name}")
        ck = ("\n".join(lines) + "\n").encode()
        ti = tarfile.TarInfo("checksum")
        ti.size = len(ck)
        tf.addfile(ti, io.BytesIO(ck))
    return buf.getvalue()


def selftest() -> None:
    import tempfile
    date = dt.date(2024, 2, 29)
    secs = [0, 1, 2, 3, 5, 6, 86399]
    body, vals = synthetic_member(date, secs)
    members = {f"AC01B_{date}_D_04.txt": b"other\n", member_name(date): body, f"ACU1B_{date}_D_04.txt": b"x\n"}
    with tempfile.TemporaryDirectory(prefix="ach1b_selftest_") as tmp:
        good = Path(tmp) / "good.tgz"
        good.write_bytes(synthetic_tar(members))
        raw, info = stream_tarball(good, member_name(date))
        require(raw == body and len(info["members"]) == 3, "selftest: stream_tarball")
        parsed = parse_member(raw, date, min_records=1)
        require(list(parsed["values"]) == vals, "selftest: parsed values")
        require(parsed["missing_seconds"] == sorted(set(range(DAY_SECONDS)) - set(secs)), "selftest: missing")
        require(parsed["qualflg_nonzero_rows"] == 1 and parsed["ang_accl_nonzero_rows"] == 1, "selftest: flags")
        payload = to_le_bytes(parsed["values"])
        require(payload == struct.pack(f"<{len(vals)}d", *vals), "selftest: LE packing")
        require(verify_extract(good, member_name(date)) == body, "selftest: verify_extract")
        rederived, n = verify_rederive(body, date)
        require(rederived == payload and n == len(secs), "selftest: verify path differs from build path")
        bad = Path(tmp) / "bad.tgz"
        bad.write_bytes(synthetic_tar(members, bad_md5=member_name(date)))
        for fn in (lambda: stream_tarball(bad, member_name(date)), lambda: verify_extract(bad, member_name(date))):
            try:
                fn()
            except RecipeError:
                pass
            else:
                raise RecipeError("selftest: md5 mismatch not detected")
        missing = Path(tmp) / "missing.tgz"
        missing.write_bytes(synthetic_tar({k: v for k, v in members.items() if not k.startswith("ACH1B")}))
        try:
            stream_tarball(missing, member_name(date))
        except RecipeError:
            pass
        else:
            raise RecipeError("selftest: missing ACH1B not detected")
    # Lattice violation and wrong-day rows must be rejected.
    for bad_secs in ([0, 0, 1], [0, 2, 1]):
        b, _ = synthetic_member(date, bad_secs)
        try:
            parse_member(b, date, min_records=1)
        except RecipeError:
            pass
        else:
            raise RecipeError(f"selftest: lattice violation {bad_secs} not detected")
    b, _ = synthetic_member(date, [0, 1, 2])
    try:
        parse_member(b, date + dt.timedelta(days=1), min_records=1)
    except RecipeError:
        pass
    else:
        raise RecipeError("selftest: wrong-day file not detected")
    require(day_start_gps(dt.date(2023, 1, 1)) == 725803200, "selftest: GPS day start")
    print("selftest_ok")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("selftest")
    for name in ("validate-downloads", "build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--repo-root", type=Path, required=True)
        p.add_argument("--data-dir", required=True)
        p.add_argument("--sources", type=Path, required=True)
        if name == "validate-downloads":
            p.add_argument("--quarantine", action="store_true")
        if name == "verify":
            p.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.cmd == "selftest":
            selftest()
            return 0
        return {"validate-downloads": cmd_validate, "build": cmd_build, "verify": cmd_verify}[args.cmd](args)
    except RecipeError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
