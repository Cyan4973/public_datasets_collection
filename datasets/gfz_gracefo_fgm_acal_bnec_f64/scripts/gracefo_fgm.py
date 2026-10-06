#!/usr/bin/env python3
"""Validate, build and verify gfz_gracefo_fgm_acal_bnec_f64.

Subcommands
  validate-downloads  semantic check of every downloaded CDF + README (used by download.sh)
  build               decode B_NEC from each pinned daily CDF into one raw <f8 sample per day
  verify              independently re-derive every sample and check index/manifest/policy

Missing-value policy (shared by build and verify): the upstream FILLVAL of
B_NEC is NaN.  Every selected file must span its full UTC day on the exact
1 s CDF_EPOCH lattice: every Timestamp equals midnight + k * 1000 ms with
integer k, strictly increasing, first k = 0, last k = 86399, and at most
MAX_MISSING_EPOCHS lattice epochs absent (upstream simply omits a record; it
is not filled).  Every B_NEC component must be finite (no NaN fill, no
infinities).  The sample is all records present in the file, in order, so
its shape is [86400 - missing, 3]; absent epochs are listed per sample in the
index (missing_epoch_seconds) and nothing is inserted, imputed, dropped or
reordered.  Any other deviation is fatal.  B_FLAG is not used to drop values;
its nonzero count is recorded per sample.
"""
from __future__ import annotations

import argparse
import array
import datetime as dt
import hashlib
import json
import math
import re
import struct
import sys
import tomllib
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cdf3  # noqa: E402

DATASET_ID = "gfz_gracefo_fgm_acal_bnec_f64"
SERIES_ID = "gracefo_fgm_acal_corr_b_nec_f64"
DAY_EPOCHS = 86_400
MAX_MISSING_EPOCHS = 10
N_COMP = 3
EXPECTED_FILES = 64
DOI = "10.5880/GFZ.2.3.2021.002"
KNOWN_NON_V0201_MONTHS = {"2024-12", "2025-02", "2026-05"}
B_MAG_BOUNDS_NT = (5_000.0, 80_000.0)   # decode sanity for |B| at ~490 km altitude
# GFZ disturbance-correction terms published next to B_NEC (FGM frame, nT).
DB_TERMS = ("dB_MTQ_FGM", "dB_XI_FGM", "dB_NY_FGM", "dB_BT_FGM", "dB_ST_FGM", "dB_SA_FGM", "dB_BAT_FGM")
# Realized split, pinned: in these files all seven dB_* arrays are published as
# exactly 0.0 on every record (no disturbance correction present in B_NEC);
# in every other selected file all seven carry nonzero corrections.
ZERO_TERM_DATES = frozenset({
    "20221121", "20230105", "20230219", "20230405", "20230520", "20230704", "20230818", "20231002",
    "20231116", "20231231", "20240214", "20240330", "20240514", "20240628", "20240812", "20240926",
    "20241110",
})
EXPECTED_ZERO_TERM_SAMPLES = 17
EXPECTED_NONZERO_TERM_SAMPLES = 47
RMS_TOL_NT = 1e-3
ROTATION_TOL_NT = 1e-6
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


class RecipeError(RuntimeError):
    pass


def require(cond: bool, message: str) -> None:
    if not cond:
        raise RecipeError(message)


def data_root(repo_root: Path, data_dir: str) -> Path:
    path = Path(data_dir)
    return path if path.is_absolute() else repo_root / path


def read_sources(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    require(header == ["slot", "date", "satellite", "selection", "filename", "size_bytes", "last_modified",
                       "etag", "sha256", "url"], f"unexpected sources.tsv header {header}")
    rows = [dict(zip(header, line.split("\t"))) for line in lines[1:] if line.strip()]
    require(len(rows) == EXPECTED_FILES, f"sources.tsv has {len(rows)} rows, expected {EXPECTED_FILES}")
    seen_dates = set()
    for row in rows:
        name = row["filename"]
        day = row["date"]
        sat = row["satellite"]
        require(name == f"{sat}_OPER_FGM_ACAL_CORR_{day}T000000_{day}T235959_0201.cdf", f"bad source name {name}")
        require(row["url"].endswith(f"/0201/{sat}/ACAL_CORR/{name}"), f"bad url for {name}")
        require(f"{day[:4]}-{day[4:6]}" not in KNOWN_NON_V0201_MONTHS, f"{name} is in a non-v0201 month")
        require(day not in seen_dates, f"two files selected for {day} (tandem near-duplicates)")
        seen_dates.add(day)
        row["size_bytes"] = int(row["size_bytes"])
    return rows


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def day_epoch_ms(day: str) -> float:
    date = dt.date(int(day[:4]), int(day[4:6]), int(day[6:]))
    return float((date.toordinal() + 365) * 86_400_000)  # CDF_EPOCH: ms since 0000-01-01


def open_day(path: Path, row: dict) -> cdf3.CDF:
    """Parse one daily CDF and enforce identity/structure (no value decoding)."""
    cdf = cdf3.CDF(path.read_bytes())
    stem = row["filename"][:-4]
    project = "GRACE-FO1" if row["satellite"] == "GF1" else "GRACE-FO2"
    gattr = cdf.global_attributes
    require(cdf.encoding == 1, f"{stem}: CDF encoding {cdf.encoding}, expected 1 (network)")
    require(gattr.get("TITLE") == [stem], f"{stem}: TITLE attribute {gattr.get('TITLE')}")
    require(gattr.get("Project") == [project], f"{stem}: Project attribute {gattr.get('Project')}")
    require(any(DOI.lower() in str(v).lower() for v in gattr.get("DOI", [])), f"{stem}: DOI attribute missing")
    require(any("CC BY 4.0" in str(v) for v in gattr.get("License", [])), f"{stem}: License attribute missing CC BY 4.0")
    bnec = cdf.variables.get("B_NEC")
    require(bnec is not None, f"{stem}: no B_NEC variable")
    require(bnec.data_type == 45 and bnec.num_elems == 1, f"{stem}: B_NEC is not CDF_DOUBLE")
    require(bnec.dims == [3] and all(bnec.dim_varys), f"{stem}: B_NEC dims {bnec.dims}")
    require(bnec.record_varies and DAY_EPOCHS - 1 - MAX_MISSING_EPOCHS <= bnec.max_rec <= DAY_EPOCHS - 1,
            f"{stem}: B_NEC MaxRec {bnec.max_rec} (more than {MAX_MISSING_EPOCHS} missing epochs)")
    require(bnec.attributes.get("UNITS") == "nT", f"{stem}: B_NEC UNITS {bnec.attributes.get('UNITS')}")
    require(bnec.attributes.get("DEPEND_0") == "Timestamp", f"{stem}: B_NEC DEPEND_0")
    fill = bnec.attributes.get("FILLVAL")
    require(isinstance(fill, float) and math.isnan(fill), f"{stem}: B_NEC FILLVAL {fill!r} is not NaN")
    ts = cdf.variables.get("Timestamp")
    require(ts is not None and ts.data_type == 31, f"{stem}: Timestamp variable")
    for name in ("Timestamp", "B_FGM", "q_NEC_FGM", "B_FLAG"):
        require(name in cdf.variables and cdf.variables[name].max_rec == bnec.max_rec,
                f"{stem}: {name} record count differs from B_NEC")
    return cdf


def record_count(cdf: cdf3.CDF) -> int:
    return cdf.variables["B_NEC"].max_rec + 1


def check_timestamps(cdf: cdf3.CDF, row: dict) -> list[int]:
    """Enforce the 1 s day lattice; return the absent epoch seconds (sorted)."""
    values, _ = cdf.read_values("Timestamp")
    name = row["filename"]
    start = day_epoch_ms(row["date"])
    require(len(values) == record_count(cdf), f"{name}: {len(values)} timestamps")
    seconds = []
    for i, v in enumerate(values):
        k = (v - start) / 1000.0
        require(k == int(k) and 0 <= k < DAY_EPOCHS, f"{name}: Timestamp off the 1 s day lattice at record {i}")
        require(not seconds or k > seconds[-1], f"{name}: Timestamp not strictly increasing at record {i}")
        seconds.append(int(k))
    require(seconds[0] == 0 and seconds[-1] == DAY_EPOCHS - 1, f"{name}: day span {seconds[0]}..{seconds[-1]} s")
    present = set(seconds)
    missing = [s for s in range(DAY_EPOCHS) if s not in present]
    require(len(missing) == DAY_EPOCHS - len(seconds) <= MAX_MISSING_EPOCHS,
            f"{name}: {len(missing)} missing epochs exceeds {MAX_MISSING_EPOCHS}")
    return missing


def check_labels(cdf: cdf3.CDF, row: dict) -> None:
    labels, _ = cdf.read_records("LABELS_BNEC")
    require(labels.split() == [b"Bnorth", b"Beast", b"Bcentre"], f"{row['filename']}: LABELS_BNEC {labels!r}")


def decode_bnec(cdf: cdf3.CDF, row: dict) -> tuple[tuple, bytes, dict]:
    raw_be, stats = cdf.read_records("B_NEC")
    count = record_count(cdf) * N_COMP
    require(len(raw_be) == count * 8, f"{row['filename']}: B_NEC has {len(raw_be)} bytes")
    values = struct.unpack(f">{count}d", raw_be)
    nonfinite = sum(1 for v in values if not math.isfinite(v))
    require(nonfinite == 0, f"{row['filename']}: {nonfinite} non-finite B_NEC values (FILLVAL NaN is fatal)")
    return values, struct.pack(f"<{count}d", *values), stats


def component_stats(values) -> dict:
    out = {}
    for k, name in enumerate(("B_N", "B_E", "B_C")):
        comp = values[k::3]
        lo, hi = min(comp), max(comp)
        require(lo < hi, f"component {name} is constant")
        out[name] = {"min": lo, "max": hi, "distinct": len(set(comp))}
    mags = [math.sqrt(values[i] ** 2 + values[i + 1] ** 2 + values[i + 2] ** 2) for i in range(0, len(values), 3)]
    out["B_magnitude"] = {"min": min(mags), "max": max(mags)}
    return out


def disturbance_terms(cdf: cdf3.CDF, row: dict) -> tuple[bool, float]:
    """Classify the seven dB_* terms: (all identically 0.0, RMS of per-record sum in nT).

    Every term must be CDF_DOUBLE[3] with the B_NEC record count and finite
    values; either all seven are 0.0 on every record or none is all-zero.
    """
    n_val = record_count(cdf) * N_COMP
    arrays = []
    all_zero = {}
    for name in DB_TERMS:
        var = cdf.variables.get(name)
        require(var is not None and var.data_type == 45 and var.dims == [3]
                and var.max_rec == cdf.variables["B_NEC"].max_rec,
                f"{row['filename']}: {name} missing or not CDF_DOUBLE[3] with the B_NEC record count")
        values, _ = cdf.read_values(name)
        require(len(values) == n_val, f"{row['filename']}: {name} has {len(values)} values")
        require(all(math.isfinite(v) for v in values), f"{row['filename']}: {name} has non-finite values")
        all_zero[name] = all(v == 0.0 for v in values)
        arrays.append(values)
    zero_terms = sorted(name for name, flag in all_zero.items() if flag)
    require(len(zero_terms) in (0, len(DB_TERMS)),
            f"{row['filename']}: mixed disturbance-term state, all-zero only for {zero_terms}")
    total_sq = 0.0
    for terms in zip(*arrays):
        s = sum(terms)
        total_sq += s * s
    return len(zero_terms) == len(DB_TERMS), round(math.sqrt(total_sq / n_val), 3)


def float32_exact_count(values) -> int:
    narrowed = array.array("f", values)
    return sum(1 for a, b in zip(narrowed, values) if a == b)


# ---------------------------------------------------------------------------
def readme_months(text: str) -> set[str]:
    """Months named in README 'For <Mon> <YYYY> ...' reprocessing/withdrawal notes."""
    months = set()
    for mon, year in re.findall(r"\bFor ([A-Za-z]{3})[a-z]* (\d{4})", text):
        number = MONTHS.get(mon.lower())
        months.add(f"{year}-{number:02d}" if number else f"{year}-{mon}")
    return months


def cmd_validate_downloads(args) -> int:
    root = data_root(args.repo_root, args.data_dir)
    dl = root / "downloads" / DATASET_ID
    rows = read_sources(args.sources)
    for sat in ("GF1", "GF2"):
        text = (dl / f"README_{sat}.txt").read_text(encoding="utf-8")
        require("License: CC BY 4.0" in text, f"README_{sat}.txt lacks 'License: CC BY 4.0'")
        require(DOI in text, f"README_{sat}.txt lacks DOI {DOI}")
        require("ACAL_CORR:" in text, f"README_{sat}.txt does not describe ACAL_CORR")
        extra = readme_months(text) - KNOWN_NON_V0201_MONTHS
        require(not extra, f"README_{sat}.txt reports reprocessed/withdrawn months {sorted(extra)}; re-run discover.sh")
        print(f"readme_ok satellite={sat} sha256={sha256_file(dl / f'README_{sat}.txt')}")
    ledger = []
    invalid = []
    for row in rows:
        path = dl / "cdf" / row["filename"]
        try:
            require(path.is_file(), f"missing {row['filename']}")
            require(path.stat().st_size == row["size_bytes"], f"{row['filename']}: size {path.stat().st_size} != {row['size_bytes']}")
            digest = sha256_file(path)
            if SHA_RE.match(row["sha256"]):
                require(digest == row["sha256"], f"{row['filename']}: sha256 {digest} != pinned {row['sha256']}")
            cdf = open_day(path, row)
            missing = check_timestamps(cdf, row)
            ledger.append((row["filename"], row["size_bytes"], digest))
            print(f"valid {row['filename']} bytes={row['size_bytes']} sha256={digest} "
                  f"records={record_count(cdf)} missing_epoch_seconds={missing}")
        except (RecipeError, cdf3.CDFError, OSError) as exc:
            invalid.append(row["filename"])
            print(f"INVALID {row['filename']}: {exc}", file=sys.stderr)
            if path.is_file() and args.quarantine:
                path.rename(path.with_name(path.name + ".invalid"))
    with (dl / "download_ledger.tsv").open("w", encoding="utf-8") as fh:
        fh.write("filename\tsize_bytes\tsha256\n")
        for name, size, digest in ledger:
            fh.write(f"{name}\t{size}\t{digest}\n")
    pending = sum(1 for row in rows if not SHA_RE.match(row["sha256"]))
    if pending:
        print(f"note: {pending} sources have sha256=pending; observed digests recorded in download_ledger.tsv")
    if invalid:
        print(f"{len(invalid)} invalid downloads (quarantined as *.invalid)", file=sys.stderr)
        return 1
    print(f"validated_files={len(ledger)} bytes={sum(r[1] for r in ledger)}")
    return 0


def expected_digest(row: dict, ledger: dict[str, str]) -> str:
    if SHA_RE.match(row["sha256"]):
        return row["sha256"]
    require(row["filename"] in ledger, f"{row['filename']}: no pinned sha256 and not in download ledger")
    return ledger[row["filename"]]


def load_ledger(dl: Path) -> dict[str, str]:
    path = dl / "download_ledger.tsv"
    if not path.is_file():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines()[1:]:
        name, _size, digest = line.split("\t")
        out[name] = digest
    return out


def sample_rel(row: dict) -> str:
    return f"samples/{DATASET_ID}/{SERIES_ID}/{row['satellite']}_{row['date']}_B_NEC.f64le.bin"


def cmd_build(args) -> int:
    import selftest_cdf3

    selftest_cdf3.run()
    root = data_root(args.repo_root, args.data_dir)
    dl = root / "downloads" / DATASET_ID
    rows = read_sources(args.sources)
    ledger = load_ledger(dl)
    sample_dir = root / "samples" / DATASET_ID / SERIES_ID
    index_dir = root / "index" / DATASET_ID
    filtered_dir = root / "filtered" / DATASET_ID
    for d in (sample_dir, index_dir, filtered_dir):
        d.mkdir(parents=True, exist_ok=True)
    for stale in sample_dir.glob("*.bin"):
        stale.unlink()
    index_rows = []
    per_file = []
    for row in rows:
        path = dl / "cdf" / row["filename"]
        require(path.is_file(), f"missing local source {path}")
        require(path.stat().st_size == row["size_bytes"], f"{row['filename']}: size mismatch")
        digest = sha256_file(path)
        require(digest == expected_digest(row, ledger), f"{row['filename']}: sha256 mismatch")
        cdf = open_day(path, row)
        missing = check_timestamps(cdf, row)
        check_labels(cdf, row)
        values, sample, stats = decode_bnec(cdf, row)
        n_rec = record_count(cdf)
        n_val = n_rec * N_COMP
        comps = component_stats(values)
        lo_mag, hi_mag = comps["B_magnitude"]["min"], comps["B_magnitude"]["max"]
        require(B_MAG_BOUNDS_NT[0] <= lo_mag and hi_mag <= B_MAG_BOUNDS_NT[1],
                f"{row['filename']}: |B| range {lo_mag}..{hi_mag} nT outside decode sanity bounds")
        distinct = [comps[c]["distinct"] for c in ("B_N", "B_E", "B_C")]
        require(distinct == [n_rec] * N_COMP, f"{row['filename']}: component distinct counts {distinct} != {n_rec}")
        f32_exact = float32_exact_count(values)
        require(f32_exact == 0, f"{row['filename']}: {f32_exact} B_NEC values are exactly representable in float32")
        terms_zero, terms_rms = disturbance_terms(cdf, row)
        require(terms_zero == (row["date"] in ZERO_TERM_DATES),
                f"{row['filename']}: disturbance_terms_zero={terms_zero} disagrees with pinned split")
        require(terms_zero == (terms_rms == 0.0), f"{row['filename']}: disturbance RMS {terms_rms} vs zero class")
        flags, _ = cdf.read_values("B_FLAG")
        flag_nonzero = sum(1 for f in flags if f)
        rel = sample_rel(row)
        (root / rel).write_bytes(sample)
        stored = struct.unpack(f"<{n_val}d", sample)
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": rel,
            "numeric_kind": "float",
            "bit_width": 64,
            "endianness": "little",
            "element_size_bytes": 8,
            "sample_size_bytes": len(sample),
            "value_count": n_val,
            "record_count": n_rec,
            "missing_epoch_seconds": missing,
            "shape": [n_rec, N_COMP],
            "axes": ["utc_second_of_day", "nec_component"],
            "component_order": ["B_N", "B_E", "B_C"],
            "min": min(stored),
            "max": max(stored),
            "sha256": hashlib.sha256(sample).hexdigest(),
            "satellite": row["satellite"],
            "date": row["date"],
            "slot": int(row["slot"]),
            "source_file": row["filename"],
            "source_sha256": digest,
            "b_flag_nonzero": flag_nonzero,
            "disturbance_terms_zero": terms_zero,
            "disturbance_total_rms_nT": terms_rms,
            "component_distinct_counts": distinct,
            "float32_exact_values": f32_exact,
        })
        per_file.append({"file": row["filename"], "satellite": row["satellite"], "date": row["date"],
                         "source_bytes": row["size_bytes"], "uncompressed_cdf_bytes": cdf.container["uncompressed_size"],
                         "records": n_rec, "missing_epoch_seconds": missing,
                         "b_nec_blocks": stats["blocks"], "b_nec_cvvr_blocks": stats["cvvr_blocks"],
                         "components": comps, "b_flag_nonzero": flag_nonzero,
                         "disturbance_terms_zero": terms_zero, "disturbance_total_rms_nT": terms_rms})
        print(f"built {rel} min={min(stored):.3f} max={max(stored):.3f} |B|={lo_mag:.1f}..{hi_mag:.1f} "
              f"records={n_rec} missing={missing} blocks={stats['blocks']} flag_nonzero={flag_nonzero} "
              f"dB_zero={terms_zero} dB_rms={terms_rms}")
    hashes = [r["sha256"] for r in index_rows]
    require(len(set(hashes)) == len(hashes), "duplicate samples")
    n_zero = sum(1 for r in index_rows if r["disturbance_terms_zero"])
    n_nonzero = len(index_rows) - n_zero
    require((n_zero, n_nonzero) == (EXPECTED_ZERO_TERM_SAMPLES, EXPECTED_NONZERO_TERM_SAMPLES),
            f"disturbance-term split {n_zero}/{n_nonzero} != pinned {EXPECTED_ZERO_TERM_SAMPLES}/{EXPECTED_NONZERO_TERM_SAMPLES}")
    require({r["date"] for r in index_rows if r["disturbance_terms_zero"]} == ZERO_TERM_DATES,
            "zero-term dates differ from the pinned list")
    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
        for r in index_rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    summary = {"dataset_id": DATASET_ID, "series_id": SERIES_ID, "samples": len(index_rows),
               "values": sum(r["value_count"] for r in index_rows),
               "bytes": sum(r["sample_size_bytes"] for r in index_rows),
               "samples_with_missing_epochs": sum(1 for r in index_rows if r["missing_epoch_seconds"]),
               "disturbance_terms_zero_samples": n_zero,
               "disturbance_terms_nonzero_samples": n_nonzero,
               "disturbance_total_rms_nT_nonzero_range": [
                   min(r["disturbance_total_rms_nT"] for r in index_rows if not r["disturbance_terms_zero"]),
                   max(r["disturbance_total_rms_nT"] for r in index_rows if not r["disturbance_terms_zero"])],
               "float32_exact_values": sum(r["float32_exact_values"] for r in index_rows),
               "satellites": {s: sum(1 for r in index_rows if r["satellite"] == s) for s in ("GF1", "GF2")},
               "first_date": rows[0]["date"], "last_date": rows[-1]["date"], "files": per_file}
    (filtered_dir / "ingest_stats.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(f"build_ok samples={len(index_rows)} bytes={summary['bytes']} satellites={summary['satellites']} "
          f"disturbance_terms_zero={n_zero} nonzero={n_nonzero}")
    return 0


# ---------------------------------------------------------------------------
def rotate_conj_scalar_last(q, v):
    """Rotate v by the conjugate of the scalar-last unit quaternion q = (x, y, z, w)."""
    x, y, z, w = -q[0], -q[1], -q[2], q[3]
    tx = 2.0 * (y * v[2] - z * v[1])
    ty = 2.0 * (z * v[0] - x * v[2])
    tz = 2.0 * (x * v[1] - y * v[0])
    return (v[0] + w * tx + (y * tz - z * ty),
            v[1] + w * ty + (z * tx - x * tz),
            v[2] + w * tz + (x * ty - y * tx))


def cmd_verify(args) -> int:
    root = data_root(args.repo_root, args.data_dir)
    dl = root / "downloads" / DATASET_ID
    rows = read_sources(args.sources)
    ledger = load_ledger(dl)
    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    require(manifest["dataset_id"] == DATASET_ID, "manifest dataset_id")
    series = {s["id"]: s for s in manifest["series"]}
    require(set(series) == {SERIES_ID}, f"manifest series {sorted(series)}")
    spec = series[SERIES_ID]
    require(spec["role"] == "primary" and spec["numeric_kind"] == "float" and spec["bit_width"] == 64
            and spec["endianness"] == "little", "manifest series typing")
    index_path = root / "index" / DATASET_ID / "samples.jsonl"
    index = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    require(len(index) == len(rows) == spec["sample_count"], f"index rows {len(index)} vs sources {len(rows)} vs manifest {spec['sample_count']}")
    require(sum(r["sample_size_bytes"] for r in index) == spec["total_size_bytes"], "manifest total_size_bytes")
    on_disk = sorted(p.name for p in (root / "samples" / DATASET_ID / SERIES_ID).iterdir())
    require(on_disk == sorted(Path(sample_rel(r)).name for r in rows), "sample directory contents differ from sources")
    hashes = set()
    zero_count = 0
    for row, rec in zip(rows, index):
        rel = sample_rel(row)
        require(rec["sample_path"] == rel and rec["source_file"] == row["filename"], f"index order/path for {rel}")
        path = dl / "cdf" / row["filename"]
        source_digest = sha256_file(path)
        require(source_digest == expected_digest(row, ledger) == rec["source_sha256"], f"{row['filename']}: source sha256")
        cdf = open_day(path, row)
        missing = check_timestamps(cdf, row)
        n_rec = record_count(cdf)
        require(n_rec == DAY_EPOCHS - len(missing), f"{rel}: record count vs missing epochs")
        for key, want in (("dataset_id", DATASET_ID), ("series_id", SERIES_ID), ("numeric_kind", "float"),
                          ("bit_width", 64), ("endianness", "little"), ("element_size_bytes", 8),
                          ("sample_size_bytes", n_rec * N_COMP * 8), ("value_count", n_rec * N_COMP),
                          ("record_count", n_rec), ("shape", [n_rec, N_COMP]),
                          ("missing_epoch_seconds", missing)):
            require(rec[key] == want, f"{rel}: index {key}={rec[key]!r}, expected {want!r}")
        sample = (root / rel).read_bytes()
        require(len(sample) == n_rec * N_COMP * 8, f"{rel}: {len(sample)} bytes")
        digest = hashlib.sha256(sample).hexdigest()
        require(digest == rec["sha256"], f"{rel}: sample sha256 differs from index")
        require(digest not in hashes, f"{rel}: duplicate sample")
        hashes.add(digest)
        # independent re-derivation from the source file
        raw_be, _ = cdf.read_records("B_NEC")
        swapped = array.array("d")
        swapped.frombytes(raw_be)
        if sys.byteorder == "little":
            swapped.byteswap()          # network order -> host (little) order
        else:
            raise RecipeError("verify assumes a little-endian host")
        require(swapped.tobytes() == sample, f"{rel}: re-derived B_NEC bytes differ from sample")
        stored = array.array("d")
        stored.frombytes(sample)
        require(all(math.isfinite(v) for v in stored), f"{rel}: non-finite value")
        require(min(stored) == rec["min"] and max(stored) == rec["max"], f"{rel}: index min/max differ from stored float64")
        distinct = [len(set(stored[k::3])) for k in range(3)]
        require(distinct == rec["component_distinct_counts"] == [n_rec] * N_COMP,
                f"{rel}: component distinct counts {distinct} vs index {rec['component_distinct_counts']}")
        # float32-exact iff the low 29 binary64 mantissa bits are zero (values are far inside float32 range)
        bits = array.array("Q")
        bits.frombytes(sample)
        f32_exact = sum(1 for q in bits if q & ((1 << 29) - 1) == 0)
        require(f32_exact == rec["float32_exact_values"] == 0, f"{rel}: float32-exact count {f32_exact}")
        # disturbance terms: classify from raw bytes and recompute the RMS with exact summation
        term_raw = []
        for name in DB_TERMS:
            raw, _ = cdf.read_records(name)
            require(len(raw) == n_rec * N_COMP * 8, f"{rel}: {name} record count")
            term_raw.append(raw)
        byte_zero = [raw.count(0) == len(raw) for raw in term_raw]
        require(all(byte_zero) or not any(byte_zero), f"{rel}: mixed disturbance-term state")
        terms_zero = all(byte_zero)
        require(terms_zero == rec["disturbance_terms_zero"] == (row["date"] in ZERO_TERM_DATES),
                f"{rel}: disturbance_terms_zero {terms_zero} vs index {rec['disturbance_terms_zero']}")
        term_vals = []
        for raw in term_raw:
            arr = array.array("d")
            arr.frombytes(raw)
            arr.byteswap()
            require(all(math.isfinite(v) for v in arr), f"{rel}: non-finite disturbance term")
            term_vals.append(arr)
        sq = math.fsum(math.fsum(terms) ** 2 for terms in zip(*term_vals))
        rms = math.sqrt(sq / (n_rec * N_COMP))
        require(abs(rms - rec["disturbance_total_rms_nT"]) <= RMS_TOL_NT,
                f"{rel}: disturbance RMS {rms} vs index {rec['disturbance_total_rms_nT']}")
        require(terms_zero == (rms == 0.0), f"{rel}: disturbance RMS {rms} inconsistent with zero class")
        zero_count += terms_zero
        # semantic check: B_NEC == conj(q_NEC_FGM) rotation of B_FGM (fixes variable choice and N,E,C interleave)
        b_fgm, _ = cdf.read_values("B_FGM")
        quat, _ = cdf.read_values("q_NEC_FGM")
        worst = 0.0
        for i in range(0, n_rec, 7):
            r = rotate_conj_scalar_last(quat[4 * i:4 * i + 4], b_fgm[3 * i:3 * i + 3])
            worst = max(worst, abs(r[0] - stored[3 * i]), abs(r[1] - stored[3 * i + 1]), abs(r[2] - stored[3 * i + 2]))
        require(worst <= ROTATION_TOL_NT, f"{rel}: B_NEC vs rotated B_FGM max error {worst} nT")
        mags = [math.sqrt(stored[i] ** 2 + stored[i + 1] ** 2 + stored[i + 2] ** 2) for i in range(0, len(stored), 3)]
        require(B_MAG_BOUNDS_NT[0] <= min(mags) and max(mags) <= B_MAG_BOUNDS_NT[1], f"{rel}: |B| out of bounds")
        print(f"verified {rel} records={n_rec} missing={missing} rotation_err={worst:.2e}nT "
              f"|B|={min(mags):.1f}..{max(mags):.1f} dB_zero={terms_zero} dB_rms={rms:.3f}")
    require((zero_count, len(index) - zero_count) == (EXPECTED_ZERO_TERM_SAMPLES, EXPECTED_NONZERO_TERM_SAMPLES),
            f"disturbance-term split {zero_count}/{len(index) - zero_count}")
    print(f"verify_ok samples={len(index)} bytes={sum(r['sample_size_bytes'] for r in index)} "
          f"disturbance_terms_zero={zero_count} nonzero={len(index) - zero_count}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["validate-downloads", "build", "verify"])
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--data-dir", default=".data")
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--quarantine", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "validate-downloads":
            return cmd_validate_downloads(args)
        if args.command == "build":
            return cmd_build(args)
        require(args.manifest is not None, "verify needs --manifest")
        return cmd_verify(args)
    except (RecipeError, cdf3.CDFError) as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
