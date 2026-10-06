#!/usr/bin/env python3
"""Resolve the pinned IRIS level-1 FUV full-readout frame selection (sources.tsv).

This is an authoring-time tool; download.sh never runs it and never crawls the
index. It documents how the 40 pinned S3 keys were chosen.

  scan    fetch a fixed, evenly spaced subset of the HelioCloud IRIS index CSVs
          (one CSV per minute of day, iris_iris_data_iris_HHMM.csv), keep level-1
          *_fuv.fits keys of >= 2,000,000 bytes, range-read each file's FITS
          headers (first 28,800 bytes) and record header facts in pool.tsv.
  select  apply the header regime and a deterministic activity-ranked,
          OBSID/date-diverse selection; HEAD each chosen object for size, ETag
          (MD5) and the full-object SHA-1 checksum; write sources.tsv.

All network access is curl (subprocess), so the ~/.curlrc proxy applies.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import iris_fits  # noqa: E402

BUCKET = "https://gov-nasa-hdrl-data1.s3.amazonaws.com"
INDEX_PREFIX = "sdac/iris/indices/"
INDEX_RE = re.compile(r"^sdac/iris/indices/iris_iris_data_iris_(\d{4})\.csv$")
KEY_RE = re.compile(
    r"^sdac/iris/iris_data/level1/(\d{4})/(\d{2})/(\d{2})/H(\d{4})/"
    r"iris(\d{8})_(\d{8})_fuv\.fits$")
INDEX_STRIDE = 12          # every 12th minute-of-day index -> 120 CSVs
MIN_INDEX_SIZE = 2_000_000  # full 4144x1096 readouts compress to ~2.4-3.1 MB
HEADER_BYTES = 28_800       # primary (1 block) + table header (<= 9 blocks)

POOL_FIELDS = [
    "key", "size_bytes", "date", "t_obs", "obsid", "fsn", "exptime", "crs_id",
    "crs_desc", "tsr1", "ter1", "tsr2", "ter2", "datavals", "datamin", "datamax",
    "datamedn", "datap01", "datap99", "datarms", "nsatpix", "quality", "saa", "hlz", "lutid",
    "aec_flare", "aec_event", "xcen", "ycen", "datasum", "regime",
]


def curl(args: list[str], binary: bool = False):
    proc = subprocess.run(
        ["curl", "--fail", "--silent", "--show-error", "--location",
         "--retry", "4", "--retry-delay", "3", "--max-time", "180", *args],
        capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"curl {' '.join(args)} failed: {proc.stderr.decode()[:300]}")
    return proc.stdout if binary else proc.stdout.decode()


def list_index_keys() -> list[str]:
    keys, token = [], None
    while True:
        url = f"{BUCKET}/?list-type=2&prefix={INDEX_PREFIX}"
        if token:
            from urllib.parse import quote
            url += "&continuation-token=" + quote(token, safe="")
        text = curl([url])
        keys += re.findall(r"<Key>(.*?)</Key>", text)
        m = re.search(r"<NextContinuationToken>(.*?)</NextContinuationToken>", text)
        if not m:
            return keys
        token = m.group(1)


def header_facts(key: str, size: int, blob: bytes) -> dict:
    _primary, _, pos = iris_fits.read_header(blob, 0)
    table, _, _ = iris_fits.read_header(blob, pos)
    problems = iris_fits.regime_problems(table)
    m = KEY_RE.match(key)
    g = table.get
    return {
        "key": key, "size_bytes": size,
        "date": f"{m.group(1)}-{m.group(2)}-{m.group(3)}",
        "t_obs": g("T_OBS"), "obsid": g("ISQOLTID"), "fsn": g("FSN"),
        "exptime": g("EXPTIME"), "crs_id": g("IICRSID"), "crs_desc": g("CRS_DESC"),
        "tsr1": g("TSR1"), "ter1": g("TER1"), "tsr2": g("TSR2"), "ter2": g("TER2"),
        "datavals": g("DATAVALS"), "datamin": g("DATAMIN"), "datamax": g("DATAMAX"),
        "datamedn": g("DATAMEDN"), "datap01": g("DATAP01"), "datap99": g("DATAP99"),
        "datarms": g("DATARMS"), "nsatpix": g("NSATPIX"), "quality": g("QUALITY"),
        "lutid": g("LUTID"),
        "saa": g("SAA"), "hlz": g("HLZ"), "aec_flare": g("IAECFLAG"),
        "aec_event": g("IAECEVFL"), "xcen": g("XCEN"), "ycen": g("YCEN"),
        "datasum": g("DATASUM"), "regime": "ok" if not problems else "; ".join(problems),
    }


def cmd_scan(args) -> None:
    cache = Path(args.cache)
    (cache / "indices").mkdir(parents=True, exist_ok=True)
    (cache / "headers").mkdir(parents=True, exist_ok=True)
    keys = sorted(k for k in list_index_keys() if INDEX_RE.match(k))
    print(f"index_csvs_listed={len(keys)}")
    chosen = keys[::INDEX_STRIDE]
    print(f"index_csvs_scanned={len(chosen)} stride={INDEX_STRIDE} "
          f"minutes={','.join(INDEX_RE.match(k).group(1) for k in chosen)}")
    candidates: dict[str, int] = {}
    for k in chosen:
        local = cache / "indices" / Path(k).name
        if not local.exists():
            local.write_bytes(curl([f"{BUCKET}/{k}"], binary=True))
        with local.open(newline="") as fh:
            for row in csv.reader(fh):
                if not row or row[0].startswith("#") or len(row) < 4:
                    continue
                key = row[2].replace("s3://gov-nasa-hdrl-data1/", "", 1)
                if KEY_RE.match(key) and int(row[3]) >= MIN_INDEX_SIZE:
                    candidates[key] = int(row[3])
    print(f"fuv_candidates_ge_{MIN_INDEX_SIZE}={len(candidates)}")

    def fetch(item):
        key, size = item
        local = cache / "headers" / (Path(key).name + ".hdr")
        if not local.exists():
            local.write_bytes(curl(["--range", f"0-{HEADER_BYTES - 1}",
                                    f"{BUCKET}/{key}"], binary=True))
        try:
            return header_facts(key, size, local.read_bytes())
        except Exception as exc:  # recorded, never selected
            return {"key": key, "size_bytes": size, "regime": f"unparsed: {exc}"}

    rows = []
    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        for facts in pool.map(fetch, sorted(candidates.items())):
            rows.append(facts)
    with open(cache / "pool.tsv", "w", newline="") as fh:
        w = csv.DictWriter(fh, POOL_FIELDS, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    ok = sum(1 for r in rows if r["regime"] == "ok")
    print(f"headers_read={len(rows)} regime_ok={ok} pool={cache / 'pool.tsv'}")


# ------------------------------------------------------------------ select
SELECT_COUNT = 40
MAX_PER_OBSID = 18       # no single observing program supplies more than ~45%
MAX_PER_YEAR = 6         # spread over the 2013-2022 mission years
MIN_EXPTIME = 4.0        # seconds; drops short-exposure frames dominated by pedestal
MIN_SPREAD = 10          # DATAP99 - DATAMEDN in DN; drops pedestal-only frames


def activity(r: dict) -> float:
    """Ranking score: bright-tail spread above the median pedestal."""
    return float(r["datap99"]) - float(r["datamedn"])


def eligible(r: dict) -> bool:
    if r["regime"] != "ok":
        return False
    # IRIS science OBSIDs start with 3; 4xxxxxxxxx are commissioning / calibration
    # programs (in the pool: 4190004113/4117 commissioning, 42019000xx "FUV full
    # frame" CRS 1 runs) and OBSID 0 is unassigned.
    if not str(r["obsid"]).startswith("3") or len(str(r["obsid"])) != 10:
        return False
    if int(r["quality"]) != 0 or int(r["saa"]) != 0 or int(r["hlz"]) != 0:
        return False
    if float(r["exptime"]) < MIN_EXPTIME:
        return False
    if activity(r) < MIN_SPREAD:
        return False
    # on-disk or near-limb pointing only (|r| <= 1.05 R_sun ~ 1016 arcsec)
    if (float(r["xcen"]) ** 2 + float(r["ycen"]) ** 2) ** 0.5 > 1016.0:
        return False
    return True


def cmd_select(args) -> None:
    cache = Path(args.cache)
    with open(cache / "pool.tsv", newline="") as fh:
        pool = list(csv.DictReader(fh, delimiter="\t"))
    elig = [r for r in pool if eligible(r)]
    print(f"pool={len(pool)} regime_ok={sum(r['regime'] == 'ok' for r in pool)} eligible={len(elig)}")
    # one frame per (date, OBSID) run: the most active one, ties -> earliest key
    best: dict[tuple, dict] = {}
    for r in sorted(elig, key=lambda r: (-activity(r), r["key"])):
        best.setdefault((r["date"], r["obsid"]), r)
    runs = sorted(best.values(), key=lambda r: (-activity(r), r["key"]))
    print(f"distinct_runs={len(runs)} distinct_obsids={len({r['obsid'] for r in runs})}")
    chosen, per_obsid, per_year = [], {}, {}
    for r in runs:
        year = r["date"][:4]
        if per_obsid.get(r["obsid"], 0) >= MAX_PER_OBSID or per_year.get(year, 0) >= MAX_PER_YEAR:
            continue
        chosen.append(r)
        per_obsid[r["obsid"]] = per_obsid.get(r["obsid"], 0) + 1
        per_year[year] = per_year.get(year, 0) + 1
        if len(chosen) == SELECT_COUNT:
            break
    if len(chosen) != SELECT_COUNT:
        raise SystemExit(f"only {len(chosen)} frames satisfy the selection policy")
    chosen.sort(key=lambda r: r["key"])

    out_rows = []
    for r in chosen:
        head = curl(["--head", "-H", "x-amz-checksum-mode: ENABLED", f"{BUCKET}/{r['key']}"])
        hdr = {}
        for line in head.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                hdr[k.strip().lower()] = v.strip()
        size = int(hdr["content-length"])
        etag = hdr["etag"].strip('"')
        sha1 = hdr.get("x-amz-checksum-sha1", "")
        if size != int(r["size_bytes"]) or not re.fullmatch(r"[0-9a-f]{32}", etag) or not sha1:
            raise SystemExit(f"unexpected HEAD for {r['key']}: {hdr}")
        out_rows.append({
            "filename": Path(r["key"]).name, "key": r["key"], "size_bytes": size,
            "md5_etag": etag, "sha1_b64": sha1, "last_modified": hdr.get("last-modified", ""),
            "date": r["date"], "t_obs": r["t_obs"], "obsid": r["obsid"], "fsn": r["fsn"],
            "exptime": r["exptime"], "tsr": r["tsr1"], "ter": r["ter1"],
            "datavals": r["datavals"], "datamin": r["datamin"], "datamax": r["datamax"],
            "datamedn": r["datamedn"], "datap99": r["datap99"], "datasum": r["datasum"],
        })
        print(f"pinned {r['key']} size={size} obsid={r['obsid']} exptime={r['exptime']} "
              f"p99-med={activity(r):.0f} max={r['datamax']}")
    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, list(out_rows[0]), delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(out_rows)
    print(f"sources={args.out} files={len(out_rows)} bytes={sum(r['size_bytes'] for r in out_rows)} "
          f"years={dict(sorted(per_year.items()))} obsids={len(per_obsid)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--cache", required=True)
    s.set_defaults(func=cmd_scan)
    s = sub.add_parser("select")
    s.add_argument("--cache", required=True)
    s.add_argument("--out", required=True)
    s.set_defaults(func=cmd_select)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
