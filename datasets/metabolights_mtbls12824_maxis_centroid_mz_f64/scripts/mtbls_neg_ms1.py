#!/usr/bin/env python3
"""MTBLS12824 negative-ion HILIC MS1 centroid m/z decoder (pure stdlib).

Subcommands
  validate FILE...   full semantic check of downloaded mzML runs (used by download.sh)
  extract            decode m/z arrays and write one float64 sample per MS1 spectrum
  verify             independently re-decode (line-streaming regex decoder, not
                     ElementTree) and compare index rows and sample bytes
  selftest           exercise both decoders on a synthetic mzML file

Missing-value policy (shared by extract and verify): every spectrum in a pinned
run must be MS level 1, MS1 spectrum, negative scan, centroid, and carry exactly
one m/z array (64-bit float, zlib) and one intensity array (64-bit float, zlib).
Any violation, base64/zlib failure, decoded length != defaultArrayLength,
non-finite or non-positive m/z, or descending m/z is fatal. Spectra with
defaultArrayLength == 0 hold no values and are counted but emit no sample.
Intensity arrays are decoded for validation only and never written.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import re
import shutil
import statistics
import struct
import sys
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

DATASET_ID = "metabolights_mtbls12824_maxis_centroid_mz_f64"
SERIES_ID = "neg_hilic_ms1_centroid_mz_f64"
SCRIPT_DIR = Path(__file__).resolve().parent
RUNS_TSV = SCRIPT_DIR / "runs.tsv"

ACC_MS_LEVEL = "MS:1000511"
ACC_MS1 = "MS:1000579"
ACC_NEG = "MS:1000129"
ACC_POS = "MS:1000130"
ACC_CENTROID = "MS:1000127"
ACC_PROFILE = "MS:1000128"
ACC_F64 = "MS:1000523"
ACC_F32 = "MS:1000521"
ACC_ZLIB = "MS:1000574"
ACC_NOCOMP = "MS:1000576"
ACC_MZ = "MS:1000514"
ACC_INT = "MS:1000515"
ACC_SST = "MS:1000016"
MZ_MIN, MZ_MAX = 1.0, 5000.0


class DecodeError(ValueError):
    pass


def load_runs(path: Path = RUNS_TSV) -> list[dict]:
    runs = []
    for line in path.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, sha, size, group = line.split("\t")
        runs.append({"name": name, "sha256": sha, "size": int(size), "group": group})
    names = [r["name"] for r in runs]
    if names != sorted(names) or len(set(names)) != len(names):
        raise DecodeError("runs.tsv must be sorted and unique")
    return runs


def run_tag(name: str) -> str:
    m = re.fullmatch(r"21P0055_Tissue_Georges_NEG_([NV])_(\d+)_(\d+)\.mzML", name)
    if not m:
        raise DecodeError(f"unexpected run name {name}")
    return f"neg_{m.group(1).lower()}_{m.group(2)}_{m.group(3)}"


def check_spectrum(ctx: str, accs: set[str], ms_level: str | None) -> None:
    if ms_level != "1":
        raise DecodeError(f"{ctx}: ms level {ms_level!r} != 1")
    for need, label in ((ACC_MS1, "MS1 spectrum"), (ACC_NEG, "negative scan"), (ACC_CENTROID, "centroid spectrum")):
        if need not in accs:
            raise DecodeError(f"{ctx}: missing {label} cvParam")
    for bad, label in ((ACC_POS, "positive scan"), (ACC_PROFILE, "profile spectrum")):
        if bad in accs:
            raise DecodeError(f"{ctx}: unexpected {label} cvParam")


def decode_array(ctx: str, accs: set[str], text: str, n: int) -> tuple[str, bytes]:
    kinds = [k for k, a in (("mz", ACC_MZ), ("intensity", ACC_INT)) if a in accs]
    if len(kinds) != 1:
        raise DecodeError(f"{ctx}: array kind not exactly one of m/z, intensity: {sorted(accs)}")
    if ACC_F64 not in accs or ACC_F32 in accs:
        raise DecodeError(f"{ctx}: {kinds[0]} array not declared 64-bit float")
    if ACC_ZLIB not in accs or ACC_NOCOMP in accs:
        raise DecodeError(f"{ctx}: {kinds[0]} array not declared zlib")
    try:
        raw = zlib.decompress(base64.b64decode("".join(text.split()), validate=True)) if n else b""
    except Exception as exc:  # noqa: BLE001
        raise DecodeError(f"{ctx}: base64/zlib failure: {exc}") from exc
    if len(raw) != 8 * n:
        raise DecodeError(f"{ctx}: decoded {len(raw)} bytes, expected {8 * n} (defaultArrayLength={n})")
    return kinds[0], raw


def check_mz(ctx: str, raw: bytes) -> tuple[int, float, float]:
    vals = struct.unpack(f"<{len(raw) // 8}d", raw)
    ties = 0
    prev = -math.inf
    for v in vals:
        if not math.isfinite(v) or not (MZ_MIN <= v <= MZ_MAX):
            raise DecodeError(f"{ctx}: m/z out of range or non-finite: {v!r}")
        if v < prev:
            raise DecodeError(f"{ctx}: m/z array not ascending")
        if v == prev:
            ties += 1
        prev = v
    return ties, vals[0], vals[-1]


def finish_spectrum(ctx: str, arrays: dict, n: int) -> bytes:
    if set(arrays) != {"mz", "intensity"}:
        raise DecodeError(f"{ctx}: expected one m/z and one intensity array, got {sorted(arrays)}")
    if n:
        ivals = struct.unpack(f"<{n}d", arrays["intensity"])
        if not all(math.isfinite(x) and x >= 0 for x in ivals):
            raise DecodeError(f"{ctx}: invalid intensity values")
    return arrays["mz"]


# ---------------------------------------------------------------- ElementTree decoder

def _loc(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def iter_spectra_et(path: Path):
    """Yield (index, native_id, scan_start_time, n, mz_bytes); validates everything."""
    declared = None
    seen = 0
    context = ET.iterparse(path, events=("start", "end"))
    root = None
    speclist = None
    for ev, el in context:
        tag = _loc(el.tag)
        if root is None:
            root = el
            if tag not in ("indexedmzML", "mzML"):
                raise DecodeError(f"{path.name}: root {tag} is not mzML")
        if ev == "start":
            if tag == "spectrumList":
                declared = int(el.attrib["count"])
                speclist = el
            continue
        if tag != "spectrum":
            if tag == "chromatogramList":
                el.clear()
            continue
        idx = int(el.attrib["index"])
        ctx = f"{path.name}:spectrum[{idx}]"
        if idx != seen:
            raise DecodeError(f"{ctx}: index out of order (expected {seen})")
        n = int(el.attrib["defaultArrayLength"])
        accs = set()
        ms_level = None
        sst = None
        for child in el:
            ct = _loc(child.tag)
            if ct == "cvParam":
                accs.add(child.attrib.get("accession", ""))
                if child.attrib.get("accession") == ACC_MS_LEVEL:
                    ms_level = child.attrib.get("value")
        for cv in el.iter():
            if _loc(cv.tag) == "cvParam" and cv.attrib.get("accession") == ACC_SST:
                sst = float(cv.attrib["value"])
                if cv.attrib.get("unitAccession") != "UO:0000010":
                    raise DecodeError(f"{ctx}: scan start time unit is not seconds")
        check_spectrum(ctx, accs, ms_level)
        arrays = {}
        for bda in (x for x in el.iter() if _loc(x.tag) == "binaryDataArray"):
            baccs = {x.attrib.get("accession", "") for x in bda if _loc(x.tag) == "cvParam"}
            binel = next((x for x in bda if _loc(x.tag) == "binary"), None)
            if binel is None:
                raise DecodeError(f"{ctx}: binaryDataArray without <binary>")
            kind, raw = decode_array(ctx, baccs, binel.text or "", n)
            if kind in arrays:
                raise DecodeError(f"{ctx}: duplicate {kind} array")
            arrays[kind] = raw
        mz = finish_spectrum(ctx, arrays, n)
        yield idx, el.attrib.get("id", ""), sst, n, mz
        seen += 1
        el.clear()
        if speclist is not None:
            # drop processed spectrum elements from the tree to bound memory
            for done in list(speclist):
                speclist.remove(done)
    if declared is None:
        raise DecodeError(f"{path.name}: no spectrumList")
    if seen != declared:
        raise DecodeError(f"{path.name}: spectrumList count {declared} but parsed {seen}")


# ---------------------------------------------------------------- regex line decoder (verify)

RE_SPEC = re.compile(r'<spectrum\s[^>]*\bindex="(\d+)"[^>]*\bid="([^"]*)"[^>]*\bdefaultArrayLength="(\d+)"')
RE_CV = re.compile(r'<cvParam\s[^>]*\baccession="([^"]+)"(?:[^>]*\bvalue="([^"]*)")?')
RE_LIST = re.compile(r'<spectrumList\s[^>]*\bcount="(\d+)"')
RE_SST = re.compile(r'accession="MS:1000016"[^>]*\bvalue="([^"]*)"[^>]*unitAccession="([^"]*)"')


def iter_spectra_re(path: Path):
    """Independent line-oriented decoder. Assumes ProteoWizard's one-element-per-line
    layout and fails loudly if that assumption breaks."""
    declared = None
    seen = 0
    state = None  # None | spectrum | bda
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            s = line.strip()
            if state is None:
                if declared is None:
                    m = RE_LIST.search(s)
                    if m:
                        declared = int(m.group(1))
                    continue
                if s.startswith("<spectrum "):
                    m = RE_SPEC.match(s)
                    if not m:
                        raise DecodeError(f"{path.name}: unparsable spectrum line {s[:120]}")
                    idx, nid, n = int(m.group(1)), m.group(2), int(m.group(3))
                    ctx = f"{path.name}:spectrum[{idx}]"
                    if idx != seen:
                        raise DecodeError(f"{ctx}: index out of order")
                    depth = 0  # nesting depth below <spectrum>
                    accs, ms_level, sst, arrays = set(), None, None, {}
                    state = "spectrum"
                elif s.startswith("</spectrumList>"):
                    break
                continue
            if state == "spectrum":
                if s.startswith("</spectrum>"):
                    check_spectrum(ctx, accs, ms_level)
                    mz = finish_spectrum(ctx, arrays, n)
                    yield idx, nid, sst, n, mz
                    seen += 1
                    state = None
                    continue
                if s.startswith("<binaryDataArray ") or s == "<binaryDataArray>":
                    baccs, btext = set(), None
                    state = "bda"
                    continue
                if s.startswith("<cvParam"):
                    m = RE_SST.search(s)
                    if m:
                        if m.group(2) != "UO:0000010":
                            raise DecodeError(f"{ctx}: scan start time unit is not seconds")
                        sst = float(m.group(1))
                    elif depth == 0:
                        cm = RE_CV.search(s)
                        accs.add(cm.group(1))
                        if cm.group(1) == ACC_MS_LEVEL:
                            ms_level = cm.group(2)
                    continue
                if s.startswith("</"):
                    depth -= 1
                elif s.startswith("<") and not s.endswith("/>"):
                    depth += 1
                continue
            if state == "bda":
                if s.startswith("<cvParam"):
                    baccs.add(RE_CV.search(s).group(1))
                elif s.startswith("<binary>"):
                    if not s.endswith("</binary>"):
                        raise DecodeError(f"{ctx}: multi-line <binary> not supported")
                    btext = s[len("<binary>"):-len("</binary>")]
                elif s == "<binary/>":
                    btext = ""
                elif s.startswith("</binaryDataArray>"):
                    if btext is None:
                        raise DecodeError(f"{ctx}: binaryDataArray without <binary>")
                    kind, raw = decode_array(ctx, baccs, btext, n)
                    if kind in arrays:
                        raise DecodeError(f"{ctx}: duplicate {kind} array")
                    arrays[kind] = raw
                    state = "spectrum"
    if declared is None:
        raise DecodeError(f"{path.name}: no spectrumList")
    if state is not None:
        raise DecodeError(f"{path.name}: truncated inside spectrum")
    if seen != declared:
        raise DecodeError(f"{path.name}: spectrumList count {declared} but parsed {seen}")


# ---------------------------------------------------------------- commands

def sample_name(tag: str, idx: int) -> str:
    return f"{tag}_spectrum_{idx:06d}.bin"


def plan(downloads: Path, decoder, write_root: Path | None, data_root: Path):
    runs = load_runs()
    rows, per_run = [], {}
    stats = {"empty_spectra": 0, "tied_mz_pairs": 0}
    for run in runs:
        p = downloads / run["name"]
        if not p.is_file():
            raise DecodeError(f"missing pinned run {p}")
        if p.stat().st_size != run["size"]:
            raise DecodeError(f"size mismatch {p}")
        tag = run_tag(run["name"])
        nspec = nsamp = nvals = 0
        for idx, nid, sst, n, mz in decoder(p):
            nspec += 1
            ctx = f"{run['name']}:spectrum[{idx}]"
            if n == 0:
                stats["empty_spectra"] += 1
                continue
            ties, lo, hi = check_mz(ctx, mz)
            stats["tied_mz_pairs"] += ties
            if n >= 2 and lo == hi:
                raise DecodeError(f"{ctx}: constant m/z array")
            name = sample_name(tag, idx)
            rel = f"samples/{DATASET_ID}/{SERIES_ID}/{name}"
            if write_root is not None:
                (data_root / rel).write_bytes(mz)
            rows.append({
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": rel,
                "numeric_kind": "float",
                "bit_width": 64,
                "endianness": "little",
                "element_size_bytes": 8,
                "sample_size_bytes": len(mz),
                "value_count": n,
                "min": lo,
                "max": hi,
                "sha256": hashlib.sha256(mz).hexdigest(),
                "source_file": run["name"],
                "source_group": run["group"],
                "native_id": nid,
                "scan_start_time_s": sst,
            })
            nsamp += 1
            nvals += n
        per_run[run["name"]] = {"spectra": nspec, "samples": nsamp, "values": nvals}
        print(f"run {run['name']} spectra={nspec} samples={nsamp} values={nvals}", flush=True)
    return rows, per_run, stats


def enforce(rows: list[dict]) -> dict:
    counts = [r["value_count"] for r in rows]
    total_bytes = sum(r["sample_size_bytes"] for r in rows)
    if not rows:
        raise DecodeError("no samples")
    summary = {
        "samples": len(rows),
        "values": sum(counts),
        "bytes": total_bytes,
        "median_values": statistics.median(counts),
        "min_values": min(counts),
        "max_values": max(counts),
        "global_min": min(r["min"] for r in rows),
        "global_max": max(r["max"] for r in rows),
    }
    if summary["values"] < 10_000 or summary["median_values"] < 1000:
        raise DecodeError(f"acceptance floor failed: {summary}")
    if total_bytes > 1_000_000_000:
        raise DecodeError(f"primary output exceeds 1 GB: {total_bytes}")
    if summary["global_min"] == summary["global_max"]:
        raise DecodeError("degenerate constant series")
    if len({r["sha256"] for r in rows}) < len(rows) * 0.99:
        raise DecodeError("too many duplicate spectra")
    return summary


def cmd_validate(a) -> None:
    runs = {r["name"]: r for r in load_runs()}
    for f in a.files:
        p = Path(f)
        name = p.name[:-len(".part")] if p.name.endswith(".part") else p.name
        if name not in runs:
            raise DecodeError(f"{name} not in pinned runs")
        n = vals = 0
        for idx, nid, sst, cnt, mz in iter_spectra_et(p):
            if cnt:
                check_mz(f"{name}:spectrum[{idx}]", mz)
            n += 1
            vals += cnt
        if n < 100:
            raise DecodeError(f"{name}: only {n} spectra")
        print(f"validated {name} spectra={n} mz_values={vals}", flush=True)


def cmd_extract(a) -> None:
    data_root = Path(a.data_root)
    out = data_root / "samples" / DATASET_ID / SERIES_ID
    if out.parent.exists():
        shutil.rmtree(out.parent)
    out.mkdir(parents=True)
    rows, per_run, stats = plan(Path(a.downloads), iter_spectra_et, out, data_root)
    summary = enforce(rows)
    idx = data_root / "index" / DATASET_ID / "samples.jsonl"
    idx.parent.mkdir(parents=True, exist_ok=True)
    idx.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    st = data_root / "filtered" / DATASET_ID / "spectrum_stats.json"
    st.parent.mkdir(parents=True, exist_ok=True)
    st.write_text(json.dumps({"runs": per_run, **stats, **summary}, indent=2, sort_keys=True) + "\n")
    print("built " + json.dumps({**stats, **summary}, sort_keys=True))


def load_manifest_series(path: Path) -> dict:
    import tomllib
    m = tomllib.loads(path.read_text())
    for s in m.get("series", []):
        if s.get("id") == SERIES_ID:
            return s
    raise DecodeError("series missing from manifest")


def cmd_verify(a) -> None:
    data_root = Path(a.data_root)
    rows, per_run, stats = plan(Path(a.downloads), iter_spectra_re, None, data_root)
    summary = enforce(rows)
    got = [json.loads(x) for x in (data_root / "index" / DATASET_ID / "samples.jsonl").read_text().splitlines() if x.strip()]
    if len(got) != len(rows):
        raise DecodeError(f"index has {len(got)} rows, re-derived {len(rows)}")
    for g, e in zip(got, rows):
        if g != e:
            diff = {k: (g.get(k), e.get(k)) for k in set(g) | set(e) if g.get(k) != e.get(k)}
            raise DecodeError(f"index row mismatch {e['sample_path']}: {diff}")
    sample_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    on_disk = sorted(p.name for p in sample_dir.iterdir())
    if on_disk != sorted(Path(r["sample_path"]).name for r in rows):
        raise DecodeError("sample directory contents differ from index")
    if sorted(p.name for p in sample_dir.parent.iterdir()) != [SERIES_ID]:
        raise DecodeError("unexpected series directories")
    for r in rows:
        b = (data_root / r["sample_path"]).read_bytes()
        if len(b) != r["sample_size_bytes"] or hashlib.sha256(b).hexdigest() != r["sha256"]:
            raise DecodeError(f"sample bytes mismatch {r['sample_path']}")
    ms = load_manifest_series(Path(a.manifest))
    if ms.get("sample_count") != summary["samples"] or ms.get("total_size_bytes") != summary["bytes"]:
        raise DecodeError(
            f"manifest sample_count/total_size_bytes {ms.get('sample_count')}/{ms.get('total_size_bytes')} "
            f"!= realized {summary['samples']}/{summary['bytes']}")
    print("verified " + json.dumps({**stats, **summary}, sort_keys=True))


# ---------------------------------------------------------------- self-test

def _synthetic(path: Path, spectra: list[tuple[list[float], list[float]]], extra: str = "") -> None:
    def arr(vals, acc, name):
        raw = struct.pack(f"<{len(vals)}d", *vals)
        enc = base64.b64encode(zlib.compress(raw)).decode()
        return (f'            <binaryDataArray encodedLength="{len(enc)}">\n'
                f'              <cvParam cvRef="MS" accession="MS:1000523" name="64-bit float" value=""/>\n'
                f'              <cvParam cvRef="MS" accession="MS:1000574" name="zlib compression" value=""/>\n'
                f'              <cvParam cvRef="MS" accession="{acc}" name="{name}" value=""/>\n'
                f'              <binary>{enc}</binary>\n'
                f'            </binaryDataArray>\n')
    out = ['<?xml version="1.0" encoding="utf-8"?>\n<indexedmzML xmlns="http://psi.hupo.org/ms/mzml">\n'
           '  <mzML xmlns="http://psi.hupo.org/ms/mzml" version="1.1.0">\n    <run id="x">\n'
           f'      <spectrumList count="{len(spectra)}">\n']
    for i, (mz, it) in enumerate(spectra):
        out.append(f'        <spectrum index="{i}" id="scan={i + 1}" defaultArrayLength="{len(mz)}">\n'
                   '          <cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="1"/>\n'
                   '          <cvParam cvRef="MS" accession="MS:1000579" name="MS1 spectrum" value=""/>\n'
                   '          <cvParam cvRef="MS" accession="MS:1000129" name="negative scan" value=""/>\n'
                   '          <cvParam cvRef="MS" accession="MS:1000127" name="centroid spectrum" value=""/>\n'
                   f'{extra}'
                   '          <scanList count="1">\n            <scan>\n'
                   f'              <cvParam cvRef="MS" accession="MS:1000016" name="scan start time" value="{0.5 * i}" unitCvRef="UO" unitAccession="UO:0000010" unitName="second"/>\n'
                   '            </scan>\n          </scanList>\n'
                   '          <binaryDataArrayList count="2">\n'
                   + arr(mz, ACC_MZ, "m/z array") + arr(it, ACC_INT, "intensity array") +
                   '          </binaryDataArrayList>\n        </spectrum>\n')
    out.append('      </spectrumList>\n    </run>\n  </mzML>\n</indexedmzML>\n')
    path.write_text("".join(out))


def cmd_selftest(a) -> None:
    import random
    tmp = Path(a.workdir)
    tmp.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(7)
    spectra = []
    for k in range(5):
        n = 0 if k == 3 else rnd.randint(1, 3000)
        mz = sorted(50 + 1150 * rnd.random() for _ in range(n))
        spectra.append((mz, [float(rnd.randint(500, 10**6)) for _ in range(n)]))
    good = tmp / "good.mzML"
    _synthetic(good, spectra)
    for dec in (iter_spectra_et, iter_spectra_re):
        res = list(dec(good))
        assert len(res) == 5, dec
        for (idx, nid, sst, n, mz), (emz, _) in zip(res, spectra):
            assert n == len(emz) and mz == struct.pack(f"<{n}d", *emz), (dec, idx)
            assert sst == 0.5 * idx and nid == f"scan={idx + 1}"
    bad_cases = {
        "profile": '          <cvParam cvRef="MS" accession="MS:1000128" name="profile spectrum" value=""/>\n',
        "positive": '          <cvParam cvRef="MS" accession="MS:1000130" name="positive scan" value=""/>\n',
    }
    for label, extra in bad_cases.items():
        p = tmp / f"bad_{label}.mzML"
        _synthetic(p, spectra[:2], extra)
        for dec in (iter_spectra_et, iter_spectra_re):
            try:
                list(dec(p))
            except DecodeError:
                continue
            raise AssertionError(f"{dec.__name__} accepted {label}")
    # length mismatch: corrupt defaultArrayLength
    p = tmp / "bad_len.mzML"
    _synthetic(p, spectra[:2])
    t = p.read_text().replace(f'defaultArrayLength="{len(spectra[0][0])}"', f'defaultArrayLength="{len(spectra[0][0]) + 1}"', 1)
    p.write_text(t)
    for dec in (iter_spectra_et, iter_spectra_re):
        try:
            list(dec(p))
        except DecodeError:
            continue
        raise AssertionError(f"{dec.__name__} accepted length mismatch")
    # count mismatch
    p = tmp / "bad_count.mzML"
    _synthetic(p, spectra[:2])
    p.write_text(p.read_text().replace('count="2">', 'count="3">', 1))
    for dec in (iter_spectra_et, iter_spectra_re):
        try:
            list(dec(p))
        except DecodeError:
            continue
        raise AssertionError(f"{dec.__name__} accepted count mismatch")
    try:
        check_mz("x", struct.pack("<3d", 100.0, 99.0, 101.0))
        raise AssertionError("descending accepted")
    except DecodeError:
        pass
    print("selftest ok")


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("files", nargs="+")
    v.set_defaults(func=cmd_validate)
    for name, fn in (("extract", cmd_extract), ("verify", cmd_verify)):
        q = sub.add_parser(name)
        q.add_argument("--downloads", required=True)
        q.add_argument("--data-root", required=True)
        if name == "verify":
            q.add_argument("--manifest", required=True)
        q.set_defaults(func=fn)
    s = sub.add_parser("selftest")
    s.add_argument("--workdir", required=True)
    s.set_defaults(func=cmd_selftest)
    a = p.parse_args()
    try:
        a.func(a)
    except DecodeError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
