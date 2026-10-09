#!/usr/bin/env python3
"""Resolve the pinned CDIP DWR-M3 heave windows (windows.tsv).

Documentation of how windows.tsv was produced; download/build/verify never
run this. Network I/O is done with curl (subprocess, -g to disable URL
globbing of the OPeNDAP [a:1:b] hyperslab syntax). Usage:

    python3 -I scripts/discover.py --cache /tmp/autocollect/<id> --out windows.tsv

Algorithm (deterministic given the archive state):
1. Read the CDIP THREDDS archive catalog -> station directories (NNNp1).
2. Read each station catalog -> deployment files NNNp1_dMM.nc (the
   NNNp1_historic.nc aggregates are ignored).
3. Read each deployment .das and keep those whose NC_GLOBAL title says
   "collected in situ by Datawell DWR-M3 directional buoy" and whose license
   attribute is "These data may be redistributed and used without
   restriction."; read the .dds for xyzCount.
4. Per station, try DWR-M3 deployments in order of decreasing xyzCount (ties
   by file name), at most MAX_DEPLOYMENTS per station. For each:
   - fetch xyzStartTime, xyzSampleRate, xyzFilterDelay, waveTime,
     waveFlagPrimary; require xyzSampleRate == float32(1.28);
   - candidate window starts are wave-record start times at least
     SKIP_DAYS after the first wave record, such that the WINDOW_RECORDS
     half-hour wave records covering the window are consecutive (1800 s
     spacing) and all waveFlagPrimary == 1 (good);
   - xyz start index a = ceil((t0 - xyzStartTime + xyzFilterDelay) * rate)
     (inverse of the documented time formula), count N = WINDOW_VALUES;
   - confirm with the full xyzFlagPrimary/xyzFlagSecondary hyperslab:
     primary in {1 good, 2 not_evaluated} and secondary == 0 everywhere,
     plus a stride-16 xyzZDisplacement probe with no _FillValue, |z| < 30 m
     and non-constant values. On failure, skip past the failing time and
     retry (at most MAX_TRIES windows per deployment).
5. First confirmed window per station wins. One window per station; a
   deployment is never split.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import math
import os
import re
import struct
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdip_dods  # noqa: E402

BASE = "https://thredds.cdip.ucsd.edu/thredds"
WINDOW_SECONDS = 3 * 86400
RATE = struct.unpack(">f", struct.pack(">f", 1.28))[0]
WINDOW_VALUES = 331776  # 3 days * 86400 s * 1.28 Hz
WINDOW_RECORDS = WINDOW_SECONDS // 1800 + 1
SKIP_DAYS = 2
MAX_DEPLOYMENTS = 4
MAX_TRIES = 4
M3_PHRASE = "collected in situ by Datawell DWR-M3 directional buoy located near"
LICENSE = "These data may be redistributed and used without restriction."
FILL = struct.unpack(">f", struct.pack(">f", -999.99))[0]


def curl(url: str, dest: str | None = None, timeout: int = 600) -> bytes:
    if dest and os.path.exists(dest) and os.path.getsize(dest) > 0:
        with open(dest, "rb") as fh:
            return fh.read()
    for attempt in range(6):
        proc = subprocess.run(
            ["curl", "-g", "-sS", "--fail", "--max-time", str(timeout), url],
            capture_output=True,
        )
        if proc.returncode == 0:
            break
        time.sleep(5 * (attempt + 1))
    else:
        raise RuntimeError(f"curl failed for {url}: {proc.stderr.decode()[:300]}")
    if dest:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest + ".part", "wb") as fh:
            fh.write(proc.stdout)
        os.replace(dest + ".part", dest)
    return proc.stdout


def stations(cache: str) -> list[str]:
    xml = curl(f"{BASE}/catalog/cdip/archive/catalog.xml", f"{cache}/archive_catalog.xml").decode()
    return sorted(set(re.findall(r'xlink:href="(\d{3}p1)/catalog.xml"', xml)))


def deployments(cache: str, st: str) -> list[str]:
    xml = curl(f"{BASE}/catalog/cdip/archive/{st}/catalog.xml", f"{cache}/cats/{st}.xml").decode()
    return sorted(set(re.findall(rf'urlPath="(cdip/archive/{st}/{st}_d\d+\.nc)"', xml)))


def meta(cache: str, path: str) -> dict:
    name = os.path.basename(path)[:-3]
    das = curl(f"{BASE}/dodsC/{path}.das", f"{cache}/das/{name}.das").decode("utf-8", "replace")
    dds = curl(f"{BASE}/dodsC/{path}.dds", f"{cache}/dds/{name}.dds").decode("utf-8", "replace")
    title = re.search(r'String title "([^"]*)"', das)
    lic = re.search(r'String license "([^"]*)"', das)
    cnt = re.search(r"Float32 xyzZDisplacement\[xyzCount = (\d+)\]", dds)
    return {
        "path": path,
        "name": name,
        "title": title.group(1) if title else "",
        "license": lic.group(1) if lic else "",
        "xyz_count": int(cnt.group(1)) if cnt else 0,
    }


def dods(path: str, query: str) -> dict:
    return cdip_dods.parse(curl(f"{BASE}/dodsC/{path}.dods?{query}"))


def find_window(d: dict, log) -> dict | None:
    path, n = d["path"], d["xyz_count"]
    hdr = dods(path, "xyzStartTime,xyzSampleRate,xyzFilterDelay,waveTime,waveFlagPrimary")
    if hdr["xyzSampleRate"] != RATE:
        log(f"  {d['name']}: xyzSampleRate={hdr['xyzSampleRate']} != 1.28, skip")
        return None
    start, delay = hdr["xyzStartTime"], hdr["xyzFilterDelay"]
    wt = cdip_dods.unpack_be(*hdr["waveTime"])
    wf = hdr["waveFlagPrimary"]
    if len(wt) < WINDOW_RECORDS:
        return None
    earliest = wt[0] + SKIP_DAYS * 86400
    k = 0
    tries = 0
    while tries < MAX_TRIES:
        # next k satisfying the wave-record prefilter
        found = None
        run = 0
        for j in range(k, len(wt)):
            ok = wf[j] == 1 and (run == 0 or wt[j] - wt[j - 1] == 1800)
            if not ok:
                run = 0
                if wf[j] == 1:
                    run = 1
                continue
            run += 1
            if run >= WINDOW_RECORDS and wt[j - WINDOW_RECORDS + 1] >= earliest:
                found = j - WINDOW_RECORDS + 1
                break
        if found is None:
            return None
        t0 = wt[found]
        a = math.ceil((t0 - start + delay) * RATE)
        b = a + WINDOW_VALUES - 1
        if a < 0 or b >= n:
            return None
        tries += 1
        fl = dods(path, f"xyzFlagPrimary[{a}:1:{b}],xyzFlagSecondary[{a}:1:{b}]")
        fp, fs = fl["xyzFlagPrimary"], fl["xyzFlagSecondary"]
        bad = next((i for i in range(WINDOW_VALUES) if fp[i] not in (1, 2) or fs[i] != 0), None)
        if bad is None:
            zp = cdip_dods.unpack_be(*dods(path, f"xyzZDisplacement[{a}:16:{b}]")["xyzZDisplacement"])
            if all(v != FILL and abs(v) < 30 for v in zp) and len(set(zp)) > 50:
                return {
                    "a": a,
                    "t0": t0,
                    "flag_primary_good": sum(1 for x in fp if x == 1),
                    "zprobe_min": min(zp),
                    "zprobe_max": max(zp),
                }
            log(f"  {d['name']}: z probe rejected window at {a}")
            bad_t = t0 + WINDOW_SECONDS
        else:
            log(f"  {d['name']}: flag {fp[bad]}/{fs[bad]} at window offset {bad} (a={a})")
            bad_t = start - delay + (a + bad) / RATE
        k = next((j for j in range(found, len(wt)) if wt[j] > bad_t), len(wt))
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    log = lambda s: print(s, flush=True)  # noqa: E731
    sts = stations(args.cache)
    log(f"stations={len(sts)}")
    with cf.ThreadPoolExecutor(8) as ex:
        deps = [p for lst in ex.map(lambda s: deployments(args.cache, s), sts) for p in lst]
        log(f"deployment_files={len(deps)}")
        metas = list(ex.map(lambda p: meta(args.cache, p), deps))
    m3 = [m for m in metas if M3_PHRASE in m["title"] and m["xyz_count"] > 0]
    nolic = [m["name"] for m in m3 if m["license"] != LICENSE]
    if nolic:
        log(f"excluded (license string differs): {nolic}")
    m3 = [m for m in m3 if m["license"] == LICENSE]
    by_st: dict[str, list[dict]] = {}
    for m in m3:
        by_st.setdefault(m["name"][:5], []).append(m)
    log(f"dwr_m3_deployments={len(m3)} stations_with_m3={len(by_st)}")

    def per_station(st: str):
        lines = []
        cands = sorted(by_st[st], key=lambda m: (-m["xyz_count"], m["name"]))[:MAX_DEPLOYMENTS]
        for d in cands:
            w = find_window(d, lines.append)
            if w:
                site = re.search(r"located near (.*?) from \d", d["title"])
                return st, d, w, (site.group(1) if site else ""), lines
        return st, None, None, "", lines

    rows = []
    with cf.ThreadPoolExecutor(4) as ex:
        for st, d, w, site, lines in ex.map(per_station, sorted(by_st)):
            for ln in lines:
                log(ln)
            if d is None:
                log(f"{st}: no qualifying window")
                continue
            log(f"{st}: {d['name']} a={w['a']} t0={w['t0']}")
            rows.append((st, d["name"], d["path"], d["xyz_count"], w["a"], WINDOW_VALUES, w["t0"], site))
    with open(args.out, "w") as fh:
        fh.write("station\tdeployment\turl_path\txyz_count\tstart_index\tvalue_count\twindow_start_unix\tsite\n")
        for r in rows:
            fh.write("\t".join(str(x) for x in r) + "\n")
    log(f"windows={len(rows)} written to {args.out}")


if __name__ == "__main__":
    main()
