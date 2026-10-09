#!/usr/bin/env python3
"""Resolve the pinned product list (sources.tsv) for nasa_pds_cassini_rpws_wbr_10khz_waveform_u8.

Author-time tool, not part of download/build/verify. All network I/O goes
through curl (never urllib). Steps:

1. For each of 12 Saturn-tour CORPWS volumes spaced 18 apart (CORPWS_0040,
   0058, ..., 0238; 2004-11 to 2017), fetch INDEX/INDEX.TAB and keep the
   RPWS_WIDEBAND_FULL rows whose PRODUCT_ID matches
   T<yyyyddd>_<hh>_10KHZ<n>_WBRFR_V1 (the 10-kHz baseband mode only; 75KHZ,
   5KHZ, 325KHZ and every <nnnn>KHZ frequency-translated product never match).
2. Fetch the Apache listing of every day directory that holds such a
   product and HEAD the .DAT files whose listed size could fall in the window,
   to obtain exact Content-Length and Last-Modified.
3. Eligible products: exact DAT size within [MIN_BYTES, MAX_BYTES]. Sort by
   product id and take PER_VOLUME picks at evenly spaced ranks
   (rank = floor((i + 0.5) * n / PER_VOLUME)). Each pick is probed: HEAD +
   GET of its detached label (checked with rpws.check_label) and a range GET
   of the first PROBE_BYTES of the DAT, which must parse with the label's
   RECORD_BYTES, carry FREQUENCY_BAND 2 in every probed record, and have at
   least one ANTENNA==0 (Ex) record. A pick that fails the probe is replaced
   by the next eligible product in rank order not already taken.
4. Write sources.tsv in volume/product order and print totals.

Usage: python3 -I discover.py --work /tmp/autocollect/<id>/discover [--out sources.tsv]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "scripts"))
import rpws  # noqa: E402

UA = "openzl-public-datasets-cassini-rpws-discover/1.0"
VOLUMES = [f"CORPWS_{40 + 18 * k:04d}" for k in range(12)]
PER_VOLUME = 8
MIN_BYTES = 1_000_000
MAX_BYTES = 8_000_000
PROBE_BYTES = 32768


def curl(args: list[str]) -> bytes:
    cmd = ["curl", "--fail", "--silent", "--show-error", "--location", "--retry", "5", "--retry-delay", "3",
           "--max-time", "300", "--user-agent", UA] + args
    return subprocess.run(cmd, check=True, capture_output=True).stdout


def head(url: str) -> dict:
    text = curl(["--head", url]).decode("latin-1")
    size = int(re.search(r"(?im)^content-length:\s*(\d+)", text).group(1))
    lm = re.search(r"(?im)^last-modified:\s*(.+?)\s*$", text).group(1)
    return {"size": size, "last_modified": lm}


def listing_sizes(url: str) -> dict[str, str]:
    html = curl([url]).decode("latin-1")
    out = {}
    for m in re.finditer(r'href="([^"]+\.DAT)">[^<]*</a>\s+\S+\s+\S+\s+([0-9.]+[KMG]?)', html):
        out[m.group(1)] = m.group(2)
    return out


def approx_bytes(s: str) -> float:
    mult = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}
    return float(s[:-1]) * mult[s[-1]] if s[-1] in mult else float(s)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=HERE / "sources.tsv")
    args = ap.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)

    rows_out = []
    for vol in VOLUMES:
        idx = curl([f"{rpws.BASE_URL}/{vol}/INDEX/INDEX.TAB"]).decode("latin-1")
        (args.work / f"{vol}_INDEX.TAB").write_text(idx, encoding="latin-1")
        prods = []
        for line in idx.splitlines()[1:]:
            cols = [c.strip().strip('"').strip() for c in line.split(",")]
            if len(cols) < 9 or cols[1] != "RPWS_WIDEBAND_FULL":
                continue
            pid = cols[3]
            if not pid.endswith("_V1") or not rpws.PRODUCT_RE.match(pid[:-3]):
                continue
            prods.append({"product": pid[:-3], "start_time": cols[4], "lbl_path": cols[7]})
        days = sorted({p["lbl_path"].rsplit("/", 1)[0] for p in prods})
        sizes = {}
        for d in days:
            for name, s in listing_sizes(f"{rpws.BASE_URL}/{vol}/{d}/").items():
                sizes[f"{d}/{name}"] = s
        eligible = []
        for p in sorted(prods, key=lambda r: r["product"]):
            dat_path = p["lbl_path"][:-4] + ".DAT"
            s = sizes.get(dat_path)
            if s is None:
                print(f"WARN {vol} {dat_path} missing from listing", file=sys.stderr)
                continue
            a = approx_bytes(s)
            if a < MIN_BYTES * 0.9 or a > MAX_BYTES * 1.1:
                continue
            h = head(f"{rpws.BASE_URL}/{vol}/{dat_path}")
            if MIN_BYTES <= h["size"] <= MAX_BYTES:
                eligible.append({**p, "vol": vol, "dat_path": dat_path, **h})
        n = len(eligible)
        print(f"{vol}: {len(prods)} 10KHZ products, {n} eligible in [{MIN_BYTES},{MAX_BYTES}]")
        ranks = sorted({int((i + 0.5) * n / PER_VOLUME) for i in range(min(PER_VOLUME, n))})
        taken: set[int] = set()
        for r in ranks:
            j = r
            while j < n:
                if j in taken:
                    j += 1
                    continue
                e = eligible[j]
                taken.add(j)
                lbl_url = f"{rpws.BASE_URL}/{vol}/{e['lbl_path']}"
                dat_url = f"{rpws.BASE_URL}/{vol}/{e['dat_path']}"
                try:
                    lh = head(lbl_url)
                    lbl = curl([lbl_url]).decode("latin-1")
                    meta = rpws.check_label(lbl, e["product"], e["size"])
                    probe = curl(["--range", f"0-{PROBE_BYTES - 1}", dat_url])
                    recs = list(rpws.iter_records(probe, meta["record_bytes"], allow_partial_tail=True))
                    if not recs or any(rc["band"] != rpws.BAND_10KHZ for rc in recs):
                        raise ValueError("probe: band not 10 kHz")
                    ex = sum(1 for rc in recs if rc["antenna"] == rpws.ANTENNA_EX)
                    if ex == 0:
                        raise ValueError(f"probe: no Ex records (antennas {sorted({rc['antenna'] for rc in recs})})")
                except (ValueError, subprocess.CalledProcessError) as exc:
                    print(f"  skip rank {j} {e['product']}: {exc}")
                    j += 1
                    continue
                rows_out.append({
                    "volume": vol, "product": e["product"], "start_time": e["start_time"],
                    "dat_url": dat_url, "dat_size": e["size"], "dat_last_modified": e["last_modified"],
                    "lbl_url": lbl_url, "lbl_size": lh["size"], "record_bytes": meta["record_bytes"],
                    "file_records": meta["file_records"], "probe_ex_records": ex, "probe_records": len(recs),
                })
                print(f"  pick rank {j} {e['product']} size={e['size']} rb={meta['record_bytes']} ex={ex}/{len(recs)}")
                break

    cols = ["volume", "product", "start_time", "dat_url", "dat_size", "dat_last_modified", "lbl_url",
            "lbl_size", "record_bytes", "file_records", "probe_ex_records", "probe_records"]
    with args.out.open("w", encoding="utf-8") as fh:
        fh.write("\t".join(cols) + "\n")
        for r in rows_out:
            fh.write("\t".join(str(r[c]) for c in cols) + "\n")
    print(f"products={len(rows_out)} dat_bytes={sum(r['dat_size'] for r in rows_out)} "
          f"lbl_bytes={sum(r['lbl_size'] for r in rows_out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
