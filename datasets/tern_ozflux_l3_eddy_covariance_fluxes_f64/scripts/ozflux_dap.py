#!/usr/bin/env python3
"""OzFlux L3 OPeNDAP helpers: payload validation (download) and sample build.

Subcommands:
  check-meta  <dds> <das> <expected_time_length>
  check-dods  <dods> <var> <expected_time_length> <url_path>
  build       --recipe-dir --data-root

Pure standard library. An OPeNDAP DAP2 binary (.dods) response for a single
Grid array projection `?V.V` is: a DDS text header naming
`Structure { Float64 V[time = N][latitude = 1][longitude = 1]; } V;`, the
literal separator "\\nData:\\n", two big-endian uint32 XDR array-length words
(both equal N for a 1-D-equivalent array), then N big-endian IEEE-754 float64
values. Nothing follows the last value.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import sys
from pathlib import Path

DATASET_ID = "tern_ozflux_l3_eddy_covariance_fluxes_f64"
VARIABLES = {
    # source variable -> (series id, units, valid_range declared in DAS)
    "Fco2": ("ozflux_l3_fco2_f64", "umol/m^2/s"),
    "Fe": ("ozflux_l3_fe_f64", "W/m^2"),
    "Fh": ("ozflux_l3_fh_f64", "W/m^2"),
}
FILL = -9999.0
NC_DEFAULT_FILL = 9.969209968386869e36
ABS_LIMIT = 1.0e5  # finite non-fill values beyond this are structural corruption
MIN_VALID = 1000  # (file, variable) pairs with fewer valid values are skipped
SEPARATOR = b"\nData:\n"


def read_files_tsv(recipe_dir: Path) -> list[dict]:
    rows = []
    for line in (recipe_dir / "files.tsv").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        site, release, name, path, length, step = line.split("\t")
        if not name.endswith(".nc") or step != "30":
            raise SystemExit(f"bad files.tsv row: {line!r}")
        rows.append({"site": site, "release": release, "file_name": name, "url_path": path,
                     "stem": name[:-3], "time_length": int(length)})
    return rows


def is_missing(value: float) -> bool:
    return value == FILL or not math.isfinite(value) or value == NC_DEFAULT_FILL


def decode_dods(payload: bytes, var: str, expected: int, url_path: str | None = None) -> tuple:
    """Validate a .dods projection payload and return the big-endian float64 tuple."""
    cut = payload.find(SEPARATOR)
    if cut < 0:
        head = payload[:200].decode("latin-1", "replace")
        raise ValueError(f"no DAP2 Data separator (error response?): {head!r}")
    dds = payload[:cut].decode("ascii", "strict")
    if not dds.lstrip().startswith("Dataset {"):
        raise ValueError("DDS header does not start with 'Dataset {'")
    decl = re.findall(r"\b(\w+) (\w+)\[time = (\d+)\]\[latitude = (\d+)\]\[longitude = (\d+)\];", dds)
    if decl != [("Float64", var, str(expected), "1", "1")]:
        raise ValueError(f"unexpected DDS declarations for {var}: {decl}")
    if not re.search(r"\}\s*" + re.escape(var) + r";", dds):
        raise ValueError(f"DDS lacks the {var} structure terminator")
    if url_path is not None and not dds.rstrip().endswith(f"}} {url_path};"):
        raise ValueError("DDS dataset name does not match the requested url path")
    start = cut + len(SEPARATOR)
    if len(payload) < start + 8:
        raise ValueError("truncated before XDR length words")
    n1, n2 = struct.unpack_from(">II", payload, start)
    if n1 != n2 or n1 != expected:
        raise ValueError(f"XDR length words {n1},{n2} != expected {expected}")
    body = start + 8
    if len(payload) != body + 8 * n1:
        raise ValueError(f"payload length {len(payload)} != {body + 8 * n1}")
    return struct.unpack_from(f">{n1}d", payload, body)


def check_meta(dds_path: Path, das_path: Path, expected: int) -> None:
    dds = dds_path.read_text(encoding="ascii")
    das = das_path.read_text(encoding="utf-8", errors="replace")
    if not re.search(rf"Float64 time\[time = {expected}\];", dds):
        raise SystemExit(f"{dds_path.name}: time length changed (expected {expected})")
    for var, (_, units) in VARIABLES.items():
        if not re.search(rf"Float64 {var}\[time = {expected}\]\[latitude = 1\]\[longitude = 1\];", dds):
            raise SystemExit(f"{dds_path.name}: {var} is not Float64[time={expected}][1][1]")
        block = re.search(r"\n    " + var + r" \{(.*?)\n    \}", das, re.S)
        if not block or f'units "{units}"' not in block.group(1):
            raise SystemExit(f"{das_path.name}: {var} units are not {units!r}")
        fill = re.search(r"_FillValue ([^;]*);", block.group(1))
        if fill and float(fill.group(1)) != FILL:
            raise SystemExit(f"{das_path.name}: {var} _FillValue {fill.group(1)} != -9999.0")
    if 'license_name "CC BY 4.0"' not in das or 'license "https://creativecommons.org/licenses/by/4.0/"' not in das:
        raise SystemExit(f"{das_path.name}: license is no longer CC BY 4.0")
    step = re.search(r'time_step "?([^";\n]+)"?;', das)
    if not step or step.group(1).strip() != "30":
        raise SystemExit(f"{das_path.name}: time_step is not 30 minutes")
    if 'processing_level "L3"' not in das:
        raise SystemExit(f"{das_path.name}: processing_level is not L3")
    print(f"meta_ok {dds_path.name[:-4]} time={expected}")


def check_dods(path: Path, var: str, expected: int, url_path: str) -> None:
    values = decode_dods(path.read_bytes(), var, expected, url_path)
    valid = [v for v in values if not is_missing(v)]
    big = sum(1 for v in valid if abs(v) > ABS_LIMIT)
    if big:
        raise SystemExit(f"{path.name}: {big} non-fill values exceed |{ABS_LIMIT:g}|")
    print(f"dods_ok {path.name} n={len(values)} valid={len(valid)}")


def fill_runs(values: tuple) -> list[list[int]]:
    runs: list[list[int]] = []
    for i, v in enumerate(values):
        if is_missing(v):
            if runs and runs[-1][0] + runs[-1][1] == i:
                runs[-1][1] += 1
            else:
                runs.append([i, 1])
    return runs


def build(recipe_dir: Path, data_root: Path) -> None:
    rows = read_files_tsv(recipe_dir)
    downloads = data_root / "downloads" / DATASET_ID
    samples_root = data_root / "samples" / DATASET_ID
    filtered = data_root / "filtered" / DATASET_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    for d in (samples_root, filtered / "gaps", index_path.parent):
        d.mkdir(parents=True, exist_ok=True)
    for old in samples_root.glob("*/*.f64"):
        old.unlink()
    index_rows = []
    stats = {"dataset_id": DATASET_ID, "files": len(rows), "series": {}, "skipped": []}
    for var, (series_id, units) in VARIABLES.items():
        (samples_root / series_id).mkdir(parents=True, exist_ok=True)
        (filtered / "gaps" / series_id).mkdir(parents=True, exist_ok=True)
        s = {"units": units, "samples": 0, "values": 0, "bytes": 0, "time_steps": 0,
             "fill_or_nonfinite": 0, "sha256_concat": None}
        concat = hashlib.sha256()
        for row in rows:
            src = downloads / row["site"] / f"{row['stem']}.{var}.dods"
            values = decode_dods(src.read_bytes(), var, row["time_length"], row["url_path"])
            valid = [v for v in values if not is_missing(v)]
            runs = fill_runs(values)
            s["time_steps"] += len(values)
            s["fill_or_nonfinite"] += len(values) - len(valid)
            if any(abs(v) > ABS_LIMIT for v in valid):
                raise SystemExit(f"{src}: non-fill value beyond |{ABS_LIMIT:g}|")
            if len(valid) < MIN_VALID:
                stats["skipped"].append({"series_id": series_id, "file": row["file_name"], "valid": len(valid)})
                continue
            if min(valid) == max(valid):
                raise SystemExit(f"{src}: constant valid series")
            raw = struct.pack(f"<{len(valid)}d", *valid)
            out = samples_root / series_id / f"{row['stem']}.f64"
            out.write_bytes(raw)
            concat.update(raw)
            gaps = {"file": row["file_name"], "url_path": row["url_path"], "time_length": len(values),
                    "fill_runs": runs}
            (filtered / "gaps" / series_id / f"{row['stem']}.json").write_text(json.dumps(gaps), encoding="utf-8")
            index_rows.append({
                "dataset_id": DATASET_ID, "series_id": series_id,
                "sample_path": str(out.relative_to(data_root)),
                "numeric_kind": "float", "bit_width": 64, "endianness": "little",
                "element_size_bytes": 8, "sample_size_bytes": len(raw), "value_count": len(valid),
                "site": row["site"], "release": row["release"], "source_file": row["file_name"],
                "source_variable": var, "units": units, "time_length": len(values),
                "fill_count": len(values) - len(valid), "min": min(valid), "max": max(valid),
                "sha256": hashlib.sha256(raw).hexdigest(),
            })
            s["samples"] += 1
            s["values"] += len(valid)
            s["bytes"] += len(raw)
        s["sha256_concat"] = concat.hexdigest()
        stats["series"][series_id] = s
        print(f"series {series_id}: samples={s['samples']} values={s['values']} bytes={s['bytes']} "
              f"fill_share={s['fill_or_nonfinite'] / max(1, s['time_steps']):.4f}")
    with index_path.open("w", encoding="utf-8") as handle:
        for r in index_rows:
            handle.write(json.dumps(r, sort_keys=True) + "\n")
    (filtered / "ingest_stats.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")
    print(f"index rows={len(index_rows)} skipped={len(stats['skipped'])}")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check-meta"); p.add_argument("dds"); p.add_argument("das"); p.add_argument("n", type=int)
    p = sub.add_parser("check-dods"); p.add_argument("dods"); p.add_argument("var"); p.add_argument("n", type=int); p.add_argument("url_path")
    p = sub.add_parser("build"); p.add_argument("--recipe-dir", required=True); p.add_argument("--data-root", required=True)
    a = parser.parse_args()
    try:
        if a.cmd == "check-meta":
            check_meta(Path(a.dds), Path(a.das), a.n)
        elif a.cmd == "check-dods":
            if a.var not in VARIABLES:
                raise SystemExit(f"unknown variable {a.var}")
            check_dods(Path(a.dods), a.var, a.n, a.url_path)
        else:
            build(Path(a.recipe_dir), Path(a.data_root))
    except ValueError as exc:
        raise SystemExit(f"FATAL: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
