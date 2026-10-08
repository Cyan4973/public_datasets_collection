#!/usr/bin/env python3
"""Independent verifier for zenodo_m3d_iwr6843_radar_adc_i16.

Does not import m3d_zip/m3d_tool. For every pinned capture it re-reads the
downloaded ZIP member range, parses the local header, inflates the member in
one shot, checks size and CRC-32, re-checks conf_file.cfg (exact profile,
3-TX chirps, 100 ms frames) and the DCA1000 log, strips the 64-byte HSI
header of every 1088-byte chirp record, and requires the re-derived payload to
equal the emitted sample byte-for-byte. It then recomputes value statistics,
rejects degenerate samples, and checks the index and manifest totals.
"""

from __future__ import annotations

import argparse
import array
import hashlib
import json
import re
import struct
import sys
import tomllib
import zlib
from pathlib import Path

DATASET_ID = "zenodo_m3d_iwr6843_radar_adc_i16"
SERIES_ID = "m3d_iwr6843_hsi_adc_iq_i16"
EXPECTED_SAMPLES = 16
MAGIC = struct.pack("<II", 0x0CDA0ADC, 0x0CDA0ADC)
HEADER_HEX = ("dc0ada0cdc0ada0c" "3004" "0000" "0000" "0000" "8007" "2000" "0402" "0002"
              "0f01" "0100" "8000" + "00" * 22 + "0f" * 12)
PROFILE = "profileCfg 0 61.2 60 17 50 657930 0 55.27 1 64 2000 2 1 36"
CHIRPS = ["chirpCfg 0 0 0 0 0 0 0 1", "chirpCfg 1 1 0 0 0 0 0 2", "chirpCfg 2 2 0 0 0 0 0 4"]
OTHER = ["channelCfg 15 7 0", "adcCfg 2 1", "adcbufCfg -1 0 1 1 1", "lvdsStreamCfg -1 1 1 1"]
SLOP = 512
CD_OFFSET = 3_712_592_250


def fail(msg: str) -> None:
    sys.exit(f"VERIFY FAIL: {msg}")


def check_cfg(text: str, loops: int, key: str) -> None:
    lines = [ln.strip() for ln in text.splitlines()]
    prof = [ln for ln in lines if ln.startswith("profileCfg")]
    if prof != [PROFILE]:
        fail(f"{key}: profileCfg {prof}")
    if [ln for ln in lines if ln.startswith("chirpCfg")] != CHIRPS:
        fail(f"{key}: chirpCfg lines differ")
    for o in OTHER:
        if o not in lines:
            fail(f"{key}: missing '{o}'")
    fr = [ln.split() for ln in lines if ln.startswith("frameCfg")]
    if len(fr) != 1 or len(fr[0]) != 8:
        fail(f"{key}: frameCfg {fr}")
    f = fr[0]
    # frameCfg chirpStart chirpEnd numLoops numFrames periodicity_ms trigger delay
    if (f[1], f[2], f[4], f[6], f[7]) != ("0", "2", "0", "1", "0") or float(f[5]) != 100.0:
        fail(f"{key}: frameCfg not 0..2 / 100 ms: {f}")
    if int(f[3]) != loops:
        fail(f"{key}: loops {f[3]} != pinned {loops}")


def check_log(text: str, chirps: int, key: str) -> None:
    sec = text.split("0ADC Header Data :", 1)
    if len(sec) != 2:
        fail(f"{key}: log has no 0ADC section")
    body = sec[1].split("Header Data", 1)[0]
    vals = dict(re.findall(r"^([A-Za-z][A-Za-z ]+?)\s+-\s+(\d+)\s*$", body, re.M))
    want = {"Out of sequence count": 0, "Number of zero filled packets": 0,
            "Number of zero filled bytes": 0, "Number of received packets": chirps,
            "Last Packet ID": chirps}
    for k, v in want.items():
        if int(vals.get(k, -1)) != v:
            fail(f"{key}: log {k}={vals.get(k)} expected {v}")


def rederive(range_file: Path, name: str, csize: int, usize: int, crc: int) -> bytes:
    blob = range_file.read_bytes()
    sig, _v, flags, method, _t, _d, _c, _cs, _us, fnl, exl = struct.unpack_from("<IHHHHHIIIHH", blob, 0)
    if sig != 0x04034B50 or method != 8 or flags & 1:
        fail(f"{range_file.name}: bad local header")
    if blob[30:30 + fnl] != name.encode():
        fail(f"{range_file.name}: local name mismatch")
    start = 30 + fnl + exl
    if start + csize > len(blob):
        fail(f"{range_file.name}: short range")
    d = zlib.decompressobj(-15)
    raw = d.decompress(blob[start:start + csize]) + d.flush()
    if not d.eof or d.unused_data:
        fail(f"{range_file.name}: DEFLATE boundary")
    if len(raw) != usize or zlib.crc32(raw) != crc:
        fail(f"{range_file.name}: size/CRC-32 mismatch")
    return raw


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--selection", required=True)
    ap.add_argument("--download-dir", required=True)
    ap.add_argument("--data-root", required=True)
    a = ap.parse_args()
    data_root = Path(a.data_root)
    dl = Path(a.download_dir)
    header = bytes.fromhex(HEADER_HEX)
    if len(header) != 64 or header[:8] != MAGIC:
        fail("internal header constant")

    lines = Path(a.selection).read_text().splitlines()
    cols = lines[0].split("\t")
    sel = [dict(zip(cols, ln.split("\t"))) for ln in lines[1:]]
    if len(sel) != EXPECTED_SAMPLES:
        fail(f"selection has {len(sel)} rows")

    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(ln) for ln in index_path.read_text().splitlines() if ln.strip()]
    by_path = {r["sample_path"]: r for r in rows}
    if len(rows) != EXPECTED_SAMPLES or len(by_path) != len(rows):
        fail(f"index rows {len(rows)}")

    total_bytes = 0
    loops_seen = set()
    for s in sel:
        key = f"{s['session']}_{s['capture']}"
        loops, chirps = int(s["frame_loops"]), int(s["chirps"])
        meta = dl / "meta"
        check_cfg((meta / s["cfg_name"].split("/", 1)[1].replace("/", "__")).read_text(), loops, key)
        check_log((meta / s["log_name"].split("/", 1)[1].replace("/", "__")).read_text(errors="replace"),
                  chirps, key)
        rf = dl / "ranges" / f"{key}.zipmember"
        lho, csize = int(s["bin_lho"]), int(s["bin_csize"])
        exp_len = min(lho + 30 + len(s["bin_name"].encode()) + csize + SLOP, CD_OFFSET) - lho
        if rf.stat().st_size != exp_len:
            fail(f"{key}: range file size {rf.stat().st_size} != {exp_len}")
        raw = rederive(rf, s["bin_name"], csize, int(s["bin_usize"]), int(s["bin_crc32"]))
        if len(raw) != chirps * 1088:
            fail(f"{key}: {len(raw)} bytes is not {chirps} x 1088")
        hdr_set = {raw[o:o + 64] for o in range(0, len(raw), 1088)}
        if hdr_set != {header}:
            fail(f"{key}: {len(hdr_set)} distinct HSI headers / mismatch")
        payload = b"".join(raw[o + 64:o + 1088] for o in range(0, len(raw), 1088))
        del raw
        rel = f"samples/{DATASET_ID}/{SERIES_ID}/{key}.bin"
        sample = (data_root / rel).read_bytes()
        if sample != payload:
            fail(f"{key}: sample bytes differ from re-derived payload")
        r = by_path.get(rel)
        if r is None:
            fail(f"{key}: not in index")
        vals = array.array("h")
        vals.frombytes(sample)
        if sys.byteorder != "little":
            vals.byteswap()
        lo, hi = min(vals), max(vals)
        distinct = len(set(vals))
        zero_chirps = sum(1 for o in range(0, len(sample), 1024) if not sample[o:o + 1024].strip(b"\0"))
        zero_frac = vals.count(0) / len(vals)
        if lo == hi or distinct < 1000:
            fail(f"{key}: degenerate (min={lo} max={hi} distinct={distinct})")
        if zero_chirps * 100 >= chirps or zero_frac > 0.05:
            fail(f"{key}: zero_chirps={zero_chirps} zero_frac={zero_frac:.4f}")
        if lo == -32768 and hi == 32767:
            fail(f"{key}: full-scale both ways")
        want = {"dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "int",
                "bit_width": 16, "endianness": "little", "element_size_bytes": 2,
                "sample_size_bytes": len(sample), "value_count": len(sample) // 2,
                "min": lo, "max": hi, "chirps": chirps, "frame_loops": loops,
                "sha256": hashlib.sha256(sample).hexdigest()}
        for k, v in want.items():
            if r.get(k) != v:
                fail(f"{key}: index {k}={r.get(k)} expected {v}")
        loops_seen.add(loops)
        total_bytes += len(sample)
        print(f"ok {key} loops={loops} chirps={chirps} values={len(vals)} min={lo} max={hi} "
              f"distinct={distinct} zero_frac={zero_frac:.5f}")

    out_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    files = sorted(p.name for p in out_dir.iterdir())
    if len(files) != EXPECTED_SAMPLES:
        fail(f"sample dir holds {len(files)} files")
    if loops_seen != {48, 64}:
        fail(f"loops {loops_seen}")
    man = tomllib.loads(Path(a.manifest).read_text())
    ser = [x for x in man["series"] if x["id"] == SERIES_ID]
    if len(ser) != 1 or ser[0]["sample_count"] != EXPECTED_SAMPLES or ser[0]["total_size_bytes"] != total_bytes:
        fail(f"manifest totals disagree (realized {EXPECTED_SAMPLES} samples, {total_bytes} bytes)")
    if total_bytes > 1_000_000_000:
        fail("primary output above 1 GB")
    print(f"VERIFY OK samples={EXPECTED_SAMPLES} bytes={total_bytes} values={total_bytes // 2}")


if __name__ == "__main__":
    main()
