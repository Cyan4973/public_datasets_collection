#!/usr/bin/env python3
"""End-to-end synthetic self-test for sevenzip.py + oscgrid.py.

Generates 21 synthetic COMTRADE-1999 cfg/dat pairs (good records plus one per
drop rule, a current-only record, a constant-voltage record and a duplicate),
packs them into an LZMA1 7z with bsdtar (a test fixture only, not a build
dependency), then checks: container members byte-identical, expected drop set,
emitted channel-major int16 bytes, constant/duplicate skips, verify() passes,
and verify() detects a flipped sample byte. Runs in a temporary directory.
"""
import argparse, array, hashlib, json, math, random, shutil, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import oscgrid, sevenzip

rng = random.Random(7)
root = Path(tempfile.mkdtemp(prefix="oscgrid_selftest_"))
src = root / "src" / "Labeled_raw_v1.1"; src.mkdir(parents=True)

def stem(i): return hashlib.md5(f"rec{i}".encode()).hexdigest()

def analog_line(k, name, ph, unit, a, b, lo=-32768, hi=32767):
    return f"{k}, {name}, {ph}, , {unit}, {a}, {b}, 0, {lo}, {hi}, 100, 1, S"

def make(i, kind="good"):
    # (name, phase, unit, a): realistic VT/CT scales plus an off-band sensitive
    # earth-fault current input (a=0.0024) and an off-band voltage input.
    chans = [("U | BusBar-1 | phase: A","A","V",0.0165),("I | Bus-1 | phase: A","A","A",0.0092),
             ("U | CableLine-2 | phase: AB","AB","В",0.0153),("U_raw | BusBar-1 | phase: B","B","V",0.0165),
             ("I | Bus-1 | phase: N","N","А",0.0093),("I | dif-1 | phase: A","","p.u.",0.001),
             ("I | Bus-2 | phase: N","N","A",0.0024),("U | BusBar-2 | phase: C","C","V",1.6e-05)]
    if kind == "current_only":
        chans = [("I | Bus-1 | phase: A","A","A",0.0092),("I | Bus-1 | phase: B","B","A",0.0091)]
    n = rng.randint(40, 90)
    lo = -32767 if kind == "minus32767" else -32768
    rev = "2013" if kind == "rev2013" else "1999"
    ft = "FLOAT32" if kind == "rev2013" else "ASCII"
    samp = "1200" if kind == "rate1200" else "1600"
    digital = ["MLsignal_1_2", "IFB | Bus-1 | open"]
    lines = [", , " + rev, f"{len(chans)+len(digital)}, {len(chans)}A, {len(digital)}D"]
    for k, (nm, ph, u, a) in enumerate(chans, 1):
        lines.append(analog_line(k, nm, ph, u, a, -0.0003, lo, 32767))
    for k, nm in enumerate(digital, 1):
        lines.append(f"{k}, {nm}, A, , 0")
    lines += ["50", "1", f"{samp}, {n}", "01/01/0001, 01:01:01.000000", "01/01/0001, 01:01:01.000000", ft, "1"]
    cfg = "\r\n".join(lines) + "\r\n"
    cols = [[int(rng.gauss(0, 3000)) if c % 3 else int(8000 * math.sin(r / 5.0 + c)) for r in range(n)] for c in range(len(chans))]
    for c in cols:
        for r in range(n): c[r] = max(lo, min(32767, c[r]))
    if kind == "flatvolt":
        for c, (nm, _, _, _) in zip(cols, chans):
            if nm.startswith("U |"):
                for r in range(n): c[r] = 5
    rows = []
    for r in range(n):
        toks = []
        for c in range(len(chans)):
            v = cols[c][r]
            if rng.random() < 0.05:
                tok = repr(v + (1e-13 if v >= 0 else -1e-13)) if v != 0 else "0.0"
            else:
                tok = str(v)
            toks.append(tok)
        t = r * 625
        if kind == "badts" and r == 10: t += 1
        if kind == "nonint" and r == 5: toks[1] = "12.5"
        if kind == "missing" and r == 7: toks[0] = "99999"
        if kind == "minus32767" and r == 3: toks[1] = "-32768"
        if kind == "excl_nonint" and r == 4: toks[3] = "3.25"
        rows.append(",".join([str(r+1), str(t)] + toks + [str(rng.randint(0,1)), "0"]))
    if kind == "short": rows = rows[:-1]
    dat = "\r\n".join(rows)
    s = stem(i)
    (src / f"{s}.cfg").write_text(cfg, encoding="utf-8")
    (src / f"{s}.dat").write_text(dat, encoding="ascii")
    return s, kind, chans, cols, n

kinds = ["good"]*10 + ["current_only", "flatvolt", "rev2013", "rate1200", "badts", "nonint", "missing", "minus32767", "excl_nonint", "short"]
recs = [make(i, k) for i, k in enumerate(kinds)]
# duplicate record content under a different stem
dup_src = recs[0][0]; dup = stem(999)
shutil.copy(src / f"{dup_src}.cfg", src / f"{dup}.cfg"); shutil.copy(src / f"{dup_src}.dat", src / f"{dup}.dat")
arc = root / "synth.7z"
subprocess.run(["bsdtar", "--format", "7zip", "--options", "7zip:compression=lzma1", "-cf", str(arc.resolve()), "Labeled_raw_v1.1"], cwd=root/"src", check=True)
read, size = sevenzip.file_reader(str(arc))
a = sevenzip.open_archive(read, size)
print("synthetic archive", size, "folders", len(a.streams.folders), [f.coder.method.hex() for f in a.streams.folders], "entries", len(a.entries))
# container check: every member equals the source bytes
n_ok = 0
for e, content in sevenzip.iter_members(read, a):
    assert content == (root/"src"/e.name).read_bytes(), e.name; n_ok += 1
print("container members byte-identical:", n_ok)

oscgrid.ARCHIVE_SIZE = size
oscgrid.EXPECTED_PAIRS = len(kinds) + 1
oscgrid.EXPECTED_FOLDER_UNPACK = a.streams.folders[0].unpack_size
oscgrid.MAX_DROPPED_RECORDS = 100
oscgrid.MIN_MEDIAN_VALUES = 10
data = root / "data"
ns = argparse.Namespace(archive=str(arc), samples_dir=str(data/"samples/x"), index=str(data/"index/x/samples.jsonl"),
                        stats=str(data/"filtered/x/stats.json"), data_root=str(data), manifest=None)
oscgrid.build(ns)
stats = json.loads(Path(ns.stats).read_text())
rows = [json.loads(l) for l in Path(ns.index).read_text().splitlines()]
# expected drops
exp_drop = {s for s, k, *_ in recs if k in ("rev2013","rate1200","badts","nonint","missing","minus32767","excl_nonint","short")}
assert {d["record"] for d in stats["dropped"]} == exp_drop, stats["drop_reasons"]
print("drop reasons", stats["drop_reasons"])
# expected outputs
by = {(r["series_id"], r["record"]): r for r in rows}
for s, k, chans, cols, n in recs:
    if s in exp_drop: continue
    for series, pred in (("oscgrid_voltage_codes_i16", lambda nm, a: nm.startswith("U | ") and 0.0136 <= a <= 0.0184),
                         ("oscgrid_current_codes_i16", lambda nm, a: nm.startswith("I | Bus-") and 0.00782 <= a <= 0.01058)):
        idx = [j for j, (nm, _, _, a) in enumerate(chans) if pred(nm, a)]
        exp = array.array("h")
        for j in idx: exp.extend(cols[j])
        key = (series, s)
        if not idx or min(exp) == max(exp):
            assert key not in by, key; continue
        got = (data / by[key]["sample_path"]).read_bytes()
        assert got == exp.tobytes(), key
        assert by[key]["shape"] == [len(idx), n]
assert ("oscgrid_voltage_codes_i16", dup) not in by and stats["skipped_duplicate_samples"], "duplicate not skipped"
print("emitted", len(rows), "skipped_constant", stats["skipped_constant_samples"], "dups", len(stats["skipped_duplicate_samples"]))
print("excluded", stats["excluded_channel_reasons"], "units", stats["kept_channel_units"], "artifacts", stats["float_artifact_tokens"], stats["max_integral_deviation"])
# manifest for verify
tot = {}
for r in rows:
    t = tot.setdefault(r["series_id"], [0, 0]); t[0] += 1; t[1] += r["sample_size_bytes"]
man = root / "manifest.toml"
man.write_text("".join(f'[[series]]\nid = "{sid}"\nsample_count = {c}\ntotal_size_bytes = {b}\n' for sid, (c, b) in tot.items()))
ns.manifest = str(man)
oscgrid.verify(ns)
# tamper test: flip one sample byte -> verify must fail
p = data / rows[0]["sample_path"]; b = bytearray(p.read_bytes()); b[0] ^= 1; p.write_bytes(bytes(b))
try:
    oscgrid.verify(ns); print("TAMPER NOT DETECTED"); sys.exit(1)
except SystemExit as e:
    print("tamper detected:", e)
shutil.rmtree(root)
print("SELFTEST OK")
