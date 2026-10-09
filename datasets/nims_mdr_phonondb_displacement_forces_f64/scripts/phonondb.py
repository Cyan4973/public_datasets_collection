#!/usr/bin/env python3
"""Build / verify the NIMS MDR phonon-database supercell force samples.

Source: phonopy_params.yaml.xz (one per material) from the MDR phonon calculation
database (A. Togo, NIMS), CC BY 4.0.  Primary payload: the `forces:` vectors of
every entry of the top-level `displacements:` block, flattened in file order
(displacement-major, then supercell atom, then x/y/z) and stored as
little-endian IEEE-754 float64 parsed from the decimal text.

Two independent parsers are used:
  * build  -> line state machine (parse_forces_lines)
  * verify -> block-level regex over the displacements section (parse_forces_regex)
verify recomputes every sample from the downloaded .xz and compares bytes.
"""
import argparse
import hashlib
import json
import lzma
import math
import os
import re
import struct
import sys
from decimal import Decimal

DATASET_ID = "nims_mdr_phonondb_displacement_forces_f64"
SERIES_ID = "phonopy_supercell_forces_f64"
NUM = r"-?\d+\.\d+(?:[eE][-+]?\d+)?"
VEC_RE = re.compile(r"^\s*-\s*\[\s*(" + NUM + r")\s*,\s*(" + NUM + r")\s*,\s*(" + NUM + r")\s*\]\s*$")
TOKEN_RE = re.compile(NUM)
Q8 = Decimal("0.00000001")


class ParseError(Exception):
    pass


def read_sources(path):
    rows = []
    with open(path) as f:
        header = f.readline().rstrip("\n").split("\t")
        assert header == ["dataset_id", "mp_id", "fileset_id", "size_bytes", "md5"], header
        for line in f:
            if not line.strip():
                continue
            ds, mp, fs, size, md5 = line.rstrip("\n").split("\t")
            rows.append({"dataset_id": ds, "mp_id": mp, "fileset_id": fs,
                         "size_bytes": int(size), "md5": md5})
    ids = [r["dataset_id"] for r in rows]
    if ids != sorted(ids) or len(set(ids)) != len(ids):
        raise SystemExit("sources.tsv must be sorted by unique dataset_id")
    return rows


def source_path(root, row):
    return os.path.join(root, "downloads", DATASET_ID, "xz", row["dataset_id"] + ".yaml.xz")


def sample_name(row):
    return f"{row['mp_id']}__{row['dataset_id']}.f64le.bin"


def header_info(text):
    m = re.search(r"^phonopy:\n  version: *\"?([0-9.]+)", text, re.M)
    version = m.group(1) if m else None
    m = re.search(r"^physical_unit:\n(?:  .*\n)*?  length: *\"?([a-z]+)", text, re.M)
    length = m.group(1) if m else None
    # Supercell atom count: number of "- symbol:" entries inside the top-level supercell: block.
    m = re.search(r"^supercell:\n((?:[ #].*\n|\n)*?)(?=^\S)", text, re.M)
    if not m:
        raise ParseError("no supercell block")
    n_atoms = len(re.findall(r"^  - symbol:", m.group(1), re.M))
    return version, length, n_atoms


def parse_forces_lines(text):
    """Line state machine. Returns (list_of_token_strings, n_displacements)."""
    lines = text.split("\n")
    try:
        start = lines.index("displacements:")
    except ValueError:
        raise ParseError("no top-level displacements: block")
    tokens = []
    n_disp = 0
    per_disp = []
    state = "entry"
    i = start + 1
    while i < len(lines):
        ln = lines[i]
        if ln and not ln.startswith((" ", "-", "#")):
            break  # next top-level key
        if ln.startswith("- atom:"):
            n_disp += 1
            per_disp.append(0)
            state = "disp"
        elif ln.strip() == "forces:":
            if state != "disp":
                raise ParseError(f"forces: outside displacement entry at line {i+1}")
            state = "forces"
        elif state == "forces" and ln.startswith("  - ["):
            m = VEC_RE.match(ln)
            if not m:
                raise ParseError(f"bad force line {i+1}: {ln!r}")
            tokens.extend(m.groups())
            per_disp[-1] += 1
        elif state == "forces" and ln.strip() and not ln.startswith("- atom:"):
            raise ParseError(f"unexpected line in forces block {i+1}: {ln!r}")
        i += 1
    return tokens, n_disp, per_disp


def parse_forces_regex(text):
    """Independent parser: slice the displacements section and regex each entry."""
    m = re.search(r"^displacements:\n(.*?)(?=^[A-Za-z_]|\Z)", text, re.M | re.S)
    if not m:
        raise ParseError("no displacements section")
    body = m.group(1)
    entries = re.split(r"^- atom:", body, flags=re.M)[1:]
    tokens, per_disp = [], []
    for e in entries:
        parts = e.split("\n  forces:\n", 1)
        if len(parts) != 2:
            raise ParseError("entry without forces")
        vecs = re.findall(r"^  - \[([^\]]*)\]", parts[1], re.M)
        for v in vecs:
            t = TOKEN_RE.findall(v)
            if len(t) != 3:
                raise ParseError("vector arity")
            tokens.extend(t)
        per_disp.append(len(vecs))
    return tokens, len(entries), per_disp


def tokens_to_values(tokens):
    vals = []
    beyond8 = 0
    for s in tokens:
        v = float(s)
        if not math.isfinite(v):
            raise ParseError(f"non-finite {s}")
        d = Decimal(s)
        q = d.quantize(Q8)
        if d != q:
            # phonopy prints binary64 with %.16f, so e.g. 0.61194482 can appear as
            # 0.6119448199999999.  Accept only if it is the same double as the
            # 8-decimal value; any genuine extra precision is fatal.
            beyond8 += 1
            if float(q) != v or abs(d - q) > Decimal("1e-15"):
                raise ParseError(f"token {s} is not an 8-decimal value")
        if f"{v:.8f}" != f"{q:f}" or float(f"{v:.8f}") != v:
            raise ParseError(f"8-decimal round-trip failed for {s}")
        vals.append(v)
    return vals, beyond8


def decode_record(path, parser):
    with open(path, "rb") as f:
        raw = lzma.decompress(f.read())
    text = raw.decode("utf-8")
    version, length, n_atoms = header_info(text)
    if length != "angstrom":
        raise ParseError(f"length unit {length}")
    tokens, n_disp, per_disp = parser(text)
    if n_disp < 1 or n_atoms < 1:
        raise ParseError("empty displacements or supercell")
    if any(c != n_atoms for c in per_disp):
        raise ParseError(f"force rows per displacement {sorted(set(per_disp))} != supercell atoms {n_atoms}")
    if len(tokens) != n_disp * n_atoms * 3:
        raise ParseError("token count mismatch")
    vals, beyond8 = tokens_to_values(tokens)
    return {"values": vals, "version": version, "n_disp": n_disp, "n_atoms": n_atoms,
            "beyond8": beyond8, "yaml_sha256": hashlib.sha256(raw).hexdigest()}


def pack(vals):
    return struct.pack("<%dd" % len(vals), *vals)


def stats(vals, blob):
    stored = struct.unpack("<%dd" % len(vals), blob)
    zeros = sum(1 for v in stored if v == 0.0)
    distinct = len(set(stored))
    return {"min": min(stored), "max": max(stored), "zero_count": zeros,
            "distinct_count": distinct,
            "max_abs": max(abs(v) for v in stored)}


def degenerate_reason(st, n):
    if st["distinct_count"] < 2:
        return "constant"
    if st["zero_count"] == n:
        return "all-zero"
    return None


def cmd_build(args):
    root = os.path.join(args.repo_root, args.data_dir)
    rows = read_sources(args.sources)
    out_dir = os.path.join(root, "samples", DATASET_ID, SERIES_ID)
    idx_dir = os.path.join(root, "index", DATASET_ID)
    filt_dir = os.path.join(root, "filtered", DATASET_ID)
    for d in (out_dir, idx_dir, filt_dir):
        os.makedirs(d, exist_ok=True)
    keep = set()
    index_rows = []
    versions = {}
    tot_vals = tot_zero = tot_beyond8 = 0
    agg = hashlib.sha256()
    for k, row in enumerate(rows):
        p = source_path(root, row)
        try:
            rec = decode_record(p, parse_forces_lines)
        except (ParseError, lzma.LZMAError, UnicodeDecodeError) as e:
            raise SystemExit(f"FATAL {row['dataset_id']} {row['mp_id']}: {e}")
        blob = pack(rec["values"])
        n = len(rec["values"])
        st = stats(rec["values"], blob)
        why = degenerate_reason(st, n)
        if why:
            raise SystemExit(f"FATAL degenerate sample {row['dataset_id']}: {why}")
        name = sample_name(row)
        rel = os.path.join("samples", DATASET_ID, SERIES_ID, name)
        tmp = os.path.join(root, rel + ".tmp")
        with open(tmp, "wb") as f:
            f.write(blob)
        os.replace(tmp, os.path.join(root, rel))
        keep.add(name)
        sha = hashlib.sha256(blob).hexdigest()
        agg.update(sha.encode())
        versions[rec["version"]] = versions.get(rec["version"], 0) + 1
        tot_vals += n
        tot_zero += st["zero_count"]
        tot_beyond8 += rec["beyond8"]
        index_rows.append({
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "sample_path": rel,
            "numeric_kind": "float", "bit_width": 64, "endianness": "little",
            "element_size_bytes": 8, "sample_size_bytes": len(blob), "value_count": n,
            "sample_shape": [rec["n_disp"], rec["n_atoms"], 3],
            "source_dataset_id": row["dataset_id"], "materials_project_ref": row["mp_id"],
            "source_fileset_id": row["fileset_id"], "phonopy_version": rec["version"],
            "min": st["min"], "max": st["max"], "zero_count": st["zero_count"],
            "print_noise_tokens": rec["beyond8"], "sha256": sha,
        })
        if (k + 1) % 1000 == 0:
            print(f"built {k+1}/{len(rows)}", flush=True)
    # remove stale samples
    for fn in os.listdir(out_dir):
        if fn not in keep:
            os.remove(os.path.join(out_dir, fn))
    with open(os.path.join(idx_dir, "samples.jsonl.tmp"), "w") as f:
        for r in index_rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    os.replace(os.path.join(idx_dir, "samples.jsonl.tmp"), os.path.join(idx_dir, "samples.jsonl"))
    counts = sorted(r["value_count"] for r in index_rows)
    nn = len(counts)
    median = counts[nn // 2] if nn % 2 else (counts[nn // 2 - 1] + counts[nn // 2]) / 2
    summary = {
        "sample_count": nn, "total_values": tot_vals, "total_size_bytes": tot_vals * 8,
        "median_value_count": median, "min_value_count": counts[0], "max_value_count": counts[-1],
        "samples_below_1000_values": sum(1 for c in counts if c < 1000),
        "zero_fraction": tot_zero / tot_vals, "print_noise_tokens_equal_to_8_decimal_double": tot_beyond8,
        "phonopy_versions": versions, "aggregate_sample_sha256": agg.hexdigest(),
    }
    with open(os.path.join(filt_dir, "build_summary.json"), "w") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    print(json.dumps(summary, indent=2, sort_keys=True))


def load_manifest_series(recipe_dir):
    import tomllib
    with open(os.path.join(recipe_dir, "manifest.toml"), "rb") as f:
        m = tomllib.load(f)
    return {s["id"]: s for s in m["series"]}


def cmd_verify(args):
    root = os.path.join(args.repo_root, args.data_dir)
    rows = read_sources(args.sources)
    idx_path = os.path.join(root, "index", DATASET_ID, "samples.jsonl")
    index = [json.loads(l) for l in open(idx_path)]
    if len(index) != len(rows):
        raise SystemExit(f"index rows {len(index)} != sources {len(rows)}")
    out_dir = os.path.join(root, "samples", DATASET_ID, SERIES_ID)
    on_disk = set(os.listdir(out_dir))
    expected = {sample_name(r) for r in rows}
    if on_disk != expected:
        raise SystemExit(f"sample dir mismatch: extra={len(on_disk-expected)} missing={len(expected-on_disk)}")
    required = ["dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width",
                "endianness", "element_size_bytes", "sample_size_bytes", "value_count"]
    total_bytes = 0
    seen_sha = {}
    zero_total = val_total = 0
    for k, (row, ix) in enumerate(zip(rows, index)):
        for key in required:
            if key not in ix:
                raise SystemExit(f"index missing {key}")
        rel = os.path.join("samples", DATASET_ID, SERIES_ID, sample_name(row))
        if ix["sample_path"] != rel or ix["dataset_id"] != DATASET_ID or ix["series_id"] != SERIES_ID:
            raise SystemExit(f"index identity mismatch at {k}")
        if (ix["numeric_kind"], ix["bit_width"], ix["endianness"], ix["element_size_bytes"]) != ("float", 64, "little", 8):
            raise SystemExit("index dtype mismatch")
        with open(os.path.join(root, rel), "rb") as f:
            blob = f.read()
        try:
            rec = decode_record(source_path(root, row), parse_forces_regex)
        except (ParseError, lzma.LZMAError, UnicodeDecodeError) as e:
            raise SystemExit(f"verify parse failed {row['dataset_id']}: {e}")
        n = len(rec["values"])
        if pack(rec["values"]) != blob:
            raise SystemExit(f"sample bytes differ from independent re-derivation: {rel}")
        if len(blob) != ix["sample_size_bytes"] or n != ix["value_count"] or len(blob) != 8 * n:
            raise SystemExit(f"size mismatch {rel}")
        if ix["sample_shape"] != [rec["n_disp"], rec["n_atoms"], 3]:
            raise SystemExit(f"shape mismatch {rel}")
        st = stats(rec["values"], blob)
        why = degenerate_reason(st, n)
        if why:
            raise SystemExit(f"degenerate {rel}: {why}")
        if st["min"] != ix["min"] or st["max"] != ix["max"] or st["zero_count"] != ix["zero_count"]:
            raise SystemExit(f"stats mismatch {rel}")
        if st["max_abs"] > 1000.0:
            raise SystemExit(f"implausible force magnitude {st['max_abs']} eV/A in {rel}")
        sha = hashlib.sha256(blob).hexdigest()
        if sha != ix["sha256"]:
            raise SystemExit(f"sha mismatch {rel}")
        if sha in seen_sha:
            raise SystemExit(f"duplicate sample bytes {rel} == {seen_sha[sha]}")
        seen_sha[sha] = rel
        total_bytes += len(blob)
        zero_total += st["zero_count"]
        val_total += n
        if (k + 1) % 1000 == 0:
            print(f"verified {k+1}/{len(rows)}", flush=True)
    series = load_manifest_series(args.recipe_dir)[SERIES_ID]
    if series["sample_count"] != len(index) or series["total_size_bytes"] != total_bytes:
        raise SystemExit(f"manifest mismatch: manifest sample_count={series['sample_count']} total_size_bytes={series['total_size_bytes']} realized {len(index)} {total_bytes}")
    if total_bytes > 1_000_000_000:
        raise SystemExit("primary output exceeds 1 GB cap")
    counts = sorted(ix["value_count"] for ix in index)
    nn = len(counts)
    median = counts[nn // 2] if nn % 2 else (counts[nn // 2 - 1] + counts[nn // 2]) / 2
    if median < 1000 or val_total < 10000:
        raise SystemExit(f"floor failed: median={median} values={val_total}")
    print(json.dumps({"verified_samples": nn, "total_values": val_total, "total_size_bytes": total_bytes,
                      "median_value_count": median, "zero_fraction": zero_total / val_total}, indent=2))


def cmd_check_downloads(args):
    """Semantic payload check used by download.sh: xz integrity + phonopy force block present."""
    root = os.path.join(args.repo_root, args.data_dir)
    rows = read_sources(args.sources)
    bad = 0
    for k, row in enumerate(rows):
        p = source_path(root, row)
        try:
            with open(p, "rb") as f:
                text = lzma.decompress(f.read()).decode("utf-8")
            if not text.startswith("phonopy:\n"):
                raise ParseError("not a phonopy yaml")
            if "\ndisplacements:\n" not in text or "\n  forces:\n" not in text:
                raise ParseError("no displacement force sets")
        except (ParseError, lzma.LZMAError, UnicodeDecodeError, OSError) as e:
            bad += 1
            print(f"INVALID {row['dataset_id']} {row['mp_id']}: {e}", file=sys.stderr)
        if (k + 1) % 2000 == 0:
            print(f"checked {k+1}/{len(rows)}", flush=True)
    if bad:
        raise SystemExit(f"{bad} semantically invalid payloads")
    print(f"semantic check ok files={len(rows)}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["build", "verify", "check-downloads"])
    p.add_argument("--repo-root", required=True)
    p.add_argument("--data-dir", default=".data")
    p.add_argument("--sources", required=True)
    p.add_argument("--recipe-dir", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    args = p.parse_args()
    {"build": cmd_build, "verify": cmd_verify, "check-downloads": cmd_check_downloads}[args.cmd](args)


if __name__ == "__main__":
    main()
