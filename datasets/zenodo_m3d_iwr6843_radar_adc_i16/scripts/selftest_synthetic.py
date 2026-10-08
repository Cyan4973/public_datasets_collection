#!/usr/bin/env python3
"""Synthetic end-to-end self-test of the M3D parsers (no network).

Builds a small DEFLATE ZIP with the same member layout as dataset_260917.zip
(conf_file.cfg, LogFile.csv, legend, HSI .bin captures, plus decoys with a
different profile and a capture without cfg), then runs the central-directory
parser, small-member extraction, selection derivation, build and the
independent verifier on it, and checks the emitted samples equal the known
payloads. Also checks that a corrupted header and a wrong CRC are rejected.
Run from a scratch directory: python3 -I selftest_synthetic.py <workdir>
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import random
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import m3d_tool as mt  # noqa: E402
import m3d_zip as mz  # noqa: E402
import verify_samples as vs  # noqa: E402

CFG = """sensorStop
flushCfg
dfeDataOutputMode 1
channelCfg 15 7 0
adcCfg 2 1
adcbufCfg -1 0 1 1 1
profileCfg 0 61.2 60 17 50 657930 0 55.27 1 64 2000 2 1 36
chirpCfg 0 0 0 0 0 0 0 1
chirpCfg 1 1 0 0 0 0 0 2
chirpCfg 2 2 0 0 0 0 0 4
frameCfg 0 2 {loops} 0 {period} 1 0
lowPower 0 0
lvdsStreamCfg -1 1 1 1
sensorStart"""

LOG = """Start record configuration : \n,\nLog mode : Multi\n\n0ADC Header Data :
Out of sequence count - 0
Out of sequence seen from 0 to 0
First Packet ID - 1
Last Packet ID - {n}
Number of received packets - {n}
Number of zero filled packets - 0
Number of zero filled bytes - 0
Duration(sec) - 3

0CC9 Header Data :
Out of sequence count - 0
Number of received packets - 7
"""


def payloads(rng: random.Random, n: int) -> bytes:
    out = bytearray()
    for _ in range(n):
        out += b"".join(rng.randint(-4000, 4000).to_bytes(2, "little", signed=True) for _ in range(512))
    return bytes(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    w = Path(ap.parse_args().workdir).resolve()
    w.mkdir(parents=True, exist_ok=True)
    assert bytes.fromhex(vs.HEADER_HEX) == mz.HSI_HEADER, "verifier/library header constants differ"
    rng = random.Random(7)
    caps = {("260729", "00"): (48, 100, 30), ("260729", "01"): (64, 100, 25),
            ("260729", "02"): (48, 120, 20), ("260730", "00"): (48, 100, 12)}
    expected = {}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("dataset_260917/", b"")
        for s in ("260729", "260730"):
            z.writestr(f"dataset_260917/{s}/{s}_legend.txt", "00 one person walking \n01 squats\n02 x\n")
        for (s, c), (loops, period, n) in caps.items():
            base = f"dataset_260917/{s}/{c}/"
            z.writestr(base + "conf_file.cfg", CFG.format(loops=loops, period=period))
            z.writestr(base + "datacard_record_hdr_LogFile.csv", LOG.format(n=n))
            pl = payloads(rng, n)
            if period == 100:
                expected[f"{s}_{c}"] = pl
            raw = b"".join(mz.HSI_HEADER + pl[k * 1024:(k + 1) * 1024] for k in range(n))
            z.writestr(base + "datacard_record_hdr_0ADC_0.bin", raw)
        z.writestr("dataset_260917/260730/05/datacard_record_hdr_0ADC_0.bin", mz.HSI_HEADER + bytes(1024))
        z.writestr("dataset_260917/260730/05/datacard_record_hdr_LogFile.csv", LOG.format(n=1))
    blob = buf.getvalue()
    eocd = blob.rfind(b"PK\x05\x06")
    cd_size = int.from_bytes(blob[eocd + 12:eocd + 16], "little")
    cd_off = int.from_bytes(blob[eocd + 16:eocd + 20], "little")
    n_ent = int.from_bytes(blob[eocd + 10:eocd + 12], "little")
    mz.ZIP_SIZE, mz.CD_OFFSET, mz.CD_SIZE, mz.CD_ENTRIES = len(blob), cd_off, cd_size, n_ent
    mz.CD_SHA256 = hashlib.sha256(blob[cd_off:cd_off + cd_size]).hexdigest()
    vs.CD_OFFSET = cd_off
    vs.EXPECTED_SAMPLES = len(expected)

    data = w / "data"
    dl = data / "downloads" / mt.DATASET_ID
    meta, ranges = dl / "meta", dl / "ranges"
    for p in (meta, ranges):
        p.mkdir(parents=True, exist_ok=True)
    tail_start = max(0, len(blob) - 65536)
    (dl / "tail.bin").write_bytes(blob[tail_start:])
    mt.cmd_parse_cd(SimpleNamespace(tail=str(dl / "tail.bin"), tail_start=tail_start, out=str(dl / "cd.tsv")))
    cd = mt.read_cd(dl / "cd.tsv")
    for name, e in cd.items():
        if mt._is_small(name):
            end = min(e["lho"] + 30 + len(name.encode()) + e["csize"] + mt.SMALL_SLOP, cd_off) - 1
            rf = w / "small.range"
            rf.write_bytes(blob[e["lho"]:end + 1])
            mt.cmd_extract_small(SimpleNamespace(cd=str(dl / "cd.tsv"), name=name, range_file=str(rf),
                                                 out=str(meta / mt.local_name(name))))
    sel = dl / "derived_selection.tsv"
    mt.cmd_derive(SimpleNamespace(cd=str(dl / "cd.tsv"), meta_dir=str(meta), out=str(sel)))
    rows = mt.read_sel(sel)
    assert sorted(f"{r['session']}_{r['capture']}" for r in rows) == sorted(expected), rows
    for r in rows:
        s, e = mt.bin_range(r)
        (ranges / f"{r['session']}_{r['capture']}.zipmember").write_bytes(blob[s:e + 1])
    mt.cmd_check_bin(SimpleNamespace(selection=str(sel), key=f"{rows[0]['session']}_{rows[0]['capture']}",
                                     range_file=str(ranges / f"{rows[0]['session']}_{rows[0]['capture']}.zipmember")))
    samples = data / "samples" / mt.DATASET_ID
    index = data / "index" / mt.DATASET_ID / "samples.jsonl"
    mt.cmd_build(SimpleNamespace(selection=str(sel), meta_dir=str(meta), ranges_dir=str(ranges),
                                 samples_dir=str(samples), index=str(index),
                                 stats=str(data / "filtered" / "stats.json"), data_root=str(data)))
    for key, pl in expected.items():
        got = (samples / mt.SERIES_ID / f"{key}.bin").read_bytes()
        assert got == pl, f"payload mismatch {key}"
    total = sum(len(p) for p in expected.values())
    man = w / "manifest.toml"
    man.write_text(f'[[series]]\nid = "{mt.SERIES_ID}"\nsample_count = {len(expected)}\n'
                   f"total_size_bytes = {total}\n")
    # The verifier needs the loop set {48, 64}; the synthetic selection has both.
    sys.argv = ["verify", "--manifest", str(man), "--selection", str(sel),
                "--download-dir", str(dl), "--data-root", str(data)]
    vs.main()

    # Negative tests: corrupted HSI header and CRC mismatch must be fatal.
    r0 = rows[0]
    key0 = f"{r0['session']}_{r0['capture']}"
    bad_rows = dict(r0)
    bad_rows["bin_crc32"] ^= 1
    try:
        mt.stream_capture(ranges / f"{key0}.zipmember", bad_rows, lambda p: None)
        raise AssertionError("CRC mismatch not detected")
    except mz.FormatError as exc:
        print("negative ok:", exc)
    try:
        mz.split_hsi([mz.HSI_HEADER + bytes(1024), b"\x00" * 64 + bytes(1024)], lambda p: None)
        raise AssertionError("header mismatch not detected")
    except mz.FormatError as exc:
        print("negative ok:", exc)
    try:
        mz.split_hsi([mz.HSI_HEADER + bytes(1000)], lambda p: None)
        raise AssertionError("partial record not detected")
    except mz.FormatError as exc:
        print("negative ok:", exc)
    assert mz.cfg_frame_loops(CFG.format(loops=48, period=120)) is None
    assert mz.cfg_frame_loops(CFG.format(loops=48, period=100).replace(" 64 2000 ", " 96 2000 ")) is None
    print("SELFTEST OK", json.dumps({k: len(v) for k, v in expected.items()}))


if __name__ == "__main__":
    main()
