#!/usr/bin/env python3
"""Synthetic end-to-end self-test for apss_ps.py and verify_apss.py.

Builds two small PDS-style CRLF CSV tables (10 Hz pressure with 0.2 Hz
temperature rows, blank-pressure rows, a few non-10 Hz rows), runs the real
build and verify code on a temporary data root, and checks the negative
paths (malformed decimals, too many non-10 Hz rows, wrong md5).
"""
import hashlib
import json
import os
import random
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import apss_ps  # noqa: E402

ID = apss_ps.DATASET_ID
SER = apss_ps.SERIES_ID


def make_csv(seed, n, blanks=(), non10=(), bad=None):
    rnd = random.Random(seed)
    lines = [apss_ps.HEADER]
    p = 700.0 + seed
    kept = []
    for i in range(n):
        p += rnd.uniform(-0.01, 0.01)
        ps = "%.4f" % (p if i != 5 else 1023.9999)
        aobt = "%.3f" % (633766638.3 + 0.1 * i)
        temp, tfq = ("%.4f" % (284.4 + 0.001 * i), "0.2") if i % 50 == 2 else ("", "")
        if i in blanks:
            ps_f, fq = "", ""
        elif i in non10:
            ps_f, fq = ps, "20.0"
        else:
            ps_f, fq = ps, "10.0"
            kept.append(ps)
        if bad is not None and i == bad:
            ps_f = ps + "1"
        lines.append(f"{aobt},{aobt},00420M00:00:00.022,00420 00:29:35,2020-031T18:17:32.837Z,"
                     f"{ps_f},{fq},{temp},{tfq}\r\n".encode())
    return b"".join(lines), kept


def write_inv(path, rows):
    with open(path, "w") as fh:
        fh.write("dir\tfile\tsol\tsize_bytes\tmd5\trecords\theader_bytes\tstart\tstop\n")
        for r in rows:
            fh.write("\t".join(str(r[k]) for k in ("dir", "file", "sol", "size_bytes", "md5", "records",
                                                     "header_bytes", "start", "stop")) + "\n")


def expect_fail(fn):
    try:
        fn()
    except apss_ps.RecipeError as e:
        return str(e)
    raise AssertionError("expected RecipeError")


def main():
    with tempfile.TemporaryDirectory(prefix="apss_selftest_") as td:
        root = Path(td) / "data"
        dl = root / "downloads" / ID / "csv"
        dl.mkdir(parents=True)
        rows, kept_all = [], {}
        for seed, blanks, non10 in ((1, {0, 77, 1500}, {10, 11}), (2, set(), set())):
            raw, kept = make_csv(seed, 3000, blanks, non10)
            name = f"ps_calib_{seed:04d}_01.csv"
            (dl / name).write_bytes(raw)
            rows.append({"dir": "sol_x", "file": name, "sol": seed, "size_bytes": len(raw),
                         "md5": hashlib.md5(raw).hexdigest(), "records": 3000,
                         "header_bytes": len(apss_ps.HEADER), "start": "s", "stop": "e"})
            kept_all[name] = kept
        inv = Path(td) / "files.tsv"
        write_inv(inv, rows)
        r = subprocess.run([sys.executable, str(HERE / "apss_ps.py"), "build", "--inventory", str(inv),
                            "--data-root", str(root)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        idx = [json.loads(l) for l in open(root / "index" / ID / "samples.jsonl")]
        assert len(idx) == 2
        total = 0
        for e in idx:
            b = (root / e["sample_path"]).read_bytes()
            vals = struct.unpack(f"<{len(b) // 4}f", b)
            want = kept_all[e["source_file"]]
            assert ["%.4f" % v for v in vals] == want, e["source_file"]
            assert e["value_count"] == len(want)
            total += len(b)
        e1 = [e for e in idx if e["sol"] == 1][0]
        assert e1["blank_pressure_rows"] == 3 and e1["non_10hz_rows"] == 2, e1
        assert e1["value_count"] == 3000 - 5
        assert abs(e1["max"] - 1023.9999) < 1e-4
        man = Path(td) / "manifest.toml"
        man.write_text(f'[[series]]\nid = "{SER}"\nrole = "primary"\nsample_count = 2\n'
                       f'total_size_bytes = {total}\n')
        r = subprocess.run([sys.executable, str(HERE / "verify_apss.py"), "--inventory", str(inv),
                            "--data-root", str(root), "--manifest", str(man)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr + r.stdout
        # verify must catch a tampered sample
        sp = root / idx[0]["sample_path"]
        b = bytearray(sp.read_bytes())
        b[8] ^= 1
        sp.write_bytes(bytes(b))
        r = subprocess.run([sys.executable, str(HERE / "verify_apss.py"), "--inventory", str(inv),
                            "--data-root", str(root), "--manifest", str(man)],
                           capture_output=True, text=True)
        assert r.returncode != 0 and "differ" in r.stderr, r.stderr
        # negative decode paths
        base = dict(rows[1])
        raw, _ = make_csv(3, 3000, bad=40)
        base.update(records=3000)
        msg = expect_fail(lambda: apss_ps.decode_csv(raw, base))
        assert "malformed PRESSURE" in msg, msg
        raw, _ = make_csv(4, 3000, non10=set(range(100, 200)))
        msg = expect_fail(lambda: apss_ps.decode_csv(raw, base))
        assert "non-10 Hz" in msg, msg
        raw, _ = make_csv(5, 2999)
        msg = expect_fail(lambda: apss_ps.decode_csv(raw, base))
        assert "records" in msg, msg
        bad = dl / rows[1]["file"]
        rb = dict(rows[1], md5="0" * 32)
        msg = expect_fail(lambda: apss_ps.check_bytes(bad, rb))
        assert "md5" in msg, msg
        # float32 lattice property used by the recipe: 4-dp values below 1024 round-trip
        rnd = random.Random(9)
        for _ in range(200000):
            v = rnd.randrange(1000000, 10240000) / 10000.0
            s = "%.4f" % v
            assert "%.4f" % struct.unpack("<f", struct.pack("<f", float(s)))[0] == s, s
    print("selftest ok")


if __name__ == "__main__":
    main()
