#!/usr/bin/env python3
"""ResStock 2021 (AMY2018, release 1) state-level single-family-detached
aggregate load profiles: pinned-source checks, strict CSV parsing, the global
end-use selection rule, and the sample build. Pure standard library.

Subcommands
  discover       S3 ListObjectsV2 XML -> sources.tsv (run once by discover.sh)
  check-listing  live listing must match sources.tsv (key, size, ETag, date)
  check-meta     data dictionary (pinned md5; kWh/float columns, EST
                 timestamps) and OEDI submission page (CC BY 4.0, DOI)
  check-file     size and md5 (= single-part S3 ETag) of one downloaded CSV
  validate       md5 plus full structural parse of all 49 downloaded CSVs
  build          parse, apply the selection rule, write samples and index
"""
from __future__ import annotations

import argparse
import array
import csv
import datetime
import hashlib
import json
import math
import re
import shutil
import statistics
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

DATASET_ID = "nrel_resstock2021_state_enduse_load_profiles_f64"
SERIES_ID = "resstock_sfd_state_enduse_energy_kwh_15min_f64"
BUCKET_URL = "https://oedi-data-lake.s3.amazonaws.com"
RELEASE_PREFIX = (
    "nrel-pds-building-stock/end-use-load-profiles-for-us-building-stock/2021/resstock_amy2018_release_1"
)
BY_STATE_PREFIX = RELEASE_PREFIX + "/timeseries_aggregates/by_state/"
KEY_RE = re.compile(re.escape(BY_STATE_PREFIX) + r"state=([A-Z]{2})/([a-z]{2})-single-family_detached\.csv$")
DICTIONARY_SIZE = 174446
DICTIONARY_MD5 = "63dd52cb2464d68104b578f0f898813e"
OEDI_TITLE = "End-Use Load Profiles for the U.S. Building Stock"
OEDI_DOI = "10.25984/1876417"
LICENSE_JSONLD_RE = re.compile(r'"license"\s*:\s*"https://creativecommons\.org/licenses/by/4\.0/?"')
EXPECTED_STATE_COUNT = 49
N_ROWS = 35040
START = datetime.datetime(2018, 1, 1, 0, 0, 0)
STEP = datetime.timedelta(minutes=15)
LEADING = ["in.state", "in.geometry_building_type_recs", "timestamp", "models_used", "units_represented"]
BUILDING_TYPE = "Single-Family Detached"
PV_COLUMN = "out.electricity.pv.energy_consumption"
MIN_DISTINCT = 1000
RESCALE_RTOL = 1e-9
TOTAL_RTOL = 1e-9
SITE_TOTAL_RTOL = 1e-5
MAX_PRIMARY_BYTES = 1_000_000_000
S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"


class RecipeError(Exception):
    pass


# ----------------------------------------------------------------- pins


def read_tsv(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    rows = []
    for number, line in enumerate(lines[1:], 2):
        fields = line.split("\t")
        if len(fields) != len(header):
            raise RecipeError(f"{path.name}:{number}: expected {len(header)} fields, got {len(fields)}")
        rows.append(dict(zip(header, fields)))
    return rows


def load_columns(recipe_dir: Path) -> list[dict]:
    columns = read_tsv(recipe_dir / "columns.tsv")
    if len(columns) != 54:
        raise RecipeError(f"columns.tsv must list 54 out.* columns, found {len(columns)}")
    for col in columns:
        kind, expected = col["kind"], col["expected"]
        if kind == "total" and expected != "total":
            raise RecipeError(f"columns.tsv: total column {col['column']} must have expected=total")
        if kind == "end_use" and expected not in {"keep", "drop"}:
            raise RecipeError(f"columns.tsv: end-use column {col['column']} must have expected keep|drop")
        if col["column"] != f"out.{col['fuel']}.{col['end_use']}.energy_consumption":
            raise RecipeError(f"columns.tsv: column name {col['column']} disagrees with fuel/end_use")
    return columns


def load_sources(recipe_dir: Path) -> list[dict]:
    sources = read_tsv(recipe_dir / "sources.tsv")
    if len(sources) != EXPECTED_STATE_COUNT:
        raise RecipeError(f"sources.tsv must pin {EXPECTED_STATE_COUNT} state files, found {len(sources)}")
    states = [s["state"] for s in sources]
    if states != sorted(states) or len(set(states)) != len(states):
        raise RecipeError("sources.tsv states must be unique and sorted")
    for src in sources:
        match = KEY_RE.fullmatch(src["key"])
        if not match or match.group(1) != src["state"] or match.group(2) != src["state"].lower():
            raise RecipeError(f"sources.tsv: unexpected key {src['key']}")
        if not re.fullmatch(r"[0-9a-f]{32}", src["etag_md5"]):
            raise RecipeError(f"sources.tsv: {src['state']} ETag is not a single-part md5")
        src["size_bytes"] = int(src["size_bytes"])
    return sources


def local_csv(download_dir: Path, state: str) -> Path:
    return download_dir / "by_state" / f"{state.lower()}-single-family_detached.csv"


def object_url(key: str) -> str:
    return f"{BUCKET_URL}/{key.replace('=', '%3D')}"


def sample_name(state: str, column: dict) -> str:
    return f"{state}__{column['fuel']}.{column['end_use']}.f64le.bin"


def expected_timestamps(n_rows: int = N_ROWS, start: datetime.datetime = START) -> list[str]:
    return [(start + STEP * (k + 1)).strftime("%Y-%m-%d %H:%M:%S") for k in range(n_rows)]


def md5_file(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# -------------------------------------------------------------- listing


def parse_listing(path: Path) -> dict[str, dict]:
    root = ET.parse(path).getroot()
    truncated = root.findtext(f"{S3_NS}IsTruncated")
    if truncated != "false":
        raise RecipeError(f"listing {path.name}: IsTruncated={truncated!r}; expected a complete single page")
    entries = {}
    for item in root.findall(f"{S3_NS}Contents"):
        key = item.findtext(f"{S3_NS}Key")
        entries[key] = {
            "size_bytes": int(item.findtext(f"{S3_NS}Size")),
            "etag_md5": item.findtext(f"{S3_NS}ETag").strip('"'),
            "last_modified": item.findtext(f"{S3_NS}LastModified"),
        }
    return entries


def discover(listing: Path, out: Path) -> None:
    entries = parse_listing(listing)
    rows = []
    for key, entry in entries.items():
        match = KEY_RE.fullmatch(key)
        if match and match.group(2) == match.group(1).lower():
            rows.append((match.group(1), key, entry))
    rows.sort()
    if len(rows) != EXPECTED_STATE_COUNT:
        raise RecipeError(f"listing has {len(rows)} single-family-detached state files, expected {EXPECTED_STATE_COUNT}")
    lines = ["state\tkey\tsize_bytes\tetag_md5\tlast_modified"]
    for state, key, entry in rows:
        if not re.fullmatch(r"[0-9a-f]{32}", entry["etag_md5"]):
            raise RecipeError(f"{key}: multipart ETag {entry['etag_md5']}; md5 pinning impossible")
        lines.append(f"{state}\t{key}\t{entry['size_bytes']}\t{entry['etag_md5']}\t{entry['last_modified']}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    total = sum(entry["size_bytes"] for _, _, entry in rows)
    print(f"discover: {len(rows)} files, {total} bytes -> {out}")


def check_listing(listing: Path, sources: list[dict]) -> None:
    entries = parse_listing(listing)
    live = {key for key in entries if KEY_RE.fullmatch(key)}
    pinned = {src["key"] for src in sources}
    if live != pinned:
        raise RecipeError(f"listing single-family-detached keys differ from pins: extra={sorted(live - pinned)} missing={sorted(pinned - live)}")
    for src in sources:
        entry = entries[src["key"]]
        for field in ("size_bytes", "etag_md5", "last_modified"):
            if entry[field] != src[field]:
                raise RecipeError(f"{src['state']}: listing {field}={entry[field]!r} != pinned {src[field]!r}")
    total = sum(src["size_bytes"] for src in sources)
    print(f"check-listing: {len(sources)} pinned objects match (size, ETag, LastModified); {total} bytes")


def check_meta(dictionary: Path, oedi_page: Path, columns: list[dict]) -> None:
    if dictionary.stat().st_size != DICTIONARY_SIZE or md5_file(dictionary) != DICTIONARY_MD5:
        raise RecipeError("data_dictionary.tsv size/md5 differ from the pinned object")
    with dictionary.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh, delimiter="\t"))
    header = rows[0]
    if header[:5] != ["field_location", "field_name", "data_type", "units", "field_description"]:
        raise RecipeError(f"data_dictionary.tsv header {header}")
    by_name: dict[str, list[list[str]]] = {}
    for row in rows[1:]:
        by_name.setdefault(row[1], []).append(row)
    for col in columns:
        found = by_name.get(col["column"], [])
        if len(found) != 1:
            raise RecipeError(f"data dictionary lists {col['column']} {len(found)} times")
        row = found[0]
        if row[2] != "float" or row[3] != "kWh" or "timeseries" not in row[0]:
            raise RecipeError(f"data dictionary: {col['column']} is {row[2]!r}/{row[3]!r}/{row[0]!r}, expected float/kWh/timeseries")
    ts = by_name.get("timestamp", [])
    if len(ts) != 1 or "Eastern Standard Time" not in ts[0][4]:
        raise RecipeError("data dictionary: timestamp is not documented as Eastern Standard Time")
    page = oedi_page.read_text(encoding="utf-8", errors="replace")
    if OEDI_TITLE not in page or OEDI_DOI not in page:
        raise RecipeError("OEDI submission page lacks the expected title or DOI")
    if not LICENSE_JSONLD_RE.search(page):
        raise RecipeError("OEDI submission page JSON-LD does not declare https://creativecommons.org/licenses/by/4.0/")
    print("check-meta: data dictionary md5 ok; 54 out.* columns float/kWh; timestamps EST; OEDI 4520 license CC BY 4.0, DOI " + OEDI_DOI)


def check_file(path: Path, size: int, md5: str) -> None:
    actual = path.stat().st_size
    if actual != size:
        raise RecipeError(f"{path.name}: size {actual} != pinned {size}")
    digest = md5_file(path)
    if digest != md5:
        raise RecipeError(f"{path.name}: md5 {digest} != pinned ETag {md5}")


# ------------------------------------------------------------ CSV parse


def total_groups(columns: list[dict]) -> tuple[list[tuple[str, int, list[int]]], int, list[int]]:
    """(fuel, total offset, member offsets) per fuel, the site-total offset
    and the fuel-total offsets; offsets index the 54 out.* values."""
    groups = []
    fuel_totals = []
    site = -1
    for i, col in enumerate(columns):
        if col["kind"] != "total":
            continue
        if col["fuel"] == "site_energy":
            site = i
            continue
        members = [
            j
            for j, other in enumerate(columns)
            if other["kind"] == "end_use" and other["fuel"] == col["fuel"] and other["column"] != PV_COLUMN
        ]
        groups.append((col["fuel"], i, members))
        fuel_totals.append(i)
    if site < 0 or len(groups) != 5:
        raise RecipeError("columns.tsv must hold five fuel totals plus site_energy.total")
    return groups, site, fuel_totals


def parse_state_csv(path: Path, state: str, columns: list[dict], timestamps: list[str], store: bool = True) -> tuple[dict, dict]:
    """Strictly parse one state file. Returns ({end-use column: array('d')}
    when store, else {}) and per-file stats. Raises RecipeError on any
    structural, missing-value or consistency violation."""
    out_names = [col["column"] for col in columns]
    expected_header = LEADING + out_names
    width = len(expected_header)
    end_use_offsets = [i for i, col in enumerate(columns) if col["kind"] == "end_use"]
    groups, site, fuel_totals = total_groups(columns)
    series = {out_names[i]: array.array("d") for i in end_use_offsets} if store else {}
    appenders = [(i, series[out_names[i]].append) for i in end_use_offsets] if store else []
    meta = set()
    max_total_dev = {fuel: 0.0 for fuel, _, _ in groups}
    max_site_dev = 0.0
    isfinite = math.isfinite
    n = 0
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh, strict=True)
        header = next(reader, None)
        if header != expected_header:
            raise RecipeError(f"{path.name}: header differs from the pinned 59-column layout")
        for row in reader:
            if n >= len(timestamps):
                raise RecipeError(f"{path.name}: more than {len(timestamps)} data rows")
            if len(row) != width:
                raise RecipeError(f"{path.name}: row {n + 1} has {len(row)} fields, expected {width}")
            if row[0] != state or row[1] != BUILDING_TYPE:
                raise RecipeError(f"{path.name}: row {n + 1} is {row[0]!r}/{row[1]!r}, expected {state}/{BUILDING_TYPE}")
            if row[2] != timestamps[n]:
                raise RecipeError(f"{path.name}: row {n + 1} timestamp {row[2]!r} != expected {timestamps[n]!r}")
            meta.add((row[3], row[4]))
            try:
                values = [float(tok) for tok in row[5:]]
            except ValueError as exc:
                raise RecipeError(f"{path.name}: row {n + 1}: unparsable value ({exc})") from None
            if not all(map(isfinite, values)):
                raise RecipeError(f"{path.name}: row {n + 1}: non-finite value")
            for fuel, t, members in groups:
                parts = [values[j] for j in members]
                total = values[t]
                scale = math.fsum(abs(v) for v in parts) + abs(total)
                dev = abs(math.fsum(parts) - total)
                if dev > TOTAL_RTOL * scale + 1e-9:
                    raise RecipeError(f"{path.name}: row {n + 1}: {fuel} total deviates from its end-use sum by {dev}")
                if scale > 0 and dev / scale > max_total_dev[fuel]:
                    max_total_dev[fuel] = dev / scale
            site_parts = math.fsum(values[t] for t in fuel_totals)
            site_scale = abs(site_parts) + abs(values[site])
            if site_scale > 0:
                site_dev = abs(site_parts - values[site]) / site_scale
                if site_dev > SITE_TOTAL_RTOL:
                    raise RecipeError(f"{path.name}: row {n + 1}: site_energy total deviates from fuel totals by {site_dev:.3g}")
                max_site_dev = max(max_site_dev, site_dev)
            for i, append in appenders:
                append(values[i])
            n += 1
    if n != len(timestamps):
        raise RecipeError(f"{path.name}: {n} data rows, expected {len(timestamps)}")
    if len(meta) != 1:
        raise RecipeError(f"{path.name}: models_used/units_represented not constant: {sorted(meta)[:3]}")
    models_used, units_represented = next(iter(meta))
    if not re.fullmatch(r"[1-9][0-9]*", models_used):
        raise RecipeError(f"{path.name}: models_used {models_used!r} is not a positive integer")
    units = float(units_represented)
    if not (math.isfinite(units) and units > 0):
        raise RecipeError(f"{path.name}: units_represented {units_represented!r}")
    stats = {
        "state": state,
        "rows": n,
        "first_timestamp": timestamps[0],
        "last_timestamp": timestamps[-1],
        "models_used": int(models_used),
        "units_represented": units,
        "max_rel_dev_fuel_total_vs_end_uses": max_total_dev,
        "max_rel_dev_site_total_vs_fuel_totals": max_site_dev,
    }
    return series, stats


# --------------------------------------------------------- selection


def rescaled_pairs(series_by_state: dict, column: str, states: list[str], rtol: float = RESCALE_RTOL) -> list[dict]:
    """State pairs whose series for `column` are exact rescalings of each
    other: identical zero pattern and a ratio constant to rtol."""
    masks = {}
    nonzero = {}
    for st in states:
        x = series_by_state[st][column]
        masks[st] = bytes(1 if v == 0.0 else 0 for v in x)
        nonzero[st] = [i for i, v in enumerate(x) if v != 0.0]
    found = []
    for a_pos, a in enumerate(states):
        for b in states[a_pos + 1 :]:
            if masks[a] != masks[b] or not nonzero[a]:
                continue
            xa = series_by_state[a][column]
            xb = series_by_state[b][column]
            idx = nonzero[a]
            r0 = xa[idx[0]] / xb[idx[0]]
            tol = rtol * abs(r0)
            stride = max(1, len(idx) // 256)
            if any(abs(xa[i] / xb[i] - r0) > tol for i in idx[::stride]):
                continue
            ratios = [xa[i] / xb[i] for i in idx]
            spread = (max(ratios) - min(ratios)) / abs(r0)
            if spread <= rtol:
                found.append({"pair": [a, b], "ratio": r0, "rel_spread": spread})
    return found


def select_end_uses(series_by_state: dict, columns: list[dict], min_distinct: int = MIN_DISTINCT, rtol: float = RESCALE_RTOL) -> dict:
    """Global rule: an end use is kept iff, in every state, its series is
    (a) not all +-0, (b) has >= min_distinct distinct values, and (c) is not
    an exact rescaling of another state's series for the same end use."""
    states = sorted(series_by_state)
    report = {}
    for col in columns:
        if col["kind"] != "end_use":
            continue
        name = col["column"]
        per_state = {}
        all_zero, low_distinct = [], []
        for st in states:
            x = series_by_state[st][name]
            nonzero = sum(1 for v in x if v != 0.0)
            distinct = len(set(x))
            per_state[st] = {"nonzero": nonzero, "distinct": distinct}
            if nonzero == 0:
                all_zero.append(st)
            elif distinct < min_distinct:
                low_distinct.append(st)
        live = [st for st in states if per_state[st]["nonzero"] > 0]
        pairs = rescaled_pairs(series_by_state, name, live, rtol)
        reasons = []
        if all_zero:
            reasons.append("a_all_zero")
        if low_distinct:
            reasons.append("b_low_distinct")
        if pairs:
            reasons.append("c_rescaled_duplicate")
        report[name] = {
            "decision": "drop" if reasons else "keep",
            "expected": col["expected"],
            "reasons": reasons,
            "all_zero_states": all_zero,
            "low_distinct_states": {st: per_state[st]["distinct"] for st in low_distinct},
            "rescaled_pair_count": len(pairs),
            "rescaled_pairs_first": pairs[:5],
            "min_distinct": min((per_state[st]["distinct"] for st in states), default=0),
            "min_nonzero": min((per_state[st]["nonzero"] for st in states), default=0),
        }
    return report


# -------------------------------------------------------------- build


def validate(recipe_dir: Path, download_dir: Path, out_json: Path) -> None:
    columns = load_columns(recipe_dir)
    sources = load_sources(recipe_dir)
    timestamps = expected_timestamps()
    results = []
    for src in sources:
        path = local_csv(download_dir, src["state"])
        check_file(path, src["size_bytes"], src["etag_md5"])
        _, stats = parse_state_csv(path, src["state"], columns, timestamps, store=False)
        results.append(stats)
        print(f"validate: {src['state']} ok rows={stats['rows']} models_used={stats['models_used']}")
    out_json.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    print(f"validate: {len(results)} files ok")


def build(recipe_dir: Path, download_dir: Path, data_root: Path) -> None:
    columns = load_columns(recipe_dir)
    sources = load_sources(recipe_dir)
    timestamps = expected_timestamps()
    series_by_state = {}
    file_stats = {}
    for src in sources:
        path = local_csv(download_dir, src["state"])
        if path.stat().st_size != src["size_bytes"]:
            raise RecipeError(f"{path}: size differs from pin; re-run download.sh")
        series, stats = parse_state_csv(path, src["state"], columns, timestamps)
        series_by_state[src["state"]] = series
        file_stats[src["state"]] = stats
        print(f"parsed {src['state']} rows={stats['rows']}", flush=True)

    report = select_end_uses(series_by_state, columns)
    filtered_dir = data_root / "filtered" / DATASET_ID
    filtered_dir.mkdir(parents=True, exist_ok=True)
    (filtered_dir / "column_selection.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    for name, entry in report.items():
        flag = "" if entry["decision"] == entry["expected"] else "   <-- differs from columns.tsv"
        print(f"rule {entry['decision']:4s} {name} reasons={entry['reasons']} min_distinct={entry['min_distinct']} "
              f"zero_states={entry['all_zero_states'][:6]} rescaled_pairs={entry['rescaled_pair_count']}{flag}")
    kept = [col for col in columns if col["kind"] == "end_use" and report[col["column"]]["decision"] == "keep"]
    expected = [col for col in columns if col["expected"] == "keep"]
    if [c["column"] for c in kept] != [c["column"] for c in expected]:
        raise RecipeError(
            "selection rule result differs from the pinned keep list in columns.tsv: "
            f"realized={[c['column'] for c in kept]} pinned={[c['column'] for c in expected]}"
        )

    samples_dir = data_root / "samples" / DATASET_ID
    index_dir = data_root / "index" / DATASET_ID
    for stale in (samples_dir, index_dir):
        if stale.exists():
            shutil.rmtree(stale)
    series_dir = samples_dir / SERIES_ID
    series_dir.mkdir(parents=True)
    index_dir.mkdir(parents=True)
    rows = []
    hashes = set()
    for src in sources:
        st = src["state"]
        for col in kept:
            x = series_by_state[st][col["column"]]
            stored = array.array("d", x)
            if sys.byteorder != "little":
                stored.byteswap()
            raw = stored.tobytes()
            values = list(x)
            distinct = len(set(values))
            if distinct < MIN_DISTINCT:
                raise RecipeError(f"{st} {col['column']}: only {distinct} distinct values")
            digest = sha256_bytes(raw)
            if digest in hashes:
                raise RecipeError(f"{st} {col['column']}: duplicate sample bytes")
            hashes.add(digest)
            path = series_dir / sample_name(st, col)
            path.write_bytes(raw)
            rows.append({
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": str(path.relative_to(data_root)),
                "numeric_kind": "float",
                "bit_width": 64,
                "endianness": "little",
                "element_size_bytes": 8,
                "sample_size_bytes": len(raw),
                "value_count": len(values),
                "state": st,
                "source_column": col["column"],
                "fuel": col["fuel"],
                "end_use": col["end_use"],
                "unit": "kWh per 15-minute interval",
                "first_timestamp_est": timestamps[0],
                "last_timestamp_est": timestamps[-1],
                "interval_minutes": 15,
                "timestamp_convention": "interval-ending, Eastern Standard Time (no DST)",
                "models_used": file_stats[st]["models_used"],
                "units_represented": file_stats[st]["units_represented"],
                "source_key": src["key"],
                "source_md5": src["etag_md5"],
                "min": min(values),
                "max": max(values),
                "distinct_values": distinct,
                "zero_values": sum(1 for v in values if v == 0.0),
                "negative_values": sum(1 for v in values if v < 0.0),
                "sha256": digest,
            })
    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=False) + "\n")
    total_bytes = sum(r["sample_size_bytes"] for r in rows)
    counts = sorted(r["value_count"] for r in rows)
    if total_bytes > MAX_PRIMARY_BYTES:
        raise RecipeError(f"primary bytes {total_bytes} exceed the 1 GB cap")
    if statistics.median(counts) < 1000:
        raise RecipeError("median sample below 1,000 values")
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "states": len(sources),
        "kept_end_uses": [c["column"] for c in kept],
        "samples": len(rows),
        "values": sum(counts),
        "bytes": total_bytes,
        "files": file_stats,
    }
    (filtered_dir / "ingest_stats.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(f"build: {len(rows)} samples ({len(sources)} states x {len(kept)} end uses), {sum(counts)} values, {total_bytes} bytes")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("discover")
    p.add_argument("--listing", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("check-listing")
    p.add_argument("--listing", type=Path, required=True)
    p.add_argument("--recipe-dir", type=Path, required=True)
    p = sub.add_parser("check-meta")
    p.add_argument("--dictionary", type=Path, required=True)
    p.add_argument("--oedi-page", type=Path, required=True)
    p.add_argument("--recipe-dir", type=Path, required=True)
    p = sub.add_parser("check-file")
    p.add_argument("--path", type=Path, required=True)
    p.add_argument("--size", type=int, required=True)
    p.add_argument("--md5", required=True)
    p = sub.add_parser("validate")
    p.add_argument("--recipe-dir", type=Path, required=True)
    p.add_argument("--download-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("build")
    p.add_argument("--recipe-dir", type=Path, required=True)
    p.add_argument("--download-dir", type=Path, required=True)
    p.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.cmd == "discover":
            discover(args.listing, args.out)
        elif args.cmd == "check-listing":
            check_listing(args.listing, load_sources(args.recipe_dir))
        elif args.cmd == "check-meta":
            check_meta(args.dictionary, args.oedi_page, load_columns(args.recipe_dir))
        elif args.cmd == "check-file":
            check_file(args.path, args.size, args.md5)
        elif args.cmd == "validate":
            validate(args.recipe_dir, args.download_dir, args.out)
        elif args.cmd == "build":
            build(args.recipe_dir, args.download_dir, args.data_root)
    except RecipeError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
