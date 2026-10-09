#!/usr/bin/env python3
"""CDRP (cpg0012) CellProfiler per-well profile CSV -> little-endian float64 plate matrices.

Subcommands:
  validate-download  semantic checks on downloaded plate CSVs (header, field counts, plate id)
  build              emit one row-major (well x feature) float64 matrix per plate + index
  verify             independently re-derive every sample and check the index and manifest

Pure standard library. Build parses with the csv module; verify re-parses with plain
str.split so the two paths are independent.
"""
from __future__ import annotations

import argparse
import array
import csv
import hashlib
import json
import math
import re
import struct
import sys
import tomllib
from pathlib import Path

DATASET_ID = "cellpainting_cdrp_cellprofiler_well_profiles_f64"
SERIES_ID = "cdrp_well_profile_features_f64"
EXPECTED_SOURCE_COLUMNS = 4725
EXPECTED_HEADER_SHA256 = "4d3886b4a04cdf47c8e4d11f213d30c0c333ea89544a7be7590d2e1e8617e343"
EXPECTED_KEPT_COLUMNS = 4600
EXPECTED_KEPT_HEADER_SHA256 = "0f6b7a99a9599b5dc880920b5ebf5ba2cf406d702678a30d1d38fe8bc7b64eb4"
# Schema-level exclusions (fixed, never data-dependent): plate/well identifiers and object
# counts, object-number / parent / child bookkeeping, closest-neighbour object IDs, pixel
# centroid locations, and two image-format constants (bit-depth scaling, field pixel area).
EXCLUDE_PATTERNS = (
    r"^Metadata_",
    r"_Number_Object_Number$",
    r"_Parent_",
    r"_Children_.*_Count$",
    r"_Neighbors_(First|Second)ClosestObjectNumber_",
    r"_Location_",
    r"^Image_ImageQuality_Scaling_",
    r"^Image_ImageQuality_TotalArea_",
)
MIN_WELLS = 300  # a 384-well plate; fewer complete rows means a damaged plate
MAX_DROPPED_FRACTION = 0.10
MAX_MODE_FRACTION = 0.50


def load_plates(path: Path) -> list[dict]:
    lines = path.read_text(encoding="ascii").splitlines()
    header = lines[0].split("\t")
    if header != ["plate_id", "size_bytes", "etag", "last_modified", "key"]:
        raise SystemExit(f"unexpected plates.tsv header {header}")
    plates = []
    for line in lines[1:]:
        if not line:
            continue
        p, size, etag, lm, key = line.split("\t")
        if key != f"cpg0012-wawer-bioactivecompoundprofiling/broad/workspace/backend/CDRP/{p}/{p}.csv":
            raise SystemExit(f"plates.tsv key mismatch for plate {p}")
        plates.append({"plate_id": p, "size_bytes": int(size), "etag": etag, "last_modified": lm, "key": key})
    ids = [int(r["plate_id"]) for r in plates]
    if ids != sorted(ids) or len(set(ids)) != len(ids):
        raise SystemExit("plates.tsv must be sorted by unique numeric plate id")
    return plates


def kept_indices(header: list[str]) -> list[int]:
    pats = [re.compile(p) for p in EXCLUDE_PATTERNS]
    return [j for j, name in enumerate(header) if not any(p.search(name) for p in pats)]


def check_header(line: str, plate: str) -> list[str]:
    if hashlib.sha256(line.encode("ascii")).hexdigest() != EXPECTED_HEADER_SHA256:
        raise SystemExit(f"plate {plate}: header does not match pinned CDRP schema")
    header = line.split(",")
    if len(header) != EXPECTED_SOURCE_COLUMNS:
        raise SystemExit(f"plate {plate}: {len(header)} columns != {EXPECTED_SOURCE_COLUMNS}")
    kept = [header[j] for j in kept_indices(header)]
    if len(kept) != EXPECTED_KEPT_COLUMNS or hashlib.sha256(",".join(kept).encode()).hexdigest() != EXPECTED_KEPT_HEADER_SHA256:
        raise SystemExit(f"plate {plate}: kept-column schema mismatch")
    return header


def csv_path(downloads: Path, plate: str) -> Path:
    return downloads / "plates" / f"{plate}.csv"


# ---------------------------------------------------------------- validate-download
def cmd_validate_download(args: argparse.Namespace) -> None:
    plates = load_plates(args.plates)
    selected = [r for r in plates if not args.plate or r["plate_id"] in args.plate]
    for r in selected:
        path = csv_path(args.downloads, r["plate_id"])
        if path.stat().st_size != r["size_bytes"]:
            raise SystemExit(f"plate {r['plate_id']}: size {path.stat().st_size} != pinned {r['size_bytes']}")
        with path.open("r", encoding="ascii", newline="") as fh:
            header_line = fh.readline().rstrip("\n")
            check_header(header_line, r["plate_id"])
            wells = set()
            n = 0
            for line in fh:
                if not line.endswith("\n"):
                    raise SystemExit(f"plate {r['plate_id']}: truncated final line")
                fields = line.rstrip("\n").split(",")
                if len(fields) != EXPECTED_SOURCE_COLUMNS:
                    raise SystemExit(f"plate {r['plate_id']}: row {n + 1} has {len(fields)} fields")
                if fields[0] != r["plate_id"]:
                    raise SystemExit(f"plate {r['plate_id']}: row {n + 1} Metadata_Plate={fields[0]!r}")
                if fields[1] in wells:
                    raise SystemExit(f"plate {r['plate_id']}: duplicate well {fields[1]}")
                wells.add(fields[1])
                n += 1
        if n < MIN_WELLS or n > 384:
            raise SystemExit(f"plate {r['plate_id']}: {n} well rows outside [{MIN_WELLS}, 384]")
        print(f"validated plate={r['plate_id']} wells={n} bytes={r['size_bytes']}")


# ---------------------------------------------------------------- build
def parse_plate_csv(path: Path, plate: str) -> tuple[array.array, int, int, list[str]]:
    """csv-module parse; returns (values, kept_rows, source_rows, dropped_wells)."""
    values = array.array("d")
    dropped: list[str] = []
    rows = 0
    with path.open("r", encoding="ascii", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        check_header(",".join(header), plate)
        idx = kept_indices(header)
        for rec in reader:
            rows += 1
            if len(rec) != EXPECTED_SOURCE_COLUMNS or rec[0] != plate:
                raise SystemExit(f"plate {plate}: malformed row {rows}")
            try:
                row = [float(rec[j]) for j in idx]
            except ValueError:
                dropped.append(rec[1])
                continue
            if not all(math.isfinite(v) for v in row):
                dropped.append(rec[1])
                continue
            values.extend(row)
    kept_rows = rows - len(dropped)
    return values, kept_rows, rows, dropped


def to_le_bytes(values: array.array) -> bytes:
    if sys.byteorder != "little":
        values = array.array("d", values)
        values.byteswap()
    return values.tobytes()


def stored_minmax(values) -> tuple[float, float]:
    return min(values), max(values)


def mode_fraction(values) -> float:
    counts: dict[float, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return max(counts.values()) / len(values)


def sample_rel(plate: str) -> str:
    return f"samples/{DATASET_ID}/{SERIES_ID}/cdrp_plate_{plate}.f64le.bin"


def cmd_build(args: argparse.Namespace) -> None:
    plates = load_plates(args.plates)
    out_dir = args.data_root / "samples" / DATASET_ID / SERIES_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.bin"):
        stale.unlink()
    index_rows = []
    agg = hashlib.sha256()
    total_dropped = 0
    for r in plates:
        plate = r["plate_id"]
        values, kept_rows, source_rows, dropped = parse_plate_csv(csv_path(args.downloads, plate), plate)
        if kept_rows < MIN_WELLS or len(dropped) > MAX_DROPPED_FRACTION * source_rows:
            raise SystemExit(f"plate {plate}: {len(dropped)}/{source_rows} wells dropped for non-finite values; plate rejected")
        if len(values) != kept_rows * EXPECTED_KEPT_COLUMNS:
            raise SystemExit(f"plate {plate}: value count mismatch")
        mf = mode_fraction(values)
        lo, hi = stored_minmax(values)
        if lo == hi or mf > MAX_MODE_FRACTION:
            raise SystemExit(f"plate {plate}: degenerate sample (min={lo} max={hi} mode_fraction={mf:.3f})")
        raw = to_le_bytes(values)
        rel = sample_rel(plate)
        (args.data_root / rel).write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        agg.update(raw)
        total_dropped += len(dropped)
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": rel,
            "numeric_kind": "float",
            "bit_width": 64,
            "endianness": "little",
            "element_size_bytes": 8,
            "sample_size_bytes": len(raw),
            "value_count": len(values),
            "plate_id": plate,
            "shape": [kept_rows, EXPECTED_KEPT_COLUMNS],
            "source_well_rows": source_rows,
            "dropped_wells": dropped,
            "min": lo,
            "max": hi,
            "mode_fraction": round(mf, 6),
            "sha256": digest,
        })
        print(f"built plate={plate} wells={kept_rows}/{source_rows} values={len(values)} bytes={len(raw)} mode_fraction={mf:.4f}", flush=True)
    index_path = args.data_root / "index" / DATASET_ID / "samples.jsonl"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in index_rows), encoding="utf-8")
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(index_rows),
        "total_size_bytes": sum(row["sample_size_bytes"] for row in index_rows),
        "total_values": sum(row["value_count"] for row in index_rows),
        "kept_columns": EXPECTED_KEPT_COLUMNS,
        "exclude_patterns": list(EXCLUDE_PATTERNS),
        "dropped_wells_total": total_dropped,
        "aggregate_sha256": agg.hexdigest(),
    }
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats))


# ---------------------------------------------------------------- verify
def rederive(path: Path, plate: str) -> tuple[bytes, int, int, list[str]]:
    """Independent str.split re-parse with the same missing-value policy (drop well row)."""
    with path.open("r", encoding="ascii", newline="") as fh:
        header = fh.readline().rstrip("\n").split(",")
        check_header(",".join(header), plate)
        names = header
        excl = [re.compile(p) for p in EXCLUDE_PATTERNS]
        keep = [j for j in range(len(names)) if not any(p.search(names[j]) for p in excl)]
        if len(keep) != EXPECTED_KEPT_COLUMNS:
            raise SystemExit("verify: kept column count mismatch")
        packer = struct.Struct("<" + "d" * len(keep))
        chunks = []
        rows = 0
        dropped: list[str] = []
        for line in fh:
            f = line.rstrip("\n").split(",")
            rows += 1
            if len(f) != EXPECTED_SOURCE_COLUMNS or f[0] != plate:
                raise SystemExit(f"verify: plate {plate} malformed row {rows}")
            vals = []
            ok = True
            for j in keep:
                cell = f[j]
                try:
                    v = float(cell)
                except ValueError:
                    ok = False
                    break
                if v != v or v in (math.inf, -math.inf):
                    ok = False
                    break
                vals.append(v)
            if not ok:
                dropped.append(f[1])
                continue
            chunks.append(packer.pack(*vals))
    return b"".join(chunks), rows - len(dropped), rows, dropped


def cmd_verify(args: argparse.Namespace) -> None:
    plates = load_plates(args.plates)
    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1:
        raise SystemExit("verify: manifest must declare exactly one primary series")
    series = series[0]
    index_path = args.data_root / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if [row["plate_id"] for row in rows] != [r["plate_id"] for r in plates]:
        raise SystemExit("verify: index plates differ from pinned plates.tsv")
    out_dir = args.data_root / "samples" / DATASET_ID / SERIES_ID
    on_disk = sorted(p.name for p in out_dir.glob("*.bin"))
    if on_disk != sorted(Path(row["sample_path"]).name for row in rows):
        raise SystemExit("verify: sample directory contains unindexed or missing files")
    agg = hashlib.sha256()
    total = 0
    col_first: list[float] | None = None
    col_varies = [False] * EXPECTED_KEPT_COLUMNS
    for row, r in zip(rows, plates):
        plate = r["plate_id"]
        expected, kept_rows, source_rows, dropped = rederive(csv_path(args.downloads, plate), plate)
        if kept_rows < MIN_WELLS or len(dropped) > MAX_DROPPED_FRACTION * source_rows:
            raise SystemExit(f"verify: plate {plate} drops too many wells")
        actual = (args.data_root / row["sample_path"]).read_bytes()
        if actual != expected:
            raise SystemExit(f"verify: plate {plate} sample bytes differ from independent re-derivation")
        if row["sample_path"] != sample_rel(plate):
            raise SystemExit(f"verify: plate {plate} unexpected sample path")
        n = len(actual) // 8
        checks = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "float", "bit_width": 64,
            "endianness": "little", "element_size_bytes": 8, "sample_size_bytes": len(actual), "value_count": n,
            "shape": [kept_rows, EXPECTED_KEPT_COLUMNS], "source_well_rows": source_rows, "dropped_wells": dropped,
            "sha256": hashlib.sha256(actual).hexdigest(),
        }
        for key, want in checks.items():
            if row.get(key) != want:
                raise SystemExit(f"verify: plate {plate} index field {key}={row.get(key)!r} expected {want!r}")
        vals = struct.unpack(f"<{n}d", actual)
        lo, hi = min(vals), max(vals)
        if (row["min"], row["max"]) != (lo, hi):
            raise SystemExit(f"verify: plate {plate} min/max mismatch")
        if lo == hi:
            raise SystemExit(f"verify: plate {plate} constant sample")
        values_sorted = sorted(vals)
        best = run = 1
        for a, b in zip(values_sorted, values_sorted[1:]):
            run = run + 1 if a == b else 1
            best = max(best, run)
        if best / n > MAX_MODE_FRACTION:
            raise SystemExit(f"verify: plate {plate} dominated by one value ({best / n:.3f})")
        if len(set(vals[: EXPECTED_KEPT_COLUMNS])) < EXPECTED_KEPT_COLUMNS // 4:
            raise SystemExit(f"verify: plate {plate} first well row is structurally degenerate")
        # identical well rows would indicate a broken aggregation
        well_rows = {actual[i * EXPECTED_KEPT_COLUMNS * 8:(i + 1) * EXPECTED_KEPT_COLUMNS * 8] for i in range(kept_rows)}
        if len(well_rows) != kept_rows:
            raise SystemExit(f"verify: plate {plate} has duplicate well rows")
        if col_first is None:
            col_first = list(vals[:EXPECTED_KEPT_COLUMNS])
        for j in range(EXPECTED_KEPT_COLUMNS):
            if not col_varies[j]:
                ref = col_first[j]
                col_varies[j] = any(v != ref for v in vals[j::EXPECTED_KEPT_COLUMNS])
        agg.update(actual)
        total += len(actual)
        print(f"verified plate={plate} wells={kept_rows} dropped={len(dropped)} mode_fraction={best / n:.4f}", flush=True)
    if series["sample_count"] != len(rows) or series["total_size_bytes"] != total:
        raise SystemExit(
            f"verify: manifest sample_count/total_size_bytes {series['sample_count']}/{series['total_size_bytes']} "
            f"!= realized {len(rows)}/{total}"
        )
    stats = json.loads(args.stats.read_text(encoding="utf-8"))
    if stats["aggregate_sha256"] != agg.hexdigest() or stats["total_size_bytes"] != total:
        raise SystemExit("verify: ingest_stats aggregate mismatch")
    constant_cols = col_varies.count(False)
    print(f"columns_constant_across_all_output={constant_cols}/{EXPECTED_KEPT_COLUMNS}")
    if constant_cols > EXPECTED_KEPT_COLUMNS // 20:
        raise SystemExit("verify: more than 5% of feature columns are constant across the whole output")
    print(f"verify ok samples={len(rows)} bytes={total} aggregate_sha256={agg.hexdigest()}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("validate-download", "build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--plates", type=Path, required=True)
        p.add_argument("--downloads", type=Path, required=True)
        if name == "validate-download":
            p.add_argument("--plate", action="append", default=[])
        else:
            p.add_argument("--data-root", type=Path, required=True)
            p.add_argument("--stats", type=Path, required=True)
        if name == "verify":
            p.add_argument("--manifest", type=Path, required=True)
    args = ap.parse_args()
    {"validate-download": cmd_validate_download, "build": cmd_build, "verify": cmd_verify}[args.cmd](args)


if __name__ == "__main__":
    main()
