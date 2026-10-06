#!/usr/bin/env python3
"""ExoMol .states energy-column recipe helper (pure standard library).

Subcommands
-----------
discover  Turn locally fetched metadata (exomol.all, .def, .def.json, HEAD
          results) into the pinned recipe tables master_datasets.tsv and
          sources.tsv. Used by discover.sh only.
plan      download.sh step: validate the fetched master file and every .def
          against the pinned tables, re-derive the one-dataset-per-molecule
          selection, fail loudly on any mismatch, and write the download plan.
validate  download.sh step: check every fetched .def.json and .states.bz2
          (exact size, pinned SHA-256 and line count, JSON field layout, full
          bz2 decode, first record with ID 1 and a numeric energy). A line
          count that differs from the .def state count is reported, not
          fatal: build excludes such datasets by the pinned def_count rule.
build     Decode the energy column of every selected .states file, classify
          each dataset against the pinned lattice/ID/negative rules, and emit
          one little-endian float64 sample per kept dataset plus the index.
verify    Independently re-derive everything build produced, with a separate
          integer micro-unit parser, and check the index and manifest.

Network I/O is done by curl in the shell scripts; this file only reads local
files.
"""
from __future__ import annotations

import argparse
import bz2
import decimal
import hashlib
import json
import math
import os
import re
import shutil
import statistics
import struct
import sys
import time
from array import array
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

DATASET_ID = "exomol_state_energy_levels_f64"
SERIES_ID = "exomol_state_energy_cm1_f64"
NATURAL_RECORD_KIND = "exomol_isotopologue_dataset_states_file_energy_column"
DB_BASE = "https://www.exomol.com/db"

MASTER_VERSION = "20260605"
MASTER_SHA256 = "3bc26ed45c5483839ee7a17ce4b135bdd5b2230147b6c261e07102884ffe646c"
MASTER_BYTES = 189391
MASTER_COUNTS = (102, 242, 250)  # molecules, isotopologues, datasets

# Selection rule: per molecule, the first dataset in exomol.all order whose
# .def "No. of states" lies in [MIN_STATES, MAX_STATES].
MIN_STATES = 1_000
MAX_STATES = 5_000_000

# Energy token as written by the declared C format "%12.6f": optional minus,
# 1-6 integer digits, a point and exactly six decimals. %12.6f widens past 12
# characters for values >= 100,000 cm^-1; the six-decimal lattice is what
# matters, so width alone is not a violation.
TOKEN_RE = re.compile(rb"-?[0-9]{1,6}\.[0-9]{6}")
TOKEN_MAX_LEN = 14

# Effective-lattice rule. On a uniform 1e-6 lattice the fraction of tokens
# whose six-digit fraction ends in at least k zeros is p_k = 10**-k. Writing
# c_k for that count over n tokens, the coarse-token share implied by a
# mixture model is q_k = (c_k/n - p_k) / (1 - p_k). A dataset is on the 1e-6
# lattice when, for k = 1, 2, 3,
#     q_k <= LATTICE_Q_MAX + LATTICE_Z * sqrt(p_k (1 - p_k) / n) / (1 - p_k).
LATTICE_P = {1: 0.1, 2: 0.01, 3: 0.001}
LATTICE_Q_MAX = 0.02
LATTICE_Z = 5.0

# Negative energies are kept verbatim; a dataset with more than this share of
# negative tokens would use a different zero-of-energy convention.
NEGATIVE_MAX_FRACTION = 0.01

# Float32-lattice rule. Some line lists were computed in float32 and printed
# with %12.6f, so their effective lattice is the float32 ULP (>= 1.22e-4 at
# |E| >= 1024 cm^-1), not 1e-6. Over valid tokens with |E| >= FLOAT32_MIN_ABS,
# count those equal to the six-decimal print of the float32 nearest to the
# value; genuine 1e-6 values match only by chance (<= ~1%). Exclude when at
# least FLOAT32_MIN_COUNT tokens are eligible and the matching share exceeds
# FLOAT32_SHARE_MAX.
FLOAT32_MIN_ABS = 1024.0
FLOAT32_MIN_COUNT = 100
FLOAT32_SHARE_MAX = 0.05

class RecipeError(Exception):
    """Fatal source-integrity problem raised inside worker processes."""


REASON_ORDER = ("def_count", "token_format", "id_sequence", "lattice", "float32_lattice", "negative_reference")

MASTER_FIELDS = [
    "master_order", "mol_index", "formula", "iso_slug", "dataset",
    "dataset_version", "n_states", "def_url", "def_bytes", "def_sha256",
]
SOURCE_FIELDS = [
    "sample_order", "formula", "molecule_name", "iso_slug", "dataset",
    "dataset_version", "n_states", "doi", "citation_note", "states_url",
    "states_bytes", "states_last_modified", "states_sha256", "states_lines", "defjson_url",
    "defjson_bytes", "defjson_sha256", "expected_status",
]


# ---------------------------------------------------------------- helpers

def log(message: str) -> None:
    print(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] {message}", flush=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_data_root(repo_root: Path, data_dir: str) -> Path:
    path = Path(data_dir)
    return path if path.is_absolute() else repo_root / path


def read_tsv(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    rows = []
    for number, line in enumerate(lines[1:], 2):
        parts = line.split("\t")
        if len(parts) != len(header):
            raise SystemExit(f"{path}:{number}: expected {len(header)} columns, got {len(parts)}")
        rows.append(dict(zip(header, parts)))
    return rows


def write_tsv(path: Path, fields: list[str], rows: list[dict]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(fields) + "\n")
        for row in rows:
            values = [str(row.get(field, "")) for field in fields]
            for value in values:
                if "\t" in value or "\n" in value:
                    raise SystemExit(f"tab/newline in TSV value {value!r}")
            handle.write("\t".join(values) + "\n")
    tmp.replace(path)


def path_formula(formula: str) -> str:
    return formula.replace("+", "_p")


def db_url(formula: str, slug: str, dataset: str, suffix: str) -> str:
    return f"{DB_BASE}/{path_formula(formula)}/{slug}/{dataset}/{slug}__{dataset}{suffix}"


def def_name(slug: str, dataset: str) -> str:
    return f"{slug}__{dataset}.def"


def states_name(slug: str, dataset: str) -> str:
    return f"{slug}__{dataset}.states.bz2"


def sample_name(order: int, slug: str, dataset: str) -> str:
    return f"{order:03d}_{slug}__{dataset}.bin"


# ------------------------------------------------------- metadata parsing

def parse_master(path: Path) -> tuple[str, tuple[int, int, int], list[dict]]:
    rows = []
    for raw in path.read_text(encoding="ascii").splitlines():
        value, _, label = raw.partition("#")
        rows.append((value.strip(), label.strip()))
    if not rows or rows[0][0] != "EXOMOL.master":
        raise SystemExit("exomol.all: missing EXOMOL.master header")
    version = rows[1][0]
    counts = (int(rows[2][0]), int(rows[3][0]), int(rows[4][0]))
    entries: list[dict] = []
    mol_index = -1
    formula = ""
    names: list[str] = []
    current: dict | None = None
    for value, label in rows[5:]:
        if label == "Number of molecule names listed":
            mol_index += 1
            names = []
            formula = ""
        elif label == "Name of the molecule":
            names.append(value)
        elif label == "Molecule chemical formula":
            formula = value
        elif label == "Number of isotopologues considered":
            int(value)
        elif label == "Inchi key of isotopologue":
            current = {
                "master_order": len(entries),
                "mol_index": mol_index,
                "formula": formula,
                "molecule_name": names[0] if names else formula,
                "inchikey": value,
            }
            entries.append(current)
        elif label == "Iso-slug" and current is not None:
            current["iso_slug"] = value
        elif label == "IsoFormula" and current is not None:
            current["iso_formula"] = value
        elif label == "Isotopologue dataset name" and current is not None:
            current["dataset"] = value
        elif label.startswith("Version number") and current is not None:
            current["dataset_version"] = value
        else:
            raise SystemExit(f"exomol.all: unexpected label {label!r}")
    for entry in entries:
        for key in ("iso_slug", "dataset", "dataset_version"):
            if not entry.get(key):
                raise SystemExit(f"exomol.all: entry {entry['master_order']} lacks {key}")
    if mol_index + 1 != counts[0] or len(entries) != counts[2]:
        raise SystemExit(f"exomol.all: header counts {counts} disagree with parsed {mol_index + 1} molecules/{len(entries)} datasets")
    return version, counts, entries


def parse_def(path: Path) -> dict:
    out: dict = {}
    for raw in path.read_text(encoding="utf-8", errors="strict").splitlines():
        value, _, label = raw.partition("#")
        value, label = value.strip(), label.strip()
        if label == "Iso-slug":
            out["iso_slug"] = value
        elif label == "Isotopologue dataset name":
            out["dataset"] = value
        elif label.startswith("Version number") and "version" not in out:
            out["version"] = value
        elif label == "No. of states in .states file":
            number = float(value)
            if not math.isfinite(number) or number != int(number) or number < 0:
                raise SystemExit(f"{path}: bad state count {value!r}")
            out["n_states"] = int(number)
    if not out.get("iso_slug") or "n_states" not in out:
        raise SystemExit(f"{path}: not an ExoMol .def file")
    if not path.read_text(encoding="utf-8").upper().startswith("EXOMOL.DEF"):
        raise SystemExit(f"{path}: missing EXOMOL.def header")
    return out


def parse_defjson(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    dataset = data["dataset"]
    states = dataset["states"]
    fields = states["states_file_fields"]
    if fields[0]["name"] != "ID" or fields[1]["name"] != "E":
        raise SystemExit(f"{path}: first .states columns are not ID, E")
    if fields[1]["ffmt"] != "F12.6" or fields[1]["cfmt"] != "%12.6f":
        raise SystemExit(f"{path}: energy column is not F12.6 ({fields[1]})")
    return {
        "iso_slug": data["isotopologue"]["iso_slug"],
        "dataset": dataset["name"],
        "version": str(dataset["version"]),
        "doi": dataset.get("doi"),
        "n_states": int(states["number_of_states"]),
        "energy_ffmt": fields[1]["ffmt"],
    }


def select(entries: list[dict], counts: dict[int, int]) -> list[dict]:
    chosen: dict[int, dict] = {}
    for entry in entries:
        n = counts[entry["master_order"]]
        if entry["mol_index"] not in chosen and MIN_STATES <= n <= MAX_STATES:
            chosen[entry["mol_index"]] = entry
    return [chosen[key] for key in sorted(chosen)]


# --------------------------------------------------------------- discover

def cmd_selected(args: argparse.Namespace) -> None:
    """Print .def.json and .states.bz2 URLs of the re-derived selection."""
    work = Path(args.work)
    _, _, entries = parse_master(work / "exomol.all")
    counts = {e["master_order"]: parse_def(work / "def" / def_name(e["iso_slug"], e["dataset"]))["n_states"] for e in entries}
    for entry in select(entries, counts):
        for suffix in (".def.json", ".states.bz2"):
            print(db_url(entry["formula"], entry["iso_slug"], entry["dataset"], suffix))


def cmd_discover(args: argparse.Namespace) -> None:
    work = Path(args.work)
    version, counts, entries = parse_master(work / "exomol.all")
    if version != MASTER_VERSION or counts != MASTER_COUNTS:
        raise SystemExit(f"master version/counts {version} {counts} differ from pinned {MASTER_VERSION} {MASTER_COUNTS}")
    heads = {}
    for line in (work / "heads.tsv").read_text().splitlines():
        url, code, size, modified = line.split("\t")
        heads[url] = (code, size, modified)
    previous = {}
    if args.previous and Path(args.previous).is_file():
        for row in read_tsv(Path(args.previous)):
            previous[(row["iso_slug"], row["dataset"])] = row
    master_rows, n_by_order = [], {}
    for entry in entries:
        path = work / "def" / def_name(entry["iso_slug"], entry["dataset"])
        parsed = parse_def(path)
        if (parsed["iso_slug"], parsed["dataset"], parsed["version"]) != (entry["iso_slug"], entry["dataset"], entry["dataset_version"]):
            raise SystemExit(f"{path}: identity {parsed} disagrees with master entry {entry}")
        n_by_order[entry["master_order"]] = parsed["n_states"]
        master_rows.append({
            "master_order": entry["master_order"], "mol_index": entry["mol_index"],
            "formula": entry["formula"], "iso_slug": entry["iso_slug"],
            "dataset": entry["dataset"], "dataset_version": entry["dataset_version"],
            "n_states": parsed["n_states"],
            "def_url": db_url(entry["formula"], entry["iso_slug"], entry["dataset"], ".def"),
            "def_bytes": path.stat().st_size, "def_sha256": sha256_file(path),
        })
    source_rows = []
    for entry in select(entries, n_by_order):
        slug, ds = entry["iso_slug"], entry["dataset"]
        jpath = work / "defjson" / f"{slug}__{ds}.def.json"
        meta = parse_defjson(jpath)
        n = n_by_order[entry["master_order"]]
        if (meta["iso_slug"], meta["dataset"], meta["version"], meta["n_states"]) != (slug, ds, entry["dataset_version"], n):
            raise SystemExit(f"{jpath}: {meta} disagrees with master/.def")
        states_url = db_url(entry["formula"], slug, ds, ".states.bz2")
        code, size, modified = heads[states_url]
        if code != "200" or not size.isdigit():
            raise SystemExit(f"HEAD {states_url}: {code} {size}")
        old = previous.get((slug, ds), {})
        doi = meta["doi"] or ""
        source_rows.append({
            "sample_order": entry["mol_index"], "formula": entry["formula"],
            "molecule_name": entry["molecule_name"], "iso_slug": slug, "dataset": ds,
            "dataset_version": entry["dataset_version"], "n_states": n,
            "doi": doi, "citation_note": old.get("citation_note", ""),
            "states_url": states_url, "states_bytes": size,
            "states_last_modified": modified,
            "states_sha256": old.get("states_sha256", "") if old.get("states_bytes") == size else "",
            "states_lines": old.get("states_lines", "") if old.get("states_bytes") == size else "",
            "defjson_url": db_url(entry["formula"], slug, ds, ".def.json"),
            "defjson_bytes": jpath.stat().st_size, "defjson_sha256": sha256_file(jpath),
            "expected_status": old.get("expected_status", ""),
        })
    write_tsv(Path(args.out_master), MASTER_FIELDS, master_rows)
    write_tsv(Path(args.out_sources), SOURCE_FIELDS, source_rows)
    total = sum(int(row["states_bytes"]) for row in source_rows)
    states = sum(int(row["n_states"]) for row in source_rows)
    log(f"discover: master={version} datasets={len(master_rows)} selected={len(source_rows)} states={states} states_bytes={total}")


# ------------------------------------------------------------------- plan

def cmd_plan(args: argparse.Namespace) -> None:
    recipe = Path(args.recipe)
    meta = Path(args.meta)
    allow_drift = os.environ.get("EXOMOL_ALLOW_METADATA_DRIFT", "0") == "1"
    master_path = meta / "exomol.all"
    actual = sha256_file(master_path)
    version, counts, entries = parse_master(master_path)
    log(f"plan: master version={version} counts={counts} sha256={actual}")
    if actual != MASTER_SHA256 or version != MASTER_VERSION:
        message = f"exomol.all differs from pinned version {MASTER_VERSION} (sha256 {MASTER_SHA256}); got version {version} sha256 {actual}"
        if not allow_drift:
            raise SystemExit("FATAL: " + message + ". Set EXOMOL_ALLOW_METADATA_DRIFT=1 to accept a newer master if the pinned selection still re-derives.")
        log("WARNING: " + message)
    pinned_master = read_tsv(recipe / "master_datasets.tsv")
    pinned_by_key = {(row["iso_slug"], row["dataset"]): row for row in pinned_master}
    if not allow_drift and len(entries) != len(pinned_master):
        raise SystemExit("FATAL: master entry count differs from master_datasets.tsv")
    n_by_order: dict[int, int] = {}
    for entry in entries:
        key = (entry["iso_slug"], entry["dataset"])
        path = meta / "def" / def_name(*key)
        pinned = pinned_by_key.get(key)
        if pinned is None:
            raise SystemExit(f"FATAL: master entry {key} is not in master_datasets.tsv")
        expected_url = db_url(entry["formula"], entry["iso_slug"], entry["dataset"], ".def")
        if expected_url != pinned["def_url"]:
            raise SystemExit(f"FATAL: derived .def URL {expected_url} != pinned {pinned['def_url']}")
        if not path.is_file():
            raise SystemExit(f"FATAL: missing fetched .def {path}")
        parsed = parse_def(path)
        if (parsed["iso_slug"], parsed["dataset"], parsed["version"]) != (entry["iso_slug"], entry["dataset"], entry["dataset_version"]):
            raise SystemExit(f"FATAL: {path} identity {parsed} disagrees with master entry")
        if parsed["n_states"] != int(pinned["n_states"]) or entry["dataset_version"] != pinned["dataset_version"]:
            raise SystemExit(f"FATAL: {key}: .def states/version {parsed['n_states']}/{entry['dataset_version']} != pinned {pinned['n_states']}/{pinned['dataset_version']}")
        if sha256_file(path) != pinned["def_sha256"]:
            if not allow_drift:
                raise SystemExit(f"FATAL: {path} SHA-256 differs from pinned (state count unchanged); set EXOMOL_ALLOW_METADATA_DRIFT=1 to tolerate")
            log(f"WARNING: {path.name} bytes changed upstream but state count/version are unchanged")
        n_by_order[entry["master_order"]] = parsed["n_states"]
    derived = select(entries, n_by_order)
    sources = read_tsv(recipe / "sources.tsv")
    derived_keys = [(e["mol_index"], e["iso_slug"], e["dataset"]) for e in derived]
    pinned_keys = [(int(r["sample_order"]), r["iso_slug"], r["dataset"]) for r in sources]
    if derived_keys != pinned_keys:
        missing = sorted(set(pinned_keys) - set(derived_keys))
        extra = sorted(set(derived_keys) - set(pinned_keys))
        raise SystemExit(f"FATAL: re-derived selection differs from sources.tsv; missing={missing} extra={extra}")
    plan_rows = []
    for entry, row in zip(derived, sources):
        for kind, suffix in (("defjson", ".def.json"), ("states", ".states.bz2")):
            url = db_url(entry["formula"], entry["iso_slug"], entry["dataset"], suffix)
            if url != row[f"{kind}_url"]:
                raise SystemExit(f"FATAL: derived URL {url} != pinned {row[kind + '_url']}")
            plan_rows.append({
                "kind": kind, "filename": f"{entry['iso_slug']}__{entry['dataset']}{suffix}",
                "url": url, "size_bytes": row[f"{kind}_bytes"], "sha256": row[f"{kind}_sha256"],
            })
    write_tsv(Path(args.out), ["kind", "filename", "url", "size_bytes", "sha256"], plan_rows)
    total = sum(int(r["size_bytes"]) for r in plan_rows)
    log(f"plan: selection re-derived ({len(derived)} datasets); plan rows={len(plan_rows)} bytes={total}")


# --------------------------------------------------------------- validate

def _validate_states(task: tuple[str, int, int, str, str]) -> dict:
    path_s, size, n_states, pinned_sha, pinned_lines = task
    path = Path(path_s)
    actual_size = path.stat().st_size
    if actual_size != size:
        return {"file": path.name, "error": f"size {actual_size} != pinned {size}"}
    digest = sha256_file(path)
    if pinned_sha and digest != pinned_sha:
        return {"file": path.name, "error": f"sha256 {digest} != pinned {pinned_sha}"}
    lines = 0
    first = b""
    try:
        with bz2.open(path, "rb") as handle:
            for line in handle:
                if not line.strip():
                    continue
                lines += 1
                if lines == 1:
                    first = line
    except (OSError, EOFError) as exc:
        return {"file": path.name, "error": f"bz2 decode failed: {exc}"}
    parts = first.split()
    try:
        energy_ok = len(parts) >= 4 and parts[0] == b"1" and math.isfinite(float(parts[1]))
    except ValueError:
        energy_ok = False
    if not energy_ok:
        return {"file": path.name, "error": f"first line is not an ExoMol state record: {first[:80]!r}"}
    if pinned_lines and lines != int(pinned_lines):
        return {"file": path.name, "error": f"{lines} state lines != pinned {pinned_lines}"}
    return {"file": path.name, "sha256": digest, "lines": lines, "bytes": actual_size,
            "def_states": n_states, "def_count_match": int(lines == n_states)}


def cmd_validate(args: argparse.Namespace) -> None:
    recipe = Path(args.recipe)
    downloads = Path(args.downloads)
    sources = read_tsv(recipe / "sources.tsv")
    tasks = []
    for row in sources:
        jpath = downloads / "defjson" / f"{row['iso_slug']}__{row['dataset']}.def.json"
        if jpath.stat().st_size != int(row["defjson_bytes"]) or sha256_file(jpath) != row["defjson_sha256"]:
            raise SystemExit(f"FATAL: {jpath.name} size/SHA-256 differs from pinned")
        meta = parse_defjson(jpath)
        if (meta["iso_slug"], meta["dataset"], meta["version"], meta["n_states"]) != (
                row["iso_slug"], row["dataset"], row["dataset_version"], int(row["n_states"])):
            raise SystemExit(f"FATAL: {jpath.name} identity/state count disagrees with sources.tsv")
        spath = downloads / "states" / states_name(row["iso_slug"], row["dataset"])
        tasks.append((str(spath), int(row["states_bytes"]), int(row["n_states"]), row["states_sha256"], row["states_lines"]))
    results = []
    workers = max(1, min(int(args.workers), len(tasks)))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(_validate_states, tasks):
            results.append(result)
            if "error" in result:
                log(f"INVALID {result['file']}: {result['error']}")
            else:
                note = "" if result["def_count_match"] else f" NOTE: differs from .def count {result['def_states']} (build excludes: def_count)"
                log(f"valid {result['file']} bytes={result['bytes']} lines={result['lines']} sha256={result['sha256']}{note}")
    errors = [r for r in results if "error" in r]
    if errors:
        raise SystemExit(f"FATAL: {len(errors)} invalid .states.bz2 payloads")
    write_tsv(Path(args.out), ["file", "bytes", "lines", "def_states", "def_count_match", "sha256"], results)
    unpinned = sum(1 for row in sources if not row["states_sha256"] or not row["states_lines"])
    mismatched = sum(1 for r in results if not r["def_count_match"])
    log(f"validate: {len(results)} .states.bz2 files valid; total_bytes={sum(r['bytes'] for r in results)}; def_count_mismatches={mismatched}; unpinned_sha256_or_lines={unpinned}")


# ------------------------------------------------------------------ build

def lattice_check(n: int, counts: dict[int, int]) -> tuple[bool, dict]:
    detail = {}
    ok = True
    for k, p in LATTICE_P.items():
        q_hat = (counts[k] / n - p) / (1.0 - p)
        limit = LATTICE_Q_MAX + LATTICE_Z * math.sqrt(p * (1.0 - p) / n) / (1.0 - p)
        detail[f"q{k}"] = round(q_hat, 6)
        detail[f"q{k}_limit"] = round(limit, 6)
        if q_hat > limit:
            ok = False
    return ok, detail


def classify(stats: dict) -> str:
    reasons = []
    if not stats["def_count_ok"]:
        reasons.append("def_count")
    if stats["bad_tokens"]:
        reasons.append("token_format")
    if not stats["ids_increasing"]:
        reasons.append("id_sequence")
    if not stats["bad_tokens"]:
        if not stats["lattice_ok"]:
            reasons.append("lattice")
        if stats["f32_eligible"] >= FLOAT32_MIN_COUNT and stats["f32_count"] / stats["f32_eligible"] > FLOAT32_SHARE_MAX:
            reasons.append("float32_lattice")
        if stats["negative"] > NEGATIVE_MAX_FRACTION * stats["n"]:
            reasons.append("negative_reference")
    ordered = [r for r in REASON_ORDER if r in reasons]
    return "keep" if not ordered else "exclude:" + "+".join(ordered)


def scan_states(task: tuple[str, int, str]) -> dict:
    """Parse one .states.bz2; write the float64 energy payload to out_path."""
    path_s, n_expected, out_path = task
    path = Path(path_s)
    values = array("d")
    append = values.append
    match = TOKEN_RE.fullmatch
    n = 0
    blank = 0
    bad = 0
    bad_examples: list[str] = []
    ids_contiguous = True
    ids_increasing = True
    previous_id = 0
    first_id_break = None
    c1 = c2 = c3 = 0
    negative = 0
    f32_eligible = 0
    f32_count = 0
    f32 = struct.Struct("<f")
    with bz2.open(path, "rb") as handle:
        for line in handle:
            parts = line.split(None, 2)
            if not parts:
                blank += 1
                continue
            if len(parts) < 2:
                raise RecipeError(f"{path.name}: malformed line {n + 1}: {line[:80]!r}")
            n += 1
            try:
                state_id = int(parts[0])
            except ValueError:
                raise RecipeError(f"{path.name}: non-integer ID on line {n}: {line[:80]!r}")
            if ids_contiguous and state_id != n:
                ids_contiguous = False
                first_id_break = (n, state_id)
            if state_id <= previous_id:
                ids_increasing = False
            previous_id = state_id
            token = parts[1]
            if len(token) > TOKEN_MAX_LEN or match(token) is None:
                bad += 1
                if len(bad_examples) < 5:
                    bad_examples.append(token.decode("ascii", "replace"))
                continue
            if token[0] == 45:  # '-'
                negative += 1
            if token[-1] == 48:  # '0'
                c1 += 1
                if token[-2] == 48:
                    c2 += 1
                    if token[-3] == 48:
                        c3 += 1
            value = float(token)
            append(value)
            if value >= FLOAT32_MIN_ABS or value <= -FLOAT32_MIN_ABS:
                f32_eligible += 1
                if b"%.6f" % f32.unpack(f32.pack(value))[0] == token:
                    f32_count += 1
    stats = {
        "file": path.name, "n": n, "def_states": n_expected, "def_count_ok": n == n_expected,
        "blank_lines": blank, "bad_tokens": bad,
        "bad_examples": bad_examples, "ids_contiguous": ids_contiguous,
        "ids_increasing": ids_increasing,
        "first_id_break": first_id_break, "negative": negative,
        "c1": c1, "c2": c2, "c3": c3,
        "f32_eligible": f32_eligible, "f32_count": f32_count,
        "f32_share": round(f32_count / f32_eligible, 6) if f32_eligible else 0.0,
    }
    if bad == 0:
        ok, detail = lattice_check(n, {1: c1, 2: c2, 3: c3})
        stats["lattice_ok"] = ok
        stats.update(detail)
        if sys.byteorder != "little":
            values.byteswap()
        payload = values.tobytes()
        stats["sha256"] = hashlib.sha256(payload).hexdigest()
        stats["min"] = min(values)
        stats["max"] = max(values)
        stats["distinct"] = len(set(values))
        Path(out_path).write_bytes(payload)
    else:
        stats["lattice_ok"] = False
    stats["status"] = classify(stats)
    return stats


def cmd_build(args: argparse.Namespace) -> None:
    recipe = Path(args.recipe)
    data_root = Path(args.data_root)
    downloads = data_root / "downloads" / DATASET_ID / "states"
    samples_root = data_root / "samples" / DATASET_ID
    series_dir = samples_root / SERIES_ID
    tmp_dir = samples_root / f".{SERIES_ID}.tmp"
    filtered = data_root / "filtered" / DATASET_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    sources = read_tsv(recipe / "sources.tsv")
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True)
    filtered.mkdir(parents=True, exist_ok=True)
    tasks = []
    for row in sources:
        name = sample_name(int(row["sample_order"]), row["iso_slug"], row["dataset"])
        tasks.append((str(downloads / states_name(row["iso_slug"], row["dataset"])), int(row["n_states"]), str(tmp_dir / name)))
    order = sorted(range(len(tasks)), key=lambda i: -int(sources[i]["states_bytes"]))
    results: dict[int, dict] = {}
    workers = max(1, min(int(args.workers), len(tasks)))
    log(f"build: scanning {len(tasks)} .states files with {workers} workers")
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {i: pool.submit(scan_states, tasks[i]) for i in order}
        for i in sorted(futures):
            try:
                results[i] = futures[i].result()
            except RecipeError as exc:
                raise SystemExit(f"FATAL: {exc}")
    rows, mismatches, unpinned = [], [], []
    classification = []
    for i, row in enumerate(sources):
        stats = results[i]
        expected = row["expected_status"]
        if row["states_lines"] and int(row["states_lines"]) != stats["n"]:
            mismatches.append(f"{stats['file']}: {stats['n']} lines != pinned states_lines {row['states_lines']}")
        if not expected:
            unpinned.append(row["iso_slug"] + "__" + row["dataset"])
        elif expected != stats["status"]:
            mismatches.append(f"{stats['file']}: expected {expected}, realized {stats['status']}")
        classification.append({
            "sample_order": row["sample_order"], "formula": row["formula"],
            "iso_slug": row["iso_slug"], "dataset": row["dataset"], "def_states": row["n_states"],
            "lines": stats["n"], "status": stats["status"], "bad_tokens": stats["bad_tokens"],
            "ids_increasing": int(stats["ids_increasing"]),
            "ids_contiguous": int(stats["ids_contiguous"]), "negative": stats["negative"],
            "frac_tz1": round(stats["c1"] / stats["n"], 6), "frac_tz2": round(stats["c2"] / stats["n"], 6),
            "frac_tz3": round(stats["c3"] / stats["n"], 6),
            "q1": stats.get("q1", ""), "q1_limit": stats.get("q1_limit", ""),
            "q2": stats.get("q2", ""), "q2_limit": stats.get("q2_limit", ""),
            "q3": stats.get("q3", ""), "q3_limit": stats.get("q3_limit", ""),
            "f32_eligible": stats["f32_eligible"], "f32_count": stats["f32_count"],
            "f32_share": stats["f32_share"],
            "bad_examples": ",".join(stats["bad_examples"]),
        })
        sample_tmp = Path(tasks[i][2])
        if stats["status"] != "keep":
            if sample_tmp.exists():
                sample_tmp.unlink()
            continue
        if stats["distinct"] < 2:
            raise SystemExit(f"{stats['file']}: constant energy column")
        size = sample_tmp.stat().st_size
        rows.append({
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "role": "primary",
            "sample_path": f"samples/{DATASET_ID}/{SERIES_ID}/{sample_tmp.name}",
            "numeric_kind": "float", "bit_width": 64, "endianness": "little",
            "element_size_bytes": 8, "sample_size_bytes": size, "value_count": stats["n"],
            "natural_record_kind": NATURAL_RECORD_KIND,
            "sample_order": int(row["sample_order"]), "molecule": row["formula"],
            "molecule_name": row["molecule_name"], "iso_slug": row["iso_slug"],
            "exomol_dataset": row["dataset"], "dataset_version": row["dataset_version"],
            "doi": row["doi"], "source_url": row["states_url"],
            "source_sha256": row["states_sha256"], "min": stats["min"], "max": stats["max"],
            "distinct_values": stats["distinct"], "negative_count": stats["negative"],
            "ids_contiguous": stats["ids_contiguous"], "f32_share": stats["f32_share"],
            "sample_sha256": stats["sha256"],
        })
    write_tsv(filtered / "dataset_classification.tsv", list(classification[0].keys()), classification)
    if mismatches:
        for line in mismatches:
            log("MISMATCH " + line)
        shutil.rmtree(tmp_dir)
        raise SystemExit(f"FATAL: {len(mismatches)} datasets differ from pinned expected_status")
    if series_dir.exists():
        shutil.rmtree(series_dir)
    tmp_dir.replace(series_dir)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.with_suffix(".jsonl.tmp").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    index_path.with_suffix(".jsonl.tmp").replace(index_path)
    counts = [r["value_count"] for r in rows]
    summary = {
        "dataset_id": DATASET_ID, "series_id": SERIES_ID, "candidates": len(sources),
        "kept": len(rows), "excluded": len(sources) - len(rows),
        "total_values": sum(counts), "total_bytes": sum(r["sample_size_bytes"] for r in rows),
        "median_values": statistics.median(counts) if counts else 0,
        "min_values": min(counts) if counts else 0, "max_values": max(counts) if counts else 0,
        "unpinned_expected_status": unpinned,
        "exclusions": {c["iso_slug"] + "__" + c["dataset"]: c["status"] for c in classification if c["status"] != "keep"},
    }
    (filtered / "ingest_stats.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    for c in classification:
        log(f"{c['status']:40s} {c['iso_slug']}__{c['dataset']} lines={c['lines']} def={c['def_states']} tz>=1/2/3={c['frac_tz1']}/{c['frac_tz2']}/{c['frac_tz3']} neg={c['negative']} ids_increasing={c['ids_increasing']} ids_contiguous={c['ids_contiguous']}")
    log(f"build: kept={summary['kept']} excluded={summary['excluded']} values={summary['total_values']} bytes={summary['total_bytes']} median={summary['median_values']}")
    if unpinned:
        log(f"WARNING: {len(unpinned)} datasets have no pinned expected_status; verify will fail until they are pinned")


# ----------------------------------------------------------------- verify

def _verify_one(task: tuple[str, int, str | None]) -> dict:
    """Independent re-derivation: text decode, integer micro-units."""
    path_s, n_expected, sample_s = task
    sample = open(sample_s, "rb").read() if sample_s else None
    if sample is not None and len(sample) != 8 * n_expected:
        return {"error": f"{sample_s}: {len(sample)} bytes != 8 * {n_expected}"}
    stored = struct.iter_unpack("<d", sample) if sample is not None else None
    n = 0
    expected_id = 1
    contiguous = True
    increasing = True
    last_id = 0
    bad = 0
    neg = 0
    zeros = {1: 0, 2: 0, 3: 0}
    f32_eligible = 0
    f32_count = 0
    f32_threshold = int(FLOAT32_MIN_ABS) * 1_000_000
    quantum = decimal.Decimal("0.000001")
    lo, hi = math.inf, -math.inf
    distinct: set[int] = set()
    with bz2.open(path_s, "rt", encoding="ascii", newline=None) as handle:
        for text in handle:
            fields = text.split()
            if not fields:
                continue
            n += 1
            state_id = int(fields[0])
            if state_id != expected_id:
                contiguous = False
            if state_id <= last_id:
                increasing = False
            last_id = state_id
            expected_id += 1
            token = fields[1]
            sign = -1 if token.startswith("-") else 1
            body = token[1:] if sign < 0 else token
            whole, dot, frac = body.partition(".")
            if (dot != "." or len(frac) != 6 or not whole.isdigit()
                    or not frac.isdigit() or not 1 <= len(whole) <= 6):
                bad += 1
                if stored is not None:
                    return {"error": f"{path_s}: kept dataset has malformed token {token!r}"}
                continue
            micro = sign * (int(whole) * 1_000_000 + int(frac))
            if sign < 0:
                neg += 1
            magnitude = abs(micro)
            for k in (1, 2, 3):
                if magnitude % (10 ** k) == 0:
                    zeros[k] += 1
            if magnitude >= f32_threshold:
                f32_eligible += 1
                nearest_f32 = struct.unpack("<f", struct.pack("<f", micro / 1e6))[0]
                printed = decimal.Decimal(nearest_f32).quantize(quantum, rounding=decimal.ROUND_HALF_EVEN)
                if int(printed * 10**6) == micro:
                    f32_count += 1
            if stored is not None:
                (value,) = next(stored)
                if value != micro / 1_000_000 or f"{value:.6f}" != token:
                    return {"error": f"{path_s}: line {n} stored {value!r} != source token {token!r}"}
                distinct.add(micro)
                if value < lo:
                    lo = value
                if value > hi:
                    hi = value
    if sample is not None and n != n_expected:
        return {"error": f"{path_s}: kept dataset has {n} lines != .def count {n_expected}"}
    out = {"n": n, "n_def": n_expected, "contiguous": contiguous, "increasing": increasing, "bad": bad, "neg": neg, "zeros": zeros, "min": lo, "max": hi,
           "f32_eligible": f32_eligible, "f32_count": f32_count,
           "f32_share": round(f32_count / f32_eligible, 6) if f32_eligible else 0.0}
    if sample is not None:
        out["sha256"] = hashlib.sha256(sample).hexdigest()
        out["distinct"] = len(distinct)
    return out


def verify_status(result: dict) -> str:
    reasons = []
    if result["n"] != result["n_def"]:
        reasons.append("def_count")
    if result["bad"]:
        reasons.append("token_format")
    if not result["increasing"]:
        reasons.append("id_sequence")
    if not result["bad"]:
        n = result["n"]
        lattice_bad = False
        for k in (1, 2, 3):
            p = 10.0 ** -k
            excess = result["zeros"][k] / n - p
            if excess > (1.0 - p) * LATTICE_Q_MAX + LATTICE_Z * math.sqrt(p * (1.0 - p) / n):
                lattice_bad = True
        if lattice_bad:
            reasons.append("lattice")
        if result["f32_eligible"] >= FLOAT32_MIN_COUNT and result["f32_count"] > FLOAT32_SHARE_MAX * result["f32_eligible"]:
            reasons.append("float32_lattice")
        if result["neg"] / n > NEGATIVE_MAX_FRACTION:
            reasons.append("negative_reference")
    return "keep" if not reasons else "exclude:" + "+".join(reasons)


def cmd_verify(args: argparse.Namespace) -> None:
    import tomllib

    recipe = Path(args.recipe)
    data_root = Path(args.data_root)
    downloads = data_root / "downloads" / DATASET_ID / "states"
    series_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    sources = read_tsv(recipe / "sources.tsv")
    problems = []
    for row in sources:
        if (not row["expected_status"] or not re.fullmatch(r"[0-9a-f]{64}", row["states_sha256"])
                or not row["states_lines"].isdigit()):
            problems.append(f"{row['iso_slug']}__{row['dataset']}: expected_status/states_sha256/states_lines not pinned")
    if problems:
        raise SystemExit("FATAL: sources.tsv is not fully pinned:\n  " + "\n  ".join(problems))
    index_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_path = {row["sample_path"]: row for row in index_rows}
    if len(by_path) != len(index_rows):
        raise SystemExit("FATAL: duplicate sample paths in index")
    keep_rows = [row for row in sources if row["expected_status"] == "keep"]
    expected_paths = [f"samples/{DATASET_ID}/{SERIES_ID}/" + sample_name(int(r["sample_order"]), r["iso_slug"], r["dataset"]) for r in keep_rows]
    if [row["sample_path"] for row in index_rows] != expected_paths:
        raise SystemExit("FATAL: index rows do not match the pinned kept datasets in sample order")
    on_disk = sorted(p.name for p in series_dir.iterdir())
    if on_disk != sorted(Path(p).name for p in expected_paths):
        raise SystemExit(f"FATAL: sample directory contents differ from index ({len(on_disk)} files)")
    log(f"verify: checking SHA-256 of {len(sources)} downloaded .states.bz2 files")
    for row in sources:
        spath = downloads / states_name(row["iso_slug"], row["dataset"])
        if spath.stat().st_size != int(row["states_bytes"]) or sha256_file(spath) != row["states_sha256"]:
            raise SystemExit(f"FATAL: {spath.name} differs from pinned size/SHA-256")
    tasks = []
    for row in sources:
        sample = None
        if row["expected_status"] == "keep":
            sample = str(data_root / "samples" / DATASET_ID / SERIES_ID / sample_name(int(row["sample_order"]), row["iso_slug"], row["dataset"]))
        tasks.append((str(downloads / states_name(row["iso_slug"], row["dataset"])), int(row["n_states"]), sample))
    workers = max(1, min(int(args.workers), len(tasks)))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_verify_one, tasks))
    errors = [r["error"] for r in results if "error" in r]
    if errors:
        raise SystemExit("FATAL:\n  " + "\n  ".join(errors[:20]))
    totals_values = 0
    totals_bytes = 0
    counts = []
    for row, result in zip(sources, results):
        if result["n"] != int(row["states_lines"]):
            raise SystemExit(f"FATAL: {row['iso_slug']}__{row['dataset']}: {result['n']} lines != pinned states_lines {row['states_lines']}")
        status = verify_status(result)
        if status != row["expected_status"]:
            raise SystemExit(f"FATAL: {row['iso_slug']}__{row['dataset']}: re-derived status {status} != pinned {row['expected_status']}")
        if status != "keep":
            continue
        path = f"samples/{DATASET_ID}/{SERIES_ID}/" + sample_name(int(row["sample_order"]), row["iso_slug"], row["dataset"])
        index = by_path[path]
        checks = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "float", "bit_width": 64,
            "endianness": "little", "element_size_bytes": 8, "value_count": result["n"],
            "sample_size_bytes": 8 * result["n"], "sample_sha256": result["sha256"],
            "source_sha256": row["states_sha256"], "min": result["min"], "max": result["max"],
            "negative_count": result["neg"], "exomol_dataset": row["dataset"], "iso_slug": row["iso_slug"],
            "distinct_values": result["distinct"], "ids_contiguous": result["contiguous"],
            "f32_share": result["f32_share"],
        }
        for key, value in checks.items():
            if index.get(key) != value:
                raise SystemExit(f"FATAL: index {path} field {key}={index.get(key)!r} != {value!r}")
        if not result["max"] > result["min"] or result["distinct"] < 100:
            raise SystemExit(f"FATAL: degenerate sample {path}")
        totals_values += result["n"]
        totals_bytes += 8 * result["n"]
        counts.append(result["n"])
    median = statistics.median(counts)
    if totals_values < 10_000 or median < 1_000 or totals_bytes > 1_000_000_000:
        raise SystemExit(f"FATAL: floors/cap violated: values={totals_values} median={median} bytes={totals_bytes}")
    manifest = tomllib.loads((recipe / "manifest.toml").read_text(encoding="utf-8"))
    primary = [s for s in manifest["series"] if s.get("role") == "primary"]
    if len(primary) != 1 or primary[0]["id"] != SERIES_ID:
        raise SystemExit("FATAL: manifest must declare exactly one primary series")
    if primary[0]["sample_count"] != len(counts) or primary[0]["total_size_bytes"] != totals_bytes:
        raise SystemExit(f"FATAL: manifest sample_count/total_size_bytes {primary[0]['sample_count']}/{primary[0]['total_size_bytes']} != realized {len(counts)}/{totals_bytes}")
    log(f"verify: OK kept={len(counts)} excluded={len(sources) - len(counts)} values={totals_values} bytes={totals_bytes} median={median} min={min(counts)} max={max(counts)}")


# ------------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("discover")
    p.add_argument("--work", required=True)
    p.add_argument("--out-master", required=True)
    p.add_argument("--out-sources", required=True)
    p.add_argument("--previous", default="")
    p = sub.add_parser("selected")
    p.add_argument("--work", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--recipe", required=True)
    p.add_argument("--meta", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("validate")
    p.add_argument("--recipe", required=True)
    p.add_argument("--downloads", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--workers", default=str(min(16, os.cpu_count() or 1)))
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--recipe", required=True)
        p.add_argument("--data-root", required=True)
        p.add_argument("--workers", default=str(min(16, os.cpu_count() or 1)))
    args = parser.parse_args()
    {"discover": cmd_discover, "selected": cmd_selected, "plan": cmd_plan, "validate": cmd_validate,
     "build": cmd_build, "verify": cmd_verify}[args.command](args)


if __name__ == "__main__":
    main()
