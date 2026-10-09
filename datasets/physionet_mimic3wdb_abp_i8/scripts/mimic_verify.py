#!/usr/bin/env python3
"""Verify: independently re-derive every MIMIC-III ABP sample and its index row.

Independent of mimic_build.py: a regex header tokenizer, a whole-file
array('b') decode with strided slicing, sorted-list window statistics, and
its own copy of the keep thresholds. Checks sample bytes, every index field,
ingest stats, manifest totals, stray files, the keep rule, and degeneracy.
"""
from __future__ import annotations

import argparse
import array
import collections
import hashlib
import json
import re
import sys
import tempfile
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mimic_pins as P  # noqa: E402  (segment list and sizes only)
from mimic_synth import write_synth  # noqa: E402

# Own copy of the policy (must equal mimic_pins; checked below).
SERIES_ID = "mimic3wdb_abp_fmt80_i8"
GAIN_STRING = "1.25(-100)/mmHg"
INVALID = -128
WINDOW = 7500
FLAT_P2P = 2
LOW_MEDIAN = -75
PULSE_SPREAD = 13
MAX_INVALID_FRACTION = 0.10
MAX_MODE_SHARE = 0.25
MIN_PULSATILE_FRACTION = 0.5
MIN_DISTINCT = 32
MON_LO = -125
MON_HI = 125
CLASSES = ("pulsatile", "damped", "low", "flat", "invalid")

HEAD_RE = re.compile(r"^(\S+)\s+(\d+)\s+(\d+(?:\.\d+)?)\s+(\d+)\b")
SIG_RE = re.compile(
    r"^(\S+)\s+(\d+)\s+(\S+)\s+(\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(\d+)\s+(.+?)\s*$"
)


def tokenize(text: str):
    body = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    m = HEAD_RE.match(body[0])
    if not m:
        raise ValueError("bad header line")
    rec, nsig, freq, frames = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
    sigs = []
    for ln in body[1 : 1 + nsig]:
        s = SIG_RE.match(ln)
        if not s:
            raise ValueError(f"bad signal line {ln!r}")
        sigs.append(s.groups())
    if len(sigs) != nsig:
        raise ValueError("signal count")
    return rec, nsig, freq, frames, sigs


def wfdb16(total: int) -> int:
    t = total % 65536
    return t - 65536 if t > 32767 else t


def window_class(vals) -> str:
    n = len(vals)
    good = sorted(v for v in vals if v != INVALID)
    if len(good) * 2 < n:
        return "invalid"
    if good[-1] - good[0] <= FLAT_P2P:
        return "flat"
    m = len(good) - 1
    p5, p50, p95 = good[m * 5 // 100], good[m * 50 // 100], good[m * 95 // 100]
    if p50 < LOW_MEDIAN:
        return "low"
    if p95 - p5 >= PULSE_SPREAD:
        return "pulsatile"
    return "damped"


def derive(dat: Path, nsig: int, abp: int, frames: int, window: int) -> dict:
    raw = dat.read_bytes()
    if len(raw) != frames * nsig:
        raise ValueError(f"{dat.name}: size")
    arr = array.array("b", raw.translate(bytes((b + 128) % 256 for b in range(256))))
    checks = [wfdb16(sum(arr[s::nsig])) for s in range(nsig)]
    col = arr[abp::nsig]
    counts: dict[int, int] = {}
    tally: collections.Counter = collections.Counter()
    for w in range(0, len(col), 1 << 20):
        tally.update(col[w : w + (1 << 20)])  # iterates signed ints from array('b')
    for v, c in tally.items():
        counts[v] = c
    classes = {c: 0 for c in CLASSES}
    for w in range(0, len(col), window):
        classes[window_class(col[w : w + window])] += 1
    return {
        "raw_sha": hashlib.sha256(raw).hexdigest(),
        "checks": checks,
        "col": col,
        "counts": counts,
        "classes": classes,
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="mimic_verify_selftest_") as td:
        d = Path(td)
        exp = write_synth(d, 600)
        rec, nsig, freq, frames, sigs = tokenize((d / f"{exp['segment']}.hea").read_text())
        assert (rec, nsig, frames) == (exp["segment"], exp["nsig"], exp["frames"])
        r = derive(d / f"{exp['segment']}.dat", nsig, exp["abp_index"], frames, 600)
        assert list(r["col"]) == exp["abp"], "verify self-test: ABP"
        assert r["checks"] == exp["checksums"] == [int(s[6]) for s in sigs], "verify self-test: checksums"
        assert int(sigs[exp["abp_index"]][5]) == exp["abp"][0]
        cls = [window_class(r["col"][w : w + 600]) for w in range(0, frames, 600)]
        assert cls == exp["window_classes"], f"verify self-test: classes {cls}"
        assert r["counts"].get(INVALID, 0) == exp["invalid_count"]
        assert sigs[exp["abp_index"]][2] == GAIN_STRING
    print("verify self-test ok")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download-dir", required=True, type=Path)
    ap.add_argument("--samples-root", required=True, type=Path)
    ap.add_argument("--index", required=True, type=Path)
    ap.add_argument("--stats", required=True, type=Path)
    ap.add_argument("--data-root", required=True, type=Path)
    ap.add_argument("--manifest", required=True, type=Path)
    args = ap.parse_args()
    self_test()

    policy = {
        "SERIES_ID": SERIES_ID, "ABP_GAIN_STRING": GAIN_STRING, "INVALID_CODE": INVALID,
        "WINDOW_FRAMES": WINDOW, "FLAT_P2P_CODES": FLAT_P2P, "LOW_MEDIAN_CODE": LOW_MEDIAN,
        "PULSE_SPREAD_CODES": PULSE_SPREAD, "MAX_INVALID_FRACTION": MAX_INVALID_FRACTION,
        "MAX_MODE_SHARE": MAX_MODE_SHARE, "MIN_PULSATILE_WINDOW_FRACTION": MIN_PULSATILE_FRACTION,
        "MIN_DISTINCT_CODES": MIN_DISTINCT, "MONITOR_MIN_CODE": MON_LO, "MONITOR_MAX_CODE": MON_HI,
    }
    for k, v in policy.items():
        if getattr(P, k) != v:
            raise SystemExit(f"policy drift: mimic_pins.{k}={getattr(P, k)!r} != verify {v!r}")

    rows = [json.loads(ln) for ln in args.index.read_text().splitlines() if ln.strip()]
    by_seg = {r["segment"]: r for r in rows}
    if len(by_seg) != len(rows):
        raise SystemExit("duplicate index rows")
    stats = json.loads(args.stats.read_text())
    series_dir = args.samples_root / SERIES_ID
    expected_files = set()
    kept, excluded = [], []
    seen_sha = set()
    for seg in P.segment_rows():
        name = seg["segment"]
        recdir = args.download_dir / seg["record_dir"]
        rec, nsig, freq, frames, sigs = tokenize((recdir / f"{name}.hea").read_text())
        if (rec, nsig, freq, frames) != (name, seg["nsig"], "125", seg["frames"]):
            raise SystemExit(f"{name}: header geometry")
        names = [s[8] for s in sigs]
        if names.count("ABP") != 1:
            raise SystemExit(f"{name}: ABP count")
        ai = names.index("ABP")
        if ai != seg["abp_index"] or any(s[1] != "80" or s[0] != f"{name}.dat" for s in sigs):
            raise SystemExit(f"{name}: layout")
        if sigs[ai][2] != GAIN_STRING or sigs[ai][3] != "8" or sigs[ai][4] != "0":
            raise SystemExit(f"{name}: ABP calibration")
        r = derive(recdir / f"{name}.dat", nsig, ai, frames, WINDOW)
        if r["raw_sha"] != seg["dat_sha256"]:
            raise SystemExit(f"{name}: .dat SHA-256")
        if r["checks"] != [int(s[6]) for s in sigs]:
            raise SystemExit(f"{name}: WFDB checksums")
        col = r["col"]
        if col[0] != int(sigs[ai][5]):
            raise SystemExit(f"{name}: initial value")
        counts = r["counts"]
        inv = counts.get(INVALID, 0)
        mode_code = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        nwin = sum(r["classes"].values())
        fails = []
        if inv > MAX_INVALID_FRACTION * frames:
            fails.append("invalid")
        if mode_code[1] > MAX_MODE_SHARE * frames:
            fails.append("mode")
        if r["classes"]["pulsatile"] < MIN_PULSATILE_FRACTION * nwin:
            fails.append("pulsatile")
        if len(counts) < MIN_DISTINCT:
            fails.append("distinct")
        out_of_range = sum(counts.get(v, 0) for v in range(-128, 128) if not MON_LO <= v <= MON_HI)
        if out_of_range:
            fails.append("monitor_range")
        path = series_dir / f"{name}.bin"
        if fails:
            excluded.append(name)
            if name in by_seg or path.exists():
                raise SystemExit(f"{name}: excluded by policy ({fails}) but emitted")
            continue
        kept.append(name)
        expected_files.add(path.name)
        row = by_seg.get(name)
        if row is None:
            raise SystemExit(f"{name}: kept by policy but no index row")
        data = path.read_bytes()
        if data != col.tobytes():
            raise SystemExit(f"{name}: sample bytes differ from re-derivation")
        sha = hashlib.sha256(data).hexdigest()
        if sha in seen_sha:
            raise SystemExit(f"{name}: duplicate payload")
        seen_sha.add(sha)
        expect = {
            "dataset_id": P.DATASET_ID, "series_id": SERIES_ID,
            "sample_path": f"samples/{P.DATASET_ID}/{SERIES_ID}/{name}.bin",
            "numeric_kind": "int", "bit_width": 8, "endianness": "little",
            "element_size_bytes": 1, "sample_size_bytes": frames, "value_count": frames,
            "natural_record_kind": P.NATURAL_RECORD_KIND,
            "record": seg["record"], "segment": name,
            "source_dat": f"{seg['record_dir']}{name}.dat",
            "nsig": nsig, "abp_signal_index": ai, "sampling_hz": 125,
            "adc_gain_per_mmhg": 1.25, "adc_baseline": -100, "units": "mmHg",
            "wfdb_checksum": int(sigs[ai][6]), "wfdb_initial_value": int(sigs[ai][5]),
            "min": min(counts), "max": max(counts),
            "valid_min": min(k for k in counts if k != INVALID),
            "invalid_sample_count": inv,
            "saturation_high_count": counts.get(MON_HI, 0),
            "saturation_low_count": counts.get(MON_LO, 0),
            "outside_monitor_range_count": out_of_range,
            "distinct_codes": len(counts),
            "mode_code": mode_code[0],
            "mode_share": round(mode_code[1] / frames, 6),
            **{f"windows_{c}": r["classes"][c] for c in CLASSES},
            "sha256": sha,
        }
        if set(row) != set(expect):
            raise SystemExit(f"{name}: index keys {sorted(set(row) ^ set(expect))}")
        for k, v in expect.items():
            if row[k] != v:
                raise SystemExit(f"{name}: index field {k}: {row[k]!r} != {v!r}")
        if (args.data_root / row["sample_path"]).resolve() != path.resolve():
            raise SystemExit(f"{name}: sample_path")
        if min(counts) == max(counts):
            raise SystemExit(f"{name}: constant")
        print(f"ok {name} values={frames} invalid={inv} pulsatile={r['classes']['pulsatile']}/{nwin}")

    if [r["segment"] for r in rows] != kept:
        raise SystemExit("index order/content differs from policy-kept list")
    present = {p.name for p in series_dir.iterdir()}
    if present != expected_files:
        raise SystemExit(f"stray or missing sample files: {sorted(present ^ expected_files)}")
    if stats.get("kept_segments") != kept or [e["segment"] for e in stats.get("excluded_segments", [])] != excluded:
        raise SystemExit("ingest stats kept/excluded lists differ")
    total = sum(r["value_count"] for r in rows)
    if stats.get("sample_count") != len(rows) or stats.get("total_values") != total:
        raise SystemExit("ingest stats totals differ")
    agg = hashlib.sha256("".join(f"{r['segment']}:{r['sha256']}\n" for r in rows).encode()).hexdigest()
    if stats.get("aggregate_sample_sha256") != agg:
        raise SystemExit("aggregate SHA-256 differs")
    manifest = tomllib.loads(args.manifest.read_text())
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1:
        raise SystemExit("manifest series missing")
    if series[0]["sample_count"] != len(rows) or series[0]["total_size_bytes"] != total:
        raise SystemExit(
            f"manifest totals {series[0]['sample_count']}/{series[0]['total_size_bytes']} "
            f"!= realized {len(rows)}/{total}"
        )
    vals = sorted(r["value_count"] for r in rows)
    if total < 10_000 or vals[(len(vals) - 1) // 2] < 1_000:
        raise SystemExit("below floor")
    text = args.index.read_text() + args.stats.read_text()
    if re.search(r"Location|micu|sicu|ccu|\d{1,2}:\d{2}:\d{2}", text):
        raise SystemExit("header metadata (location/time) leaked into outputs")
    print(f"verify ok: samples={len(rows)} values={total} excluded={len(excluded)} aggregate_sha256={agg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
