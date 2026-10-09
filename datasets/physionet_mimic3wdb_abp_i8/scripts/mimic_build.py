#!/usr/bin/env python3
"""Build: de-interleave the ABP channel of each pinned MIMIC-III segment.

For every pinned segment (mimic_pins.SEGMENTS, canonical order) this parses
the WFDB segment header, checks it against the pins, streams the format-80
.dat in whole-frame chunks, verifies the 16-bit WFDB checksum of every
signal and the ABP initial value, and writes the ABP column as signed int8
(stored byte - 128). Per-segment content diagnostics (60 s windows) decide
the pinned keep rule; excluded segments get no sample.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mimic_pins as P  # noqa: E402
from mimic_synth import write_synth  # noqa: E402

XOR80 = bytes(b ^ 0x80 for b in range(256))  # offset-binary byte -> two's complement int8 byte


def parse_header(text: str) -> dict:
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    head = lines[0].split()
    rec, nsig, freq, frames = head[0], int(head[1]), head[2], int(head[3])
    sigs = []
    for ln in lines[1 : 1 + nsig]:
        f = ln.split()
        if len(f) < 9:
            raise ValueError(f"short signal line in {rec}: {ln!r}")
        sigs.append(
            {
                "file": f[0],
                "fmt": f[1],
                "gain": f[2],
                "adcres": f[3],
                "adczero": f[4],
                "init": int(f[5]),
                "checksum": int(f[6]),
                "blocksize": f[7],
                "name": " ".join(f[8:]),
            }
        )
    if len(sigs) != nsig:
        raise ValueError(f"{rec}: header declares {nsig} signals, has {len(sigs)}")
    return {"record": rec, "nsig": nsig, "freq": freq, "frames": frames, "signals": sigs}


def check_header(h: dict, seg: str, nsig: int, frames: int, abp_index: int) -> None:
    if h["record"] != seg or h["nsig"] != nsig or h["frames"] != frames or h["freq"] != str(P.SAMPLING_HZ):
        raise ValueError(f"{seg}: header geometry mismatch {h['record']} {h['nsig']} {h['freq']} {h['frames']}")
    for s in h["signals"]:
        if s["fmt"] != "80" or s["file"] != f"{seg}.dat":
            raise ValueError(f"{seg}: signal {s['name']} not format 80 in {seg}.dat")
    names = [s["name"] for s in h["signals"]]
    if names.count("ABP") != 1 or names.index("ABP") != abp_index:
        raise ValueError(f"{seg}: ABP index mismatch {names}")
    a = h["signals"][abp_index]
    if a["gain"] != P.ABP_GAIN_STRING or a["adcres"] != "8" or a["adczero"] != "0":
        raise ValueError(f"{seg}: ABP calibration mismatch {a}")


def classify_window(counts: collections.Counter, n: int) -> str:
    """counts: histogram of int8 codes in one window of n values."""
    valid = n - counts.get(P.INVALID_CODE, 0)
    if 2 * valid < n:
        return "invalid"
    keys = sorted(k for k in counts if k != P.INVALID_CODE)
    if keys[-1] - keys[0] <= P.FLAT_P2P_CODES:
        return "flat"
    targets = {k: (valid - 1) * k // 100 for k in (5, 50, 95)}
    pct = {}
    cum = 0
    for key in keys:
        cum += counts[key]
        for k, t in targets.items():
            if k not in pct and cum > t:
                pct[k] = key
    if pct[50] < P.LOW_MEDIAN_CODE:
        return "low"
    if pct[95] - pct[5] >= P.PULSE_SPREAD_CODES:
        return "pulsatile"
    return "damped"


def decode_segment(dat: Path, nsig: int, abp_index: int, frames: int, out: Path | None,
                   window: int, chunk_windows: int) -> dict:
    size = dat.stat().st_size
    if size != frames * nsig:
        raise ValueError(f"{dat.name}: size {size} != frames {frames} x nsig {nsig}")
    sums = [0] * nsig
    first = None
    hist: collections.Counter = collections.Counter()
    classes = collections.Counter()
    sha = hashlib.sha256()
    out_sha = hashlib.sha256()
    chunk_bytes = window * chunk_windows * nsig
    written = 0
    fo = open(out, "wb") if out is not None else None
    try:
        with open(dat, "rb") as f:
            while True:
                chunk = f.read(chunk_bytes)
                if not chunk:
                    break
                if len(chunk) % nsig:
                    raise ValueError(f"{dat.name}: partial frame")
                sha.update(chunk)
                for s in range(nsig):
                    col = chunk[s::nsig]
                    sums[s] += sum(col) - 128 * len(col)
                abp_raw = chunk[abp_index::nsig]
                abp = abp_raw.translate(XOR80)
                if first is None:
                    first = abp_raw[0] - 128
                if fo is not None:
                    fo.write(abp)
                out_sha.update(abp)
                written += len(abp)
                for w in range(0, len(abp_raw), window):
                    raw_counts = collections.Counter(abp_raw[w : w + window])
                    counts = collections.Counter({b - 128: c for b, c in raw_counts.items()})
                    hist.update(counts)
                    classes[classify_window(counts, min(window, len(abp_raw) - w))] += 1
    finally:
        if fo is not None:
            fo.close()
    if written != frames:
        raise ValueError(f"{dat.name}: wrote {written} != {frames}")
    checks = []
    for s in sums:
        c = s & 0xFFFF
        checks.append(c - 0x10000 if c >= 0x8000 else c)
    mode_code, mode_count = max(hist.items(), key=lambda kv: (kv[1], -kv[0]))
    return {
        "frames": frames,
        "checksums": checks,
        "first": first,
        "hist": hist,
        "classes": classes,
        "dat_sha256": sha.hexdigest(),
        "sample_sha256": out_sha.hexdigest(),
        "mode_code": mode_code,
        "mode_count": mode_count,
    }


def keep_decision(r: dict) -> tuple[bool, str]:
    n = r["frames"]
    inv = r["hist"].get(P.INVALID_CODE, 0)
    windows = sum(r["classes"].values())
    puls = r["classes"].get("pulsatile", 0)
    reasons = []
    if inv > P.MAX_INVALID_FRACTION * n:
        reasons.append(f"invalid fraction {inv / n:.4f} > {P.MAX_INVALID_FRACTION}")
    if r["mode_count"] > P.MAX_MODE_SHARE * n:
        reasons.append(f"mode share {r['mode_count'] / n:.4f} > {P.MAX_MODE_SHARE}")
    if puls < P.MIN_PULSATILE_WINDOW_FRACTION * windows:
        reasons.append(f"pulsatile windows {puls / windows:.4f} < {P.MIN_PULSATILE_WINDOW_FRACTION}")
    if len(r["hist"]) < P.MIN_DISTINCT_CODES:
        reasons.append(f"distinct codes {len(r['hist'])} < {P.MIN_DISTINCT_CODES}")
    outside = sum(c for code, c in r["hist"].items()
                  if code < P.MONITOR_MIN_CODE or code > P.MONITOR_MAX_CODE)
    if outside:
        reasons.append(f"codes outside monitor range {P.MONITOR_MIN_CODE}..{P.MONITOR_MAX_CODE}: {outside}")
    return (not reasons), "; ".join(reasons)


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="mimic_build_selftest_") as td:
        d = Path(td)
        window = 600
        exp = write_synth(d, window)
        seg, nsig, ai, frames = exp["segment"], exp["nsig"], exp["abp_index"], exp["frames"]
        h = parse_header((d / f"{seg}.hea").read_text())
        check_header(h, seg, nsig, frames, ai)
        out = d / "out.bin"
        r = decode_segment(d / f"{seg}.dat", nsig, ai, frames, out, window, chunk_windows=2)
        got = [b - 256 if b >= 128 else b for b in out.read_bytes()]
        assert got == exp["abp"], "self-test: ABP bytes differ"
        assert r["checksums"] == exp["checksums"] == [s["checksum"] for s in h["signals"]], "self-test: checksums"
        assert r["first"] == exp["abp"][0] == h["signals"][ai]["init"], "self-test: initial value"
        assert r["hist"].get(P.INVALID_CODE, 0) == exp["invalid_count"], "self-test: invalid count"
        order = []
        for w in range(0, frames, window):
            vals = exp["abp"][w : w + window]
            order.append(classify_window(collections.Counter(vals), len(vals)))
        assert order == exp["window_classes"], f"self-test: classes {order}"
        assert sum(r["classes"].values()) == len(order)
        # corrupted variants must be rejected
        dat = d / f"{seg}.dat"
        raw = bytearray(dat.read_bytes())
        raw[5 * nsig + ai] ^= 0x01
        dat.write_bytes(bytes(raw))
        r2 = decode_segment(dat, nsig, ai, frames, None, window, 2)
        assert r2["checksums"][ai] != h["signals"][ai]["checksum"], "self-test: corruption not detected"
        dat.write_bytes(bytes(raw[:-1]))
        try:
            decode_segment(dat, nsig, ai, frames, None, window, 2)
        except ValueError:
            pass
        else:
            raise AssertionError("self-test: truncated .dat accepted")
        bad = (d / f"{seg}.hea").read_text().replace("1.25(-100)/mmHg", "1.28(-109)/mmHg")
        try:
            check_header(parse_header(bad), seg, nsig, frames, ai)
        except ValueError:
            pass
        else:
            raise AssertionError("self-test: wrong ABP gain accepted")
    print("build self-test ok")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download-dir", required=True, type=Path)
    ap.add_argument("--samples-root", required=True, type=Path)
    ap.add_argument("--index", required=True, type=Path)
    ap.add_argument("--stats", required=True, type=Path)
    ap.add_argument("--data-root", required=True, type=Path)
    args = ap.parse_args()

    self_test()
    series_dir = args.samples_root / P.SERIES_ID
    series_dir.mkdir(parents=True, exist_ok=True)
    for stale in series_dir.glob("*"):
        stale.unlink()
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.stats.parent.mkdir(parents=True, exist_ok=True)

    rows, kept, excluded = [], [], []
    for seg in P.segment_rows():
        name = seg["segment"]
        recdir = args.download_dir / seg["record_dir"]
        h = parse_header((recdir / f"{name}.hea").read_text())
        check_header(h, name, seg["nsig"], seg["frames"], seg["abp_index"])
        a = h["signals"][seg["abp_index"]]
        if a["checksum"] != seg["abp_checksum"] or a["init"] != seg["abp_init"]:
            raise ValueError(f"{name}: ABP checksum/init differ from pins")
        tmp = series_dir / f"{name}.bin.part"
        r = decode_segment(recdir / f"{name}.dat", seg["nsig"], seg["abp_index"], seg["frames"], tmp,
                           P.WINDOW_FRAMES, P.CHUNK_WINDOWS)
        if r["dat_sha256"] != seg["dat_sha256"]:
            raise ValueError(f"{name}: .dat SHA-256 differs from pin")
        want = [s["checksum"] for s in h["signals"]]
        if r["checksums"] != want:
            raise ValueError(f"{name}: WFDB checksum mismatch {r['checksums']} != {want}")
        if r["first"] != a["init"]:
            raise ValueError(f"{name}: ABP initial value {r['first']} != header {a['init']}")
        ok, reason = keep_decision(r)
        n = r["frames"]
        hist = r["hist"]
        valid_keys = sorted(k for k in hist if k != P.INVALID_CODE)
        diag = {
            "invalid_sample_count": hist.get(P.INVALID_CODE, 0),
            "saturation_high_count": hist.get(P.MONITOR_MAX_CODE, 0),
            "saturation_low_count": hist.get(P.MONITOR_MIN_CODE, 0),
            "outside_monitor_range_count": sum(
                c for code, c in hist.items() if code < P.MONITOR_MIN_CODE or code > P.MONITOR_MAX_CODE),
            "distinct_codes": len(hist),
            "mode_code": r["mode_code"],
            "mode_share": round(r["mode_count"] / n, 6),
            **{f"windows_{c}": r["classes"].get(c, 0) for c in P.WINDOW_CLASSES},
        }
        if not ok:
            tmp.unlink()
            excluded.append({"segment": name, "record": seg["record"], "reason": reason, **diag})
            print(f"exclude {name}: {reason}")
            continue
        final = series_dir / f"{name}.bin"
        os.replace(tmp, final)
        kept.append(name)
        rows.append(
            {
                "dataset_id": P.DATASET_ID,
                "series_id": P.SERIES_ID,
                "sample_path": str(final.relative_to(args.data_root)),
                "numeric_kind": "int",
                "bit_width": 8,
                "endianness": "little",
                "element_size_bytes": 1,
                "sample_size_bytes": n,
                "value_count": n,
                "natural_record_kind": P.NATURAL_RECORD_KIND,
                "record": seg["record"],
                "segment": name,
                "source_dat": f"{seg['record_dir']}{name}.dat",
                "nsig": seg["nsig"],
                "abp_signal_index": seg["abp_index"],
                "sampling_hz": P.SAMPLING_HZ,
                "adc_gain_per_mmhg": P.ABP_GAIN,
                "adc_baseline": P.ABP_BASELINE,
                "units": "mmHg",
                "wfdb_checksum": a["checksum"],
                "wfdb_initial_value": a["init"],
                "min": min(hist),
                "max": max(hist),
                "valid_min": valid_keys[0],
                **diag,
                "sha256": r["sample_sha256"],
            }
        )
        print(f"kept {name}: {n} values, invalid {diag['invalid_sample_count']}, "
              f"pulsatile {diag['windows_pulsatile']}/{sum(r['classes'].values())}")
    with open(args.index, "w") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True) + "\n")
    total_values = sum(r["value_count"] for r in rows)
    vals = sorted(r["value_count"] for r in rows)
    stats = {
        "dataset_id": P.DATASET_ID,
        "series_id": P.SERIES_ID,
        "pinned_segments": len(P.SEGMENTS),
        "kept_segments": kept,
        "excluded_segments": excluded,
        "sample_count": len(rows),
        "total_values": total_values,
        "total_bytes": total_values,
        "median_values": vals[(len(vals) - 1) // 2] if vals else 0,
        "window_class_totals": {c: sum(r[f"windows_{c}"] for r in rows) for c in P.WINDOW_CLASSES},
        "invalid_sample_total": sum(r["invalid_sample_count"] for r in rows),
        "aggregate_sample_sha256": hashlib.sha256(
            "".join(f"{r['segment']}:{r['sha256']}\n" for r in rows).encode()
        ).hexdigest(),
    }
    args.stats.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n")
    if len(rows) < P.MIN_KEPT_SEGMENTS:
        raise SystemExit(f"only {len(rows)} segments kept (< {P.MIN_KEPT_SEGMENTS})")
    print(f"samples={len(rows)} values={total_values} excluded={len(excluded)} "
          f"aggregate_sha256={stats['aggregate_sample_sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
