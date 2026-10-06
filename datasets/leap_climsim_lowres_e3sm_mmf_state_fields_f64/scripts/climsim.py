#!/usr/bin/env python3
"""ClimSim low-res E3SM-MMF `state_t` recipe helper (pure standard library).

Subcommands (network I/O is always done by curl in the shell scripts; this
helper only plans, parses and validates local files):

  plan            print the deterministic list of candidate repo paths
  pin             combine paths-info JSON responses into selection.tsv
  check-meta      validate the HF revision API record and README license
  check-paths     validate paths-info responses against selection.tsv
  validate-heads  parse every fetched header prefix; write the data-range plan
  validate-data   validate every fetched state_t range (HTTP + values)
  build           emit little-endian float64 samples and the sample index
  verify          independently re-derive and check the emitted output
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cdf5  # noqa: E402

DATASET_ID = "leap_climsim_lowres_e3sm_mmf_state_fields_f64"
SERIES_ID = "climsim_e3sm_mmf_state_t_f64"
REPO = "LEAP/ClimSim_low-res"
REVISION = "bab82a2ebdc750a0134ddcd0d5813867b92eed2a"
VARIABLE = "state_t"
NCOL = 384
NLEV = 60
VALUE_COUNT = NCOL * NLEV
VSIZE = VALUE_COUNT * 8
FILE_SIZE = 1897632
HEAD_BYTES = 4096

# Deterministic timestep rule: model years 0002..0008 (E3SM NO_LEAP calendar,
# 72 twenty-minute steps per day), one file every 223 steps (74 h 20 min)
# starting at 0002-01-01-00000. 223 mod 72 = 7 is coprime with 72, so the
# time of day rotates through all 72 steps instead of aliasing the diurnal
# cycle, and no two selected files are adjacent.
FIRST_YEAR = 2
LAST_YEAR = 8
STEPS_PER_DAY = 72
STEP_SECONDS = 1200
STRIDE_STEPS = 223
MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

# Decode-garbage guard for air temperature on the 60 model levels. These are
# deliberately wide: they reject byte garbage read as doubles (tiny or huge
# exponents, negatives), not model physics. The model top (lev 0) has genuine
# transient hot spots: selected file 0008-06-10-68400 (ordinal 759) holds
# 414.2 K and 663.6 K at lev 0, columns 302-303, confirmed against the
# sha256-verified whole file (it is a download canary) and kept as source
# content. Across the 825 selected fields the stored values span 146.2-663.6 K.
T_MIN_K = 50.0
T_MAX_K = 1000.0

SELECTION_COLUMNS = ["ordinal", "path", "ymd", "tod_seconds", "size_bytes", "lfs_sha256", "xet_hash"]


def fail(message: str) -> None:
    raise SystemExit(f"FATAL: {message}")


# ---------------------------------------------------------------------------
# Selection


def planned_steps() -> list[dict]:
    rows = []
    total_steps = (LAST_YEAR - FIRST_YEAR + 1) * 365 * STEPS_PER_DAY
    for ordinal, step in enumerate(range(0, total_steps, STRIDE_STEPS)):
        day, step_of_day = divmod(step, STEPS_PER_DAY)
        year_offset, day_of_year = divmod(day, 365)
        year = FIRST_YEAR + year_offset
        month = 0
        while day_of_year >= MONTH_DAYS[month]:
            day_of_year -= MONTH_DAYS[month]
            month += 1
        month += 1
        mday = day_of_year + 1
        tod = step_of_day * STEP_SECONDS
        path = f"train/{year:04d}-{month:02d}/E3SM-MMF.mli.{year:04d}-{month:02d}-{mday:02d}-{tod:05d}.nc"
        rows.append({"ordinal": ordinal, "path": path, "ymd": year * 10000 + month * 100 + mday, "tod_seconds": tod})
    return rows


def stem_of(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if not re.fullmatch(r"E3SM-MMF\.mli\.\d{4}-\d{2}-\d{2}-\d{5}\.nc", name):
        fail(f"unexpected file name {name!r}")
    return name[: -len(".nc")]


def read_selection(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].split("\t") != SELECTION_COLUMNS:
        fail(f"{path}: bad selection header")
    rows = []
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) != len(SELECTION_COLUMNS):
            fail(f"{path}: malformed row {line!r}")
        row = dict(zip(SELECTION_COLUMNS, parts))
        for key in ("ordinal", "ymd", "tod_seconds", "size_bytes"):
            row[key] = int(row[key])
        rows.append(row)
    planned = planned_steps()
    if [(r["ordinal"], r["path"], r["ymd"], r["tod_seconds"]) for r in rows] != [
        (p["ordinal"], p["path"], p["ymd"], p["tod_seconds"]) for p in planned
    ]:
        fail(f"{path} does not match the deterministic timestep rule")
    for row in rows:
        if row["size_bytes"] != FILE_SIZE:
            fail(f"{row['path']}: pinned size {row['size_bytes']} != {FILE_SIZE}")
        if not re.fullmatch(r"[0-9a-f]{64}", row["lfs_sha256"]) or not re.fullmatch(r"[0-9a-f]{64}", row["xet_hash"]):
            fail(f"{row['path']}: malformed pinned hashes")
    return rows


def load_paths_info(files: list[Path]) -> dict[str, dict]:
    entries: dict[str, dict] = {}
    for file in files:
        data = json.loads(file.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            fail(f"{file}: paths-info response is not a list")
        for item in data:
            if isinstance(item, dict) and item.get("type") == "file":
                entries[str(item.get("path"))] = item
    return entries


def cmd_plan(args) -> int:
    rows = planned_steps()
    out = Path(args.output)
    out.write_text("".join(row["path"] + "\n" for row in rows), encoding="utf-8")
    print(f"planned {len(rows)} timesteps -> {out}")
    return 0


def cmd_pin(args) -> int:
    entries = load_paths_info([Path(p) for p in args.paths_info])
    planned = planned_steps()
    missing = [row["path"] for row in planned if row["path"] not in entries]
    if missing:
        fail(f"{len(missing)} planned paths absent at revision, e.g. {missing[:3]}")
    lines = ["\t".join(SELECTION_COLUMNS)]
    for row in planned:
        item = entries[row["path"]]
        lfs = item.get("lfs") or {}
        size = int(item.get("size") or 0)
        if size != FILE_SIZE or int(lfs.get("size") or 0) != FILE_SIZE:
            fail(f"{row['path']}: unexpected size {size}")
        lines.append("\t".join(str(x) for x in [row["ordinal"], row["path"], row["ymd"], row["tod_seconds"], size, lfs.get("oid"), item.get("xetHash")]))
    Path(args.output).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"pinned {len(planned)} files -> {args.output}")
    return 0


# ---------------------------------------------------------------------------
# Download-time validation


def cmd_check_meta(args) -> int:
    info = json.loads(Path(args.api_info).read_text(encoding="utf-8"))
    if info.get("id") != REPO or info.get("sha") != REVISION:
        fail(f"API record identity changed: id={info.get('id')!r} sha={info.get('sha')!r}")
    if info.get("gated") not in (False, None) or info.get("private") or info.get("disabled"):
        fail(f"repository access changed: gated={info.get('gated')!r} private={info.get('private')!r} disabled={info.get('disabled')!r}")
    license_id = str((info.get("cardData") or {}).get("license") or "")
    if license_id.lower() != "cc-by-4.0":
        fail(f"cardData.license changed: {license_id!r}")
    readme = Path(args.readme).read_text(encoding="utf-8")
    front = re.match(r"^---\s*\n(.*?)\n---", readme, flags=re.S)
    if not front or not re.search(r"^license:\s*cc-by-4\.0\s*$", front.group(1), flags=re.M):
        fail("README.md front matter no longer declares license: cc-by-4.0")
    print(f"meta_validation=ok repo={REPO} sha={REVISION} license=cc-by-4.0 gated=false")
    return 0


def cmd_check_paths(args) -> int:
    rows = read_selection(Path(args.selection))
    entries = load_paths_info([Path(p) for p in args.paths_info])
    for row in rows:
        item = entries.get(row["path"])
        if item is None:
            fail(f"{row['path']}: absent from paths-info at revision {REVISION}")
        lfs = item.get("lfs") or {}
        if int(item.get("size") or 0) != row["size_bytes"] or lfs.get("oid") != row["lfs_sha256"] or item.get("xetHash") != row["xet_hash"]:
            fail(f"{row['path']}: upstream metadata differs from pinned selection")
    print(f"paths_validation=ok files={len(rows)}")
    return 0


def parse_http(path: Path) -> tuple[dict, list[dict]]:
    """Split a curl --dump-header file into response blocks; return the final
    206 block and every block (lower-cased header names)."""
    text = path.read_text(encoding="iso-8859-1")
    blocks = []
    for chunk in re.split(r"(?=^HTTP/)", text, flags=re.M):
        if not chunk.strip():
            continue
        first, *rest = chunk.strip().splitlines()
        match = re.match(r"HTTP/\S+\s+(\d+)", first)
        if not match:
            continue
        headers = {}
        for line in rest:
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()
        blocks.append({"status": int(match.group(1)), "reason": first, "headers": headers})
    blocks = [b for b in blocks if "connection established" not in b["reason"].lower()]
    finals = [b for b in blocks if b["status"] == 206]
    if not finals:
        fail(f"{path}: no 206 Partial Content response")
    return finals[-1], blocks


def strip_etag(value: str) -> str:
    value = value.strip()
    if value.startswith("W/"):
        value = value[2:]
    return value.strip('"')


def check_range_http(http_path: Path, row: dict, start: int, end: int) -> None:
    final, blocks = parse_http(http_path)
    content_range = final["headers"].get("content-range", "")
    expected = f"bytes {start}-{end}/{row['size_bytes']}"
    if content_range != expected:
        fail(f"{http_path.name}: Content-Range {content_range!r} != {expected!r}")
    etag = strip_etag(final["headers"].get("etag", ""))
    linked = [strip_etag(b["headers"]["x-linked-etag"]) for b in blocks if "x-linked-etag" in b["headers"]]
    if etag not in (row["xet_hash"], row["lfs_sha256"]):
        fail(f"{http_path.name}: CDN ETag {etag!r} matches neither pinned xet hash nor LFS sha256")
    if row["lfs_sha256"] not in linked and etag != row["lfs_sha256"]:
        fail(f"{http_path.name}: no X-Linked-Etag equal to pinned LFS sha256 {row['lfs_sha256']}")
    for block in blocks:
        size = block["headers"].get("x-linked-size")
        if size is not None and int(size) != row["size_bytes"]:
            fail(f"{http_path.name}: X-Linked-Size {size} != {row['size_bytes']}")


def check_header_layout(header: cdf5.Header, prefix: bytes, row: dict, label: str) -> cdf5.Var:
    if header.version != 5:
        fail(f"{label}: expected CDF-5, got version {header.version}")
    if header.dim("ncol").length != NCOL or header.dim("lev").length != NLEV:
        fail(f"{label}: unexpected dims {header.dims}")
    if header.gattrs.get("calendar") != "NO_LEAP":
        fail(f"{label}: calendar attribute changed: {header.gattrs.get('calendar')!r}")
    var = header.var(VARIABLE)
    dim_names = [header.dims[d].name for d in var.dimids]
    if var.nc_type != cdf5.NC_DOUBLE or dim_names != ["lev", "ncol"] or var.is_record:
        fail(f"{label}: {VARIABLE} is {var.type_name} {dim_names} record={var.is_record}")
    if var.vsize != VSIZE or var.begin < header.header_end or var.begin + var.vsize > row["size_bytes"]:
        fail(f"{label}: {VARIABLE} begin={var.begin} vsize={var.vsize} outside file of {row['size_bytes']} bytes")
    for scalar, expected in (("ymd", row["ymd"]), ("tod", row["tod_seconds"])):
        item = header.var(scalar)
        if item.type_name != "NC_INT" or item.shape != [] or item.begin + 4 > len(prefix):
            fail(f"{label}: scalar {scalar} not readable from the {len(prefix)}-byte prefix")
        value = struct.unpack(">i", prefix[item.begin:item.begin + 4])[0]
        if value != expected:
            fail(f"{label}: in-file {scalar}={value} disagrees with file name ({expected})")
    return var


def decode_values(raw: bytes, label: str) -> tuple[float, ...]:
    if len(raw) != VSIZE:
        fail(f"{label}: {len(raw)} bytes, expected {VSIZE}")
    values = struct.unpack(f">{VALUE_COUNT}d", raw)
    lo = min(values)
    hi = max(values)
    if not all(math.isfinite(v) for v in values):
        fail(f"{label}: non-finite temperature values")
    if lo < T_MIN_K or hi > T_MAX_K:
        fail(f"{label}: temperature range {lo}..{hi} K outside [{T_MIN_K}, {T_MAX_K}]")
    if lo == hi:
        fail(f"{label}: constant field")
    # Gross structure: the lowest model level (index 59) is warmer on average
    # than the tropopause region (levels 15..25), as in any real atmosphere.
    surface = sum(values[(NLEV - 1) * NCOL:]) / NCOL
    tropo = sum(values[15 * NCOL:26 * NCOL]) / (11 * NCOL)
    if not surface > tropo + 20.0:
        fail(f"{label}: implausible vertical structure (surface mean {surface:.2f} K, tropopause-band mean {tropo:.2f} K)")
    return values


def paths_for(download_dir: Path, row: dict) -> dict[str, Path]:
    stem = stem_of(row["path"])
    return {
        "head": download_dir / "heads" / f"{stem}.head",
        "head_http": download_dir / "heads" / f"{stem}.head.http",
        "data": download_dir / VARIABLE / f"{stem}.{VARIABLE}.be",
        "data_http": download_dir / VARIABLE / f"{stem}.{VARIABLE}.be.http",
    }


def cmd_validate_heads(args) -> int:
    rows = read_selection(Path(args.selection))
    download_dir = Path(args.download_dir)
    plan_lines = []
    begins = set()
    for row in rows:
        paths = paths_for(download_dir, row)
        prefix = paths["head"].read_bytes()
        if len(prefix) != HEAD_BYTES:
            fail(f"{paths['head'].name}: {len(prefix)} bytes, expected {HEAD_BYTES}")
        check_range_http(paths["head_http"], row, 0, HEAD_BYTES - 1)
        try:
            header = cdf5.parse_header(prefix)
        except cdf5.CDFError as exc:
            fail(f"{paths['head'].name}: header parse failed: {exc}")
        var = check_header_layout(header, prefix, row, paths["head"].name)
        begins.add(var.begin)
        plan_lines.append(f"{row['ordinal']}\t{row['path']}\t{var.begin}\t{var.begin + var.vsize - 1}")
    Path(args.plan).write_text("\n".join(plan_lines) + "\n", encoding="utf-8")
    print(f"head_validation=ok files={len(rows)} {VARIABLE}_begin_offsets={sorted(begins)} plan={args.plan}")
    return 0


def cmd_validate_data(args) -> int:
    rows = read_selection(Path(args.selection))
    download_dir = Path(args.download_dir)
    plan = {}
    for line in Path(args.plan).read_text(encoding="utf-8").splitlines():
        ordinal, path, start, end = line.split("\t")
        plan[path] = (int(start), int(end))
    digests = {}
    for row in rows:
        paths = paths_for(download_dir, row)
        start, end = plan[row["path"]]
        check_range_http(paths["data_http"], row, start, end)
        raw = paths["data"].read_bytes()
        decode_values(raw, paths["data"].name)
        digest = hashlib.sha256(raw).hexdigest()
        if digest in digests:
            fail(f"{paths['data'].name}: identical payload to {digests[digest]}")
        digests[digest] = paths["data"].name
    print(f"data_validation=ok files={len(rows)} distinct_payloads={len(digests)}")
    return 0


CANARY_ORDINALS = (0, 759, 824)


def cmd_check_canaries(args) -> int:
    """Whole-file canaries: sha256 equals the pinned LFS oid, and the separately
    range-fetched header prefix and state_t slab equal the same byte slices
    of the verified whole file (proves the CDN Range semantics)."""
    rows = {row["ordinal"]: row for row in read_selection(Path(args.selection))}
    download_dir = Path(args.download_dir)
    plan = {}
    for line in Path(args.plan).read_text(encoding="utf-8").splitlines():
        ordinal, path, start, end = line.split("\t")
        plan[path] = (int(start), int(end))
    for ordinal in CANARY_ORDINALS:
        row = rows[ordinal]
        whole_path = download_dir / "canary" / row["path"].rsplit("/", 1)[-1]
        whole = whole_path.read_bytes()
        if len(whole) != row["size_bytes"] or hashlib.sha256(whole).hexdigest() != row["lfs_sha256"]:
            fail(f"canary {whole_path.name}: size/sha256 differ from pinned LFS object")
        paths = paths_for(download_dir, row)
        start, end = plan[row["path"]]
        if whole[:HEAD_BYTES] != paths["head"].read_bytes():
            fail(f"canary {whole_path.name}: header range bytes differ from the whole file")
        if whole[start:end + 1] != paths["data"].read_bytes():
            fail(f"canary {whole_path.name}: state_t range bytes differ from the whole file")
        header = cdf5.parse_header(whole)
        var = header.var(VARIABLE)
        if (var.begin, var.begin + var.vsize - 1) != (start, end):
            fail(f"canary {whole_path.name}: whole-file header disagrees with range plan")
        last = max(v.begin + v.vsize for v in header.vars)
        if last != len(whole):
            fail(f"canary {whole_path.name}: variables end at {last}, file is {len(whole)} bytes")
    print(f"canary_validation=ok ordinals={list(CANARY_ORDINALS)} (sha256 + range-slice equality)")
    return 0


# ---------------------------------------------------------------------------
# Build and verify


def sample_relpath(row: dict) -> str:
    return f"samples/{DATASET_ID}/{SERIES_ID}/{stem_of(row['path'])}.{VARIABLE}.f64le.bin"


def derive(download_dir: Path, row: dict) -> tuple[bytes, float, float, dict]:
    """Decode one selected timestep's state_t into little-endian float64."""
    paths = paths_for(download_dir, row)
    prefix = paths["head"].read_bytes()
    header = cdf5.parse_header(prefix)
    var = check_header_layout(header, prefix, row, paths["head"].name)
    raw = paths["data"].read_bytes()
    values = decode_values(raw, paths["data"].name)
    out = struct.pack(f"<{VALUE_COUNT}d", *values)
    stored = struct.unpack(f"<{VALUE_COUNT}d", out)
    return out, min(stored), max(stored), {"begin": var.begin, "vsize": var.vsize}


def index_row(row: dict, payload: bytes, lo: float, hi: float, layout: dict) -> dict:
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_path": sample_relpath(row),
        "numeric_kind": "float",
        "bit_width": 64,
        "endianness": "little",
        "element_size_bytes": 8,
        "sample_size_bytes": len(payload),
        "value_count": VALUE_COUNT,
        "shape": [NLEV, NCOL],
        "axes": ["lev", "ncol"],
        "source_repo": f"https://huggingface.co/datasets/{REPO}",
        "source_revision": REVISION,
        "source_path": row["path"],
        "source_lfs_sha256": row["lfs_sha256"],
        "source_variable": VARIABLE,
        "source_byte_range": [layout["begin"], layout["begin"] + layout["vsize"] - 1],
        "model_ymd": row["ymd"],
        "model_tod_seconds": row["tod_seconds"],
        "min": lo,
        "max": hi,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def cmd_build(args) -> int:
    rows = read_selection(Path(args.selection))
    download_dir = Path(args.download_dir)
    data_root = Path(args.data_root)
    series_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    series_dir.mkdir(parents=True, exist_ok=True)
    for stale in series_dir.glob("*"):
        stale.unlink()
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    out_rows = []
    lo_all, hi_all = math.inf, -math.inf
    for row in rows:
        payload, lo, hi, layout = derive(download_dir, row)
        target = data_root / sample_relpath(row)
        tmp = target.with_suffix(target.suffix + ".part")
        tmp.write_bytes(payload)
        tmp.replace(target)
        out_rows.append(index_row(row, payload, lo, hi, layout))
        lo_all, hi_all = min(lo_all, lo), max(hi_all, hi)
    index_tmp = index_path.with_suffix(".jsonl.part")
    index_tmp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in out_rows), encoding="utf-8")
    index_tmp.replace(index_path)
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "samples": len(out_rows),
        "values": len(out_rows) * VALUE_COUNT,
        "bytes": sum(r["sample_size_bytes"] for r in out_rows),
        "min_k": lo_all,
        "max_k": hi_all,
        "first": rows[0]["path"],
        "last": rows[-1]["path"],
    }
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=1) + "\n", encoding="utf-8")
    print(f"build ok samples={stats['samples']} values={stats['values']} bytes={stats['bytes']} range_K={lo_all}..{hi_all}")
    return 0


def cmd_verify(args) -> int:
    rows = read_selection(Path(args.selection))
    download_dir = Path(args.download_dir)
    data_root = Path(args.data_root)
    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != DATASET_ID:
        fail("manifest dataset_id mismatch")
    series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
    if len(series) != 1 or series[0].get("role") != "primary":
        fail("manifest must declare exactly one primary series " + SERIES_ID)
    series = series[0]
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    index_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(index_rows) != len(rows):
        fail(f"index has {len(index_rows)} rows, selection has {len(rows)}")
    expected_files = set()
    digests = set()
    total_bytes = 0
    lo_all, hi_all = math.inf, -math.inf
    for row, entry in zip(rows, index_rows):
        payload, lo, hi, layout = derive(download_dir, row)
        expected = index_row(row, payload, lo, hi, layout)
        if entry != expected:
            diff = sorted(k for k in set(entry) | set(expected) if entry.get(k) != expected.get(k))
            fail(f"index row for {row['path']} differs from re-derivation in {diff}")
        sample = data_root / entry["sample_path"]
        on_disk = sample.read_bytes()
        if on_disk != payload:
            fail(f"{entry['sample_path']}: bytes differ from independent re-derivation")
        # Second, struct-free conversion path: reversing each 8-byte group of
        # the big-endian source slab must give the stored little-endian bytes.
        source = paths_for(download_dir, row)["data"].read_bytes()
        swapped = b"".join(source[i:i + 8][::-1] for i in range(0, len(source), 8))
        if swapped != on_disk:
            fail(f"{entry['sample_path']}: byte-swap cross-check against source slab failed")
        if len(on_disk) != entry["value_count"] * entry["element_size_bytes"]:
            fail(f"{entry['sample_path']}: size/value_count mismatch")
        stored = struct.unpack(f"<{VALUE_COUNT}d", on_disk)
        if not all(math.isfinite(v) for v in stored) or min(stored) != entry["min"] or max(stored) != entry["max"]:
            fail(f"{entry['sample_path']}: stored values disagree with index min/max or are non-finite")
        if len(set(stored)) < VALUE_COUNT // 4:
            fail(f"{entry['sample_path']}: degenerate field ({len(set(stored))} distinct values)")
        if entry["sha256"] in digests:
            fail(f"{entry['sample_path']}: duplicate sample payload")
        digests.add(entry["sha256"])
        expected_files.add(sample.name)
        total_bytes += len(on_disk)
        lo_all, hi_all = min(lo_all, min(stored)), max(hi_all, max(stored))
    series_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    present = {p.name for p in series_dir.iterdir()}
    if present != expected_files:
        fail(f"sample directory has unexpected files: {sorted(present - expected_files)[:5]} missing: {sorted(expected_files - present)[:5]}")
    other = [p.name for p in (data_root / "samples" / DATASET_ID).iterdir() if p.name != SERIES_ID]
    if other:
        fail(f"unexpected entries under samples/{DATASET_ID}: {other}")
    if series.get("sample_count") != len(rows) or series.get("total_size_bytes") != total_bytes:
        fail(f"manifest sample_count/total_size_bytes {series.get('sample_count')}/{series.get('total_size_bytes')} != realized {len(rows)}/{total_bytes}")
    if hi_all - lo_all < 50.0:
        fail(f"series range {lo_all}..{hi_all} K is implausibly narrow")
    print(f"verify ok samples={len(rows)} bytes={total_bytes} distinct_payloads={len(digests)} range_K={lo_all}..{hi_all}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--output", required=True)
    p = sub.add_parser("pin")
    p.add_argument("--output", required=True)
    p.add_argument("paths_info", nargs="+")
    p = sub.add_parser("check-meta")
    p.add_argument("--api-info", required=True)
    p.add_argument("--readme", required=True)
    p = sub.add_parser("check-paths")
    p.add_argument("--selection", required=True)
    p.add_argument("paths_info", nargs="+")
    for name in ("validate-heads", "validate-data", "check-canaries"):
        p = sub.add_parser(name)
        p.add_argument("--selection", required=True)
        p.add_argument("--download-dir", required=True)
        p.add_argument("--plan", required=True)
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--selection", required=True)
        p.add_argument("--download-dir", required=True)
        p.add_argument("--data-root", required=True)
        if name == "verify":
            p.add_argument("--manifest", required=True)
    args = parser.parse_args()
    handlers = {
        "plan": cmd_plan,
        "pin": cmd_pin,
        "check-meta": cmd_check_meta,
        "check-paths": cmd_check_paths,
        "validate-heads": cmd_validate_heads,
        "validate-data": cmd_validate_data,
        "check-canaries": cmd_check_canaries,
        "build": cmd_build,
        "verify": cmd_verify,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
