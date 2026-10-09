#!/usr/bin/env python3
"""Resolve the pinned TRACE 171 A candidate pool (sources.tsv). Authoring-time only.

download.sh never runs this. It documents how the pinned S3 keys were chosen.

  scan    (also reads every header of the 00 UT hour, see TARGET_HOUR_RE)
          list every day prefix sdac/trace/1998/MM/DD/trac_171____a0_ from
          WINDOW_START to WINDOW_END (anonymous S3 ListObjectsV2, paginated),
          keep keys of exactly 2,105,280 bytes with a single-part MD5 ETag, take
          up to CANDIDATES_PER_DAY keys at evenly spaced positions of each day's
          time-sorted list, range-read their first 5,760 bytes (the whole FITS
          header) and record header facts and the header-regime verdict in
          pool.tsv.
  select  from the header-regime passes, keep frames greedily in time order
          that are at least MIN_SEPARATION_H hours after the previously kept
          frame, at most MAX_PER_DAY per day; write sources.tsv.

The header regime includes the near-lossless FRM_NAM allowlist
(trace_fits.program_class), so only allowlisted or conditional programs are
pinned. The data-level regime (no JPEG ringing around particle spikes, no empty
near-zero histogram bin, non-degenerate) can only be measured on whole frames,
so it is applied by build.py after download; sources.tsv is the candidate pool.

All network access is curl (subprocess), so the ~/.curlrc proxy applies.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trace_fits as T  # noqa: E402

BUCKET = "https://gov-nasa-hdrl-data1.s3.amazonaws.com"
CANDIDATES_PER_DAY = 32
MIN_SEPARATION_H = 3.0
MAX_PER_DAY = 2
TARGET_HOUR_RE = re.compile(r"_00\d{4}\.fts$")

POOL_FIELDS = ["key", "size_bytes", "md5_etag", "last_modified", "date_obs", "frm_nam",
               "obs_prog", "sht_mdur", "img_min", "img_max", "img_avg", "xcen", "ycen",
               "history", "problems"]
SOURCE_FIELDS = ["filename", "key", "size_bytes", "md5_etag", "last_modified", "date_obs",
                 "frm_nam", "obs_prog", "sht_mdur", "img_min", "img_max", "img_avg",
                 "xcen", "ycen", "history"]


def curl(args: list[str]) -> bytes:
    proc = subprocess.run(
        ["curl", "--fail", "--silent", "--show-error", "--location",
         "--retry", "4", "--retry-delay", "3", "--max-time", "120", *args],
        capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"curl {' '.join(args)} failed: {proc.stderr.decode()[:300]}")
    return proc.stdout


def list_day(day: dt.date) -> list[dict]:
    prefix = f"sdac/trace/{day:%Y/%m/%d}/trac_171____a0_"
    out, token = [], None
    while True:
        url = f"{BUCKET}/?list-type=2&max-keys=1000&prefix={quote(prefix)}"
        if token:
            url += "&continuation-token=" + quote(token, safe="")
        text = curl([url]).decode()
        for block in re.findall(r"<Contents>(.*?)</Contents>", text, re.S):
            get = lambda tag: (re.search(rf"<{tag}>(.*?)</{tag}>", block) or [None, ""])[1]
            out.append({"key": get("Key"), "size_bytes": int(get("Size") or 0),
                        "md5_etag": get("ETag").replace("&quot;", "").strip('"'),
                        "last_modified": get("LastModified")})
        m = re.search(r"<NextContinuationToken>(.*?)</NextContinuationToken>", text)
        if not m:
            return out
        token = m.group(1)


def scan(cache: Path) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    start = dt.date.fromisoformat(T.WINDOW_START)
    end = dt.date.fromisoformat(T.WINDOW_END)
    days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    with cf.ThreadPoolExecutor(8) as ex:
        listings = list(ex.map(list_day, days))
    candidates = []
    n_listed = n_ok = 0
    for day, objs in zip(days, listings):
        n_listed += len(objs)
        ok = sorted((o for o in objs
                     if T.KEY_RE.match(o["key"]) and o["size_bytes"] == T.FILE_SIZE
                     and re.fullmatch(r"[0-9a-f]{32}", o["md5_etag"])),
                    key=lambda o: o["key"])
        n_ok += len(ok)
        n = len(ok)
        if n <= CANDIDATES_PER_DAY:
            picks = list(ok)
        else:
            picks = [ok[(2 * i + 1) * n // (2 * CANDIDATES_PER_DAY)] for i in range(CANDIDATES_PER_DAY)]
        # Targeted stage: every frame of the 00 UT hour, where the near-lossless disk-centre
        # synoptic program (cjs.caldc171, CJS.scene.CDSsynoptic) runs as isolated frames that
        # sparse sampling misses.
        seen = {o["key"] for o in picks}
        picks += [o for o in ok if TARGET_HOUR_RE.search(o["key"]) and o["key"] not in seen]
        candidates += picks
    print(f"days={len(days)} listed={n_listed} full_size={n_ok} candidates={len(candidates)}", flush=True)

    def facts(o: dict) -> dict:
        path = cache / (o["key"].rsplit("/", 1)[1] + ".hdr")
        if not path.exists() or path.stat().st_size != T.HEADER_SIZE:
            blob = curl(["--range", f"0-{T.HEADER_SIZE - 1}", f"{BUCKET}/{o['key']}"])
            path.write_bytes(blob)
        blob = path.read_bytes()
        h, hist, off = T.parse_header(blob)
        problems = T.regime_problems(h, hist)
        if off != T.HEADER_SIZE:
            problems.append(f"data offset {off}")
        if not T.key_matches_header(o["key"], h):
            problems.append("key timestamp != DATE_OBS")
        sig, _ = T.history_signature(hist)
        return {**o, "date_obs": h.get("DATE_OBS"), "frm_nam": h.get("FRM_NAM"),
                "obs_prog": h.get("OBS_PROG"), "sht_mdur": h.get("SHT_MDUR"),
                "img_min": h.get("IMG_MIN"), "img_max": h.get("IMG_MAX"),
                "img_avg": h.get("IMG_AVG"), "xcen": h.get("XCEN"), "ycen": h.get("YCEN"),
                "history": "+".join(sig), "problems": "; ".join(problems)}

    with cf.ThreadPoolExecutor(8) as ex:
        rows = list(ex.map(facts, candidates))
    with open(cache / "pool.tsv", "w", newline="") as fh:
        w = csv.DictWriter(fh, POOL_FIELDS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in POOL_FIELDS})
    print(f"header_pass={sum(1 for r in rows if not r['problems'])} of {len(rows)}", flush=True)


def select(cache: Path, out: Path) -> None:
    rows = list(csv.DictReader(open(cache / "pool.tsv", newline=""), delimiter="\t"))
    passing = sorted((r for r in rows if not r["problems"]), key=lambda r: r["date_obs"])
    kept, last, per_day = [], None, {}
    for r in passing:
        t = dt.datetime.fromisoformat(r["date_obs"][:19])
        day = r["date_obs"][:10]
        if last is not None and (t - last).total_seconds() < MIN_SEPARATION_H * 3600:
            continue
        if per_day.get(day, 0) >= MAX_PER_DAY:
            continue
        kept.append(r)
        last = t
        per_day[day] = per_day.get(day, 0) + 1
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, SOURCE_FIELDS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for r in kept:
            w.writerow({"filename": r["key"].rsplit("/", 1)[1], **{k: r[k] for k in SOURCE_FIELDS[1:]}})
    months = sorted({r["date_obs"][:7] for r in kept})
    print(f"selected={len(kept)} days={len(per_day)} months={months} "
          f"bytes={len(kept) * T.FILE_SIZE}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["scan", "select"])
    ap.add_argument("--cache", type=Path, required=True)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    if a.mode == "scan":
        scan(a.cache)
    else:
        select(a.cache, a.out)


if __name__ == "__main__":
    main()
