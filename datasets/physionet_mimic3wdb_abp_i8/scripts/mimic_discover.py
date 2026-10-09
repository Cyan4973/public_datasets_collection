#!/usr/bin/env python3
"""Author-time discovery of the pinned MIMIC-III waveform segments.

Not run by download.sh, build.sh or verify.sh. It documents how the segment
list in mimic_pins.py was resolved, and can be re-run to reproduce it:

  python3 -I mimic_discover.py --cache /tmp/x/cache --out /tmp/x/pins.json

Procedure (network I/O through the curl CLI, small text files only):
  1. Fetch RECORDS-adults (pinned by size and SHA-256).
  2. Walk its record directories in file order. Skip a record when its
     RECORDS list names no waveform record (numerics only), when its master
     header says '# Location: nicu', or when its layout header's ABP line is
     absent or not at gain 1.25/mmHg (a cheap prefilter; the layout header
     carries one calibration per signal name).
  3. Visit the record's segments of at least MIN_FRAMES frames in
     master-header (chronological) order (gaps '~' and the zero-length layout
     segment ignored), fetch each segment header, and keep the first one that
     qualifies: 125 Hz, every signal format 80 in the single file <seg>.dat
     with one sample per frame, and exactly one signal named ABP with gain
     string '1.25(-100)/mmHg', 8-bit ADC resolution and ADC zero 0. At most
     one segment per record.
  4. Stop after N_SEGMENTS records have contributed a segment.
  5. Resolve the SHA-256 of each kept .hea and .dat from the release
     SHA256SUMS.txt (639 MB, path-sorted) by binary search over HTTP range
     requests; the .dat size comes from the record directory listing and must
     equal frames x nsig.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = "https://physionet.org/files/mimic3wdb/1.0"
SUMS_URL = BASE + "/SHA256SUMS.txt"
SUMS_BYTES = 639425652
MIN_FRAMES = 500_000
N_SEGMENTS = 60
ABP_GAIN = "1.25(-100)/mmHg"


def curl(url: str, rng: str | None = None) -> bytes:
    cmd = ["curl", "-fsSL", "--retry", "5", "--retry-delay", "3", "--max-time", "120"]
    if rng:
        cmd += ["-r", rng]
    cmd.append(url)
    return subprocess.run(cmd, check=True, capture_output=True).stdout


def cached(cache: Path, rel: str) -> bytes:
    path = cache / rel
    if path.exists():
        return path.read_bytes()
    data = curl(f"{BASE}/{rel}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def parse_master(text: str):
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    head = lines[0].split()
    if "/" not in head[0]:
        return None
    segs = []
    for ln in lines[1:]:
        name, length = ln.split()[:2]
        segs.append((name, int(length)))
    return segs


def parse_segment(text: str):
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    head = lines[0].split()
    rec, nsig, freq, nframes = head[0], int(head[1]), head[2], int(head[3])
    sigs = []
    for ln in lines[1 : 1 + nsig]:
        f = ln.split()
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
    return rec, nsig, freq, nframes, sigs


def qualifies(seg_name: str, text: str):
    rec, nsig, freq, nframes, sigs = parse_segment(text)
    if rec != seg_name or freq != "125" or len(sigs) != nsig or nframes < MIN_FRAMES:
        return None
    if any(s["fmt"] != "80" or s["file"] != f"{seg_name}.dat" for s in sigs):
        return None
    abp = [i for i, s in enumerate(sigs) if s["name"] == "ABP"]
    if len(abp) != 1:
        return None
    s = sigs[abp[0]]
    if s["gain"] != ABP_GAIN or s["adcres"] != "8" or s["adczero"] != "0":
        return None
    return {
        "segment": seg_name,
        "nsig": nsig,
        "frames": nframes,
        "abp_index": abp[0],
        "abp_init": s["init"],
        "abp_checksum": s["checksum"],
        "signal_names": [x["name"] for x in sigs],
    }


def listing_size(cache: Path, recdir: str, fname: str) -> int:
    html = cached(cache, recdir + "index.html") if (cache / (recdir + "index.html")).exists() else None
    if html is None:
        html = curl(f"{BASE}/{recdir}")
        (cache / recdir).mkdir(parents=True, exist_ok=True)
        (cache / (recdir + "index.html")).write_bytes(html)
    m = re.search(rf'>{re.escape(fname)}</a>\s+\S+\s+\S+\s+(\d+)', html.decode())
    if not m:
        raise SystemExit(f"no listing size for {recdir}{fname}")
    return int(m.group(1))


def sums_line_at(offset: int, span: int = 4096):
    """Return (start_offset, list of (path, sha)) of full lines in a window."""
    end = min(SUMS_BYTES - 1, offset + span - 1)
    chunk = curl(SUMS_URL, f"{offset}-{end}").decode()
    start = 0
    if offset > 0:
        start = chunk.index("\n") + 1
    out = []
    pos = start
    while True:
        nl = chunk.find("\n", pos)
        if nl < 0:
            break
        sha, path = chunk[pos:nl].split(" ", 1)
        out.append((path.strip(), sha))
        pos = nl + 1
    return out


def find_sha(paths: list[str]) -> dict[str, str]:
    """Binary-search SHA256SUMS.txt for the first path, then scan forward."""
    target = min(paths)
    lo, hi = 0, SUMS_BYTES
    while hi - lo > 65536:
        mid = (lo + hi) // 2
        lines = sums_line_at(mid, 1024)
        if not lines:
            hi = mid
            continue
        if lines[0][0] < target:
            lo = mid
        else:
            hi = mid
    found: dict[str, str] = {}
    off = lo
    want = set(paths)
    while want - set(found) and off < SUMS_BYTES:
        lines = sums_line_at(off, 262144)
        prev = None
        for p, sha in lines:
            if prev is not None and p < prev:
                raise SystemExit("SHA256SUMS.txt not sorted where expected")
            prev = p
            if p in want:
                found[p] = sha
        if lines and lines[-1][0] > max(paths):
            break
        off += 262144 - 512
    missing = want - set(found)
    if missing:
        raise SystemExit(f"SHA-256 not found for {sorted(missing)}")
    return found


def scan_record(cache: Path, recdir: str):
    """Return (status, info) for one record directory, per the rule above."""
    rec = recdir.strip("/").split("/")[-1]
    listed = cached(cache, recdir + "RECORDS").decode().split()
    if rec not in listed:  # numerics-only record: no waveform master header
        return "no_waveform_record", None
    mtext = cached(cache, recdir + rec + ".hea").decode()
    loc = re.search(r"^#\s*Location:\s*(\S+)", mtext, re.M)
    location = loc.group(1) if loc else ""
    if location == "nicu":
        return "nicu", None
    segs = parse_master(mtext)
    if not segs:
        return "not_multisegment", None
    layout = cached(cache, recdir + rec + "_layout.hea").decode()
    abp_layout = [ln.split() for ln in layout.splitlines()[1:] if ln.split()[-1:] == ["ABP"]]
    if not abp_layout or not re.fullmatch(r"1\.25(\(-?\d+\))?/mmHg", abp_layout[0][2]):
        return "layout_no_abp_1.25", None
    for name, length in segs:  # master-header (chronological) order
        if name == "~" or name.endswith("_layout") or length < MIN_FRAMES:
            continue
        info = qualifies(name, cached(cache, recdir + name + ".hea").decode())
        if info is None:
            continue
        if info["frames"] != length:
            raise SystemExit(f"master/segment length mismatch {name}")
        info["record"] = rec
        info["record_dir"] = recdir
        info["location"] = location
        return "kept", info
    return "no_qualifying_segment", None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--count", type=int, default=N_SEGMENTS)
    ap.add_argument("--threads", type=int, default=12)
    args = ap.parse_args()
    cache = args.cache
    cache.mkdir(parents=True, exist_ok=True)

    adults = cached(cache, "RECORDS-adults")
    print("RECORDS-adults", len(adults), hashlib.sha256(adults).hexdigest(), file=sys.stderr)
    recdirs = [ln.strip() for ln in adults.decode().splitlines() if ln.strip()]

    kept = []
    walked = 0
    tally: dict[str, int] = {}
    pool = ThreadPoolExecutor(args.threads)
    batch = 4 * args.threads
    i = 0
    while len(kept) < args.count and i < len(recdirs):
        block = recdirs[i : i + batch]
        i += batch
        results = list(pool.map(lambda d: scan_record(cache, d), block))
        for recdir, (status, info) in zip(block, results):
            if len(kept) >= args.count:
                break
            walked += 1
            tally[status] = tally.get(status, 0) + 1
            if info is not None:
                kept.append(info)
                print(f"keep {len(kept):3d} {recdir}{info['segment']} nsig={info['nsig']} frames={info['frames']}", file=sys.stderr)
        print(f"walked {walked} tally {tally}", file=sys.stderr)
    last_walked = recdirs[walked - 1]

    for info in kept:
        recdir, seg = info["record_dir"], info["segment"]
        hea = cached(cache, recdir + seg + ".hea")
        info["hea_bytes"] = len(hea)
        info["hea_sha256_local"] = hashlib.sha256(hea).hexdigest()
        info["dat_bytes"] = listing_size(cache, recdir, seg + ".dat")
        if info["dat_bytes"] != info["frames"] * info["nsig"]:
            raise SystemExit(f"dat size mismatch {seg}")
        sums = find_sha([recdir + seg + ".dat", recdir + seg + ".hea"])
        info["dat_sha256"] = sums[recdir + seg + ".dat"]
        info["hea_sha256"] = sums[recdir + seg + ".hea"]
        if info["hea_sha256"] != info["hea_sha256_local"]:
            raise SystemExit(f"hea hash mismatch vs SHA256SUMS {seg}")
        print(f"sha {seg} {info['dat_sha256'][:12]}", file=sys.stderr)
    out = {
        "records_walked": walked,
        "last_record_walked": last_walked,
        "walk_tally": tally,
        "records_adults_bytes": len(adults),
        "records_adults_sha256": hashlib.sha256(adults).hexdigest(),
        "segments": kept,
    }
    args.out.write_text(json.dumps(out, indent=1))
    tot = sum(k["frames"] for k in kept)
    dl = sum(k["dat_bytes"] for k in kept)
    print(f"segments={len(kept)} abp_values={tot} dat_bytes={dl}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
