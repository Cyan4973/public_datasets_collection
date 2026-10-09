#!/usr/bin/env python3
"""SHOALS-1000T Blue Hill Bay (Digital Coast 8526) per-point GPS time, float64.

Subcommands:
  inspect  header-level semantic validation of downloaded COPC tiles
           (called by download.sh; no point decoding)
  build    decode every tile with tools/laz/laszip.py and copy the 8-byte
           GPS time field (offset 22 of each 30-byte PDRF 6 record) of every
           point, in stored order, into one raw little-endian float64 sample
  verify   re-decode every tile, re-extract the field through a different
           code path, and byte-compare with the samples and the index

Pure standard library. The LAZ decoder is imported from the repository
(tools/laz/laszip.py), not copied.
"""
import argparse
import array
import hashlib
import json
import math
import statistics
import struct
import sys
import tomllib
from pathlib import Path

RECIPE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = RECIPE_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools" / "laz"))
import laszip  # noqa: E402

DATASET_ID = "noaa_shoals1000t_bluehillbay_topobathy_gps_time_f64"
SERIES_ID = "shoals_gps_time_f64"
SOURCE_BASE = "https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/"
RECORD_LENGTH = 30
GPS_OFFSET = 22
EXPECTED_TILES = 92
EXPECTED_POINTS = 25_298_628
# Publisher STAC statistics are rounded to 10 significant digits, i.e. to
# 0.1 s at ~1.83e8 s; allow that rounding plus float summation noise.
STAC_MINMAX_TOL = 0.06
STAC_AVG_TOL = 0.11
# Project acquisition window (2017-06-25 .. 2017-07-05) in adjusted standard
# GPS seconds (GPS seconds minus 1e9); a guard against wrong-epoch decodes.
GPS_WINDOW = (182_000_000.0, 184_000_000.0)
MIN_TOTAL_VALUES = 10_000
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000


def read_sources(path: Path) -> list:
    rows = []
    with path.open(encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        for line in fh:
            if not line.strip():
                continue
            values = line.rstrip("\n").split("\t")
            values += [""] * (len(header) - len(values))
            row = dict(zip(header, values))
            row["size_bytes"] = int(row["size_bytes"])
            row["point_count"] = int(row["point_count"])
            for key in ("stac_gps_min", "stac_gps_max", "stac_gps_avg"):
                row[key] = float(row[key])
            rows.append(row)
    if len(rows) != EXPECTED_TILES:
        raise SystemExit(f"sources.tsv lists {len(rows)} tiles, expected {EXPECTED_TILES}")
    if sum(r["point_count"] for r in rows) != EXPECTED_POINTS:
        raise SystemExit("sources.tsv point counts do not sum to the pinned total")
    if len({r["filename"] for r in rows}) != len(rows):
        raise SystemExit("duplicate filenames in sources.tsv")
    for r in rows:
        if not r["key"].startswith("laz/geoid18/8526/") or not r["filename"].endswith(".copc.laz"):
            raise SystemExit(f"unexpected key {r['key']}")
    return rows


def copc_info(hdr: dict) -> dict:
    for vlr in hdr["vlrs"]:
        if vlr["user_id"] == "copc" and vlr["record_id"] == 1:
            data = vlr["data"]
            if len(data) != 160:
                raise ValueError(f"COPC info VLR has length {len(data)}, expected 160")
            gmin, gmax = struct.unpack_from("<dd", data, 56)
            return {"gpstime_minimum": gmin, "gpstime_maximum": gmax}
    raise ValueError("COPC info VLR (copc/1) not found")


def check_header(path: Path, src: dict) -> dict:
    """Semantic header checks shared by inspect, build and verify."""
    name = src["filename"]
    hdr = laszip.read_header(str(path))
    if hdr["file_size"] != src["size_bytes"]:
        raise ValueError(f"{name}: size {hdr['file_size']} != pinned {src['size_bytes']}")
    if hdr["version"] != "1.4":
        raise ValueError(f"{name}: LAS version {hdr['version']}, expected 1.4")
    if hdr["point_format"] != 6 or not hdr["compressed"]:
        raise ValueError(f"{name}: point format raw {hdr['point_format_raw']}, expected compressed PDRF 6")
    if hdr["point_record_length"] != RECORD_LENGTH:
        raise ValueError(f"{name}: record length {hdr['point_record_length']}, expected 30 (no extra bytes)")
    ge = hdr["global_encoding"]
    if not ge & 1:
        raise ValueError(f"{name}: global_encoding {ge} lacks bit 0 (GPS time is not adjusted standard time)")
    if ge & 0b110:
        raise ValueError(f"{name}: global_encoding {ge} declares waveform data")
    if hdr["point_count"] != src["point_count"]:
        raise ValueError(f"{name}: header point count {hdr['point_count']} != STAC pc:count {src['point_count']}")
    lz = hdr["laszip"]
    items = [(it["type"], it["size"], it["version"]) for it in lz["items"]]
    if lz["compressor"] != 3 or lz["coder"] != 0 or items != [(10, 30, 3)] or not lz["variable_chunks"]:
        raise ValueError(f"{name}: LASzip layout compressor={lz['compressor']} items={items} "
                         f"chunk_size={lz['chunk_size']}, expected layered POINT14 v3 variable chunks")
    info = copc_info(hdr)
    for key in ("gpstime_minimum", "gpstime_maximum"):
        if not GPS_WINDOW[0] <= info[key] <= GPS_WINDOW[1]:
            raise ValueError(f"{name}: COPC {key} {info[key]} outside the 2017 project window")
    return {"hdr": hdr, "copc": info, "global_encoding": ge}


def decode_build_path(path: Path, hdr: dict) -> tuple:
    """Build extraction: strided byte slices of each decoded chunk."""
    parts = []
    channels = set()
    chunks = 0
    for _, n, recs in laszip.iter_chunks(str(path), header=hdr):
        parts.append(b"".join([recs[o:o + 8] for o in range(GPS_OFFSET, n * RECORD_LENGTH, RECORD_LENGTH)]))
        channels.update({(b >> 4) & 3 for b in recs[15::RECORD_LENGTH]})
        chunks += 1
    return b"".join(parts), sorted(channels), chunks


def decode_verify_path(path: Path, hdr: dict) -> bytes:
    """Verify extraction: struct.iter_unpack over whole records."""
    values = array.array("d")
    for _, _, recs in laszip.iter_chunks(str(path), header=hdr):
        values.extend(t[0] for t in struct.iter_unpack("<22xd", recs))
    if sys.byteorder != "little":
        values.byteswap()
    return values.tobytes()


def series_checks(name: str, raw: bytes, src: dict, info: dict) -> dict:
    """Content checks applied identically by build and verify."""
    n = len(raw) // 8
    if len(raw) % 8 or n != src["point_count"]:
        raise ValueError(f"{name}: decoded {n} values, expected {src['point_count']}")
    vals = array.array("d")
    vals.frombytes(raw)
    if sys.byteorder != "little":
        vals.byteswap()
    if not all(math.isfinite(v) for v in vals):
        raise ValueError(f"{name}: non-finite GPS time")
    vmin, vmax = min(vals), max(vals)
    # COPC info VLR stores the exact gpstime extent of the file: a decoder
    # desync in the GPS-time layer would not reproduce it bit for bit.
    if vmin != info["gpstime_minimum"] or vmax != info["gpstime_maximum"]:
        raise ValueError(f"{name}: decoded GPS extent {vmin!r}..{vmax!r} != COPC info "
                         f"{info['gpstime_minimum']!r}..{info['gpstime_maximum']!r}")
    avg = math.fsum(vals) / n
    if (abs(vmin - src["stac_gps_min"]) > STAC_MINMAX_TOL or abs(vmax - src["stac_gps_max"]) > STAC_MINMAX_TOL
            or abs(avg - src["stac_gps_avg"]) > STAC_AVG_TOL):
        raise ValueError(f"{name}: GPS min/max/avg {vmin}/{vmax}/{avg} disagree with STAC "
                         f"{src['stac_gps_min']}/{src['stac_gps_max']}/{src['stac_gps_avg']}")
    distinct = len(set(raw[i:i + 8] for i in range(0, len(raw), 8)))
    if distinct < 2 or vmin == vmax:
        raise ValueError(f"{name}: constant GPS-time series")
    neg = zero = 0
    prev = vals[0]
    for v in vals[1:] if n > 1 else []:
        if v < prev:
            neg += 1
        elif v == prev:
            zero += 1
        prev = v
    return {"value_count": n, "min": vmin, "max": vmax, "mean": avg, "distinct_values": distinct,
            "backward_steps": neg, "repeat_steps": zero}


def sample_relpath(src: dict) -> str:
    stem = src["filename"][: -len(".copc.laz")]
    return f"samples/{DATASET_ID}/{SERIES_ID}/{stem}_gps_time_f64.bin"


def cmd_inspect(args) -> int:
    sources = read_sources(Path(args.sources))
    ges = {}
    for src in sources:
        info = check_header(Path(args.download_dir) / src["filename"], src)
        ges[info["global_encoding"]] = ges.get(info["global_encoding"], 0) + 1
    print(f"inspect ok tiles={len(sources)} points={sum(s['point_count'] for s in sources)} "
          f"global_encoding={ges}")
    return 0


def cmd_build(args) -> int:
    data_root = Path(args.data_root)
    sources = read_sources(Path(args.sources))
    out_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.bin"):
        stale.unlink()
    rows, per_tile = [], []
    for i, src in enumerate(sources, 1):
        path = Path(args.download_dir) / src["filename"]
        h = check_header(path, src)
        raw, channels, chunks = decode_build_path(path, h["hdr"])
        metrics = series_checks(src["filename"], raw, src, h["copc"])
        rel = sample_relpath(src)
        out = data_root / rel
        tmp = out.with_suffix(".bin.part")
        tmp.write_bytes(raw)
        tmp.replace(out)
        if out.stat().st_size != len(raw):
            raise ValueError(f"{rel}: output size mismatch")
        row = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": rel,
            "numeric_kind": "float",
            "bit_width": 64,
            "endianness": "little",
            "element_size_bytes": 8,
            "sample_size_bytes": len(raw),
            "value_count": metrics["value_count"],
            "sample_format": "raw homogeneous float64 LAS GPS-time array",
            "sample_geometry": "las_point_attribute_stream",
            "sample_rank": 1,
            "sample_shape": [metrics["value_count"]],
            "sample_axes": ["point"],
            "natural_record_kind": "copc_laz_tile",
            "source_format": "LAS 1.4 PDRF 6 (COPC, LASzip layered POINT14 v3)",
            "source_field": "GPS Time",
            "source_file": src["filename"],
            "source_url": SOURCE_BASE + src["key"],
            "source_bytes": src["size_bytes"],
            "source_md5": src["md5"],
            "global_encoding": h["global_encoding"],
            "scanner_channels": channels,
            "copc_chunks": chunks,
            "min": metrics["min"],
            "max": metrics["max"],
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        rows.append(row)
        per_tile.append({"source_file": src["filename"], "copc_chunks": chunks,
                         "scanner_channels": channels, **metrics})
        print(f"[{i}/{len(sources)}] {src['filename']} points={metrics['value_count']} chunks={chunks} "
              f"channels={channels} backward_steps={metrics['backward_steps']} "
              f"repeat_steps={metrics['repeat_steps']} distinct={metrics['distinct_values']}", flush=True)
    counts = [r["value_count"] for r in rows]
    total_values, total_bytes = sum(counts), sum(r["sample_size_bytes"] for r in rows)
    median = statistics.median(counts)
    if total_values < MIN_TOTAL_VALUES or median < MIN_MEDIAN_VALUES:
        raise ValueError(f"below floor: values={total_values} median={median}")
    if total_bytes > MAX_PRIMARY_BYTES:
        raise ValueError(f"primary bytes {total_bytes} exceed cap")
    index = data_root / "index" / DATASET_ID / "samples.jsonl"
    index.parent.mkdir(parents=True, exist_ok=True)
    with index.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    agg = hashlib.sha256()
    for row in rows:
        agg.update(bytes.fromhex(row["sha256"]))
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(rows),
        "primary_values": total_values,
        "primary_bytes": total_bytes,
        "median_sample_values": median,
        "min_sample_values": min(counts),
        "max_sample_values": max(counts),
        "samples_under_1000_values": sum(1 for c in counts if c < 1000),
        "global_min": min(r["min"] for r in rows),
        "global_max": max(r["max"] for r in rows),
        "backward_steps_total": sum(t["backward_steps"] for t in per_tile),
        "repeat_steps_total": sum(t["repeat_steps"] for t in per_tile),
        "sha256_of_sample_sha256s": agg.hexdigest(),
        "tiles": per_tile,
    }
    stats_path.write_text(json.dumps(stats, indent=1) + "\n", encoding="utf-8")
    print(f"build ok samples={len(rows)} values={total_values} bytes={total_bytes} median={median} "
          f"min_values={min(counts)} under_1000={stats['samples_under_1000_values']} "
          f"aggregate_sha256={agg.hexdigest()}")
    return 0


def cmd_verify(args) -> int:
    data_root = Path(args.data_root)
    sources = read_sources(Path(args.sources))
    manifest = tomllib.loads((RECIPE_DIR / "manifest.toml").read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1 or series[0].get("role") != "primary":
        raise ValueError("manifest must declare exactly one primary series " + SERIES_ID)
    series = series[0]
    index = data_root / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_file = {r["source_file"]: r for r in rows}
    if len(rows) != len(sources) or set(by_file) != {s["filename"] for s in sources}:
        raise ValueError(f"index has {len(rows)} rows; expected one per pinned tile ({len(sources)})")
    on_disk = sorted(p.name for p in (data_root / "samples" / DATASET_ID / SERIES_ID).glob("*"))
    expected_names = sorted(Path(sample_relpath(s)).name for s in sources)
    if on_disk != expected_names:
        raise ValueError("sample directory content differs from the pinned tile list")
    total_values = total_bytes = 0
    counts = []
    for i, src in enumerate(sources, 1):
        name = src["filename"]
        row = by_file[name]
        rel = sample_relpath(src)
        expect = {"dataset_id": DATASET_ID, "series_id": SERIES_ID, "sample_path": rel,
                  "numeric_kind": "float", "bit_width": 64, "endianness": "little",
                  "element_size_bytes": 8, "role": "primary"}
        for key, value in expect.items():
            if row.get(key) != value:
                raise ValueError(f"{name}: index {key}={row.get(key)!r}, expected {value!r}")
        path = Path(args.download_dir) / name
        if len(src.get("sha256", "")) != 64:
            raise ValueError(f"{name}: sources.tsv has no pinned SHA-256")
        if hashlib.sha256(path.read_bytes()).hexdigest() != src["sha256"]:
            raise ValueError(f"{name}: tile SHA-256 differs from the pinned value")
        h = check_header(path, src)
        raw = decode_verify_path(path, h["hdr"])
        metrics = series_checks(name, raw, src, h["copc"])
        stored = (data_root / rel).read_bytes()
        if stored != raw:
            raise ValueError(f"{name}: stored sample differs from the re-extracted GPS-time field")
        if row["value_count"] != metrics["value_count"] or row["sample_size_bytes"] != len(stored):
            raise ValueError(f"{name}: index counts disagree with the sample")
        if row["sha256"] != hashlib.sha256(stored).hexdigest():
            raise ValueError(f"{name}: sample sha256 mismatch")
        if row["min"] != metrics["min"] or row["max"] != metrics["max"]:
            raise ValueError(f"{name}: index min/max disagree with stored float64 values")
        total_values += metrics["value_count"]
        total_bytes += len(stored)
        counts.append(metrics["value_count"])
        print(f"[{i}/{len(sources)}] verified {name} values={metrics['value_count']}", flush=True)
    if series["sample_count"] != len(rows) or series["total_size_bytes"] != total_bytes:
        raise ValueError(f"manifest sample_count/total_size_bytes {series['sample_count']}/"
                         f"{series['total_size_bytes']} != realized {len(rows)}/{total_bytes}")
    median = statistics.median(counts)
    if total_values < MIN_TOTAL_VALUES or median < MIN_MEDIAN_VALUES or total_bytes > MAX_PRIMARY_BYTES:
        raise ValueError(f"floor/cap failure values={total_values} median={median} bytes={total_bytes}")
    print(f"verify ok samples={len(rows)} values={total_values} bytes={total_bytes} median={median}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("inspect", "build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--sources", default=str(RECIPE_DIR / "sources.tsv"))
        p.add_argument("--download-dir", required=True)
        if name != "inspect":
            p.add_argument("--data-root", required=True)
    args = parser.parse_args()
    return {"inspect": cmd_inspect, "build": cmd_build, "verify": cmd_verify}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
