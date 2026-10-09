"""Classify HDR+ bursts from 4 KiB payload_N000.dng header probes and make
the deterministic candidate selection (sources.candidate.tsv) that is then
privacy-screened into sources.tsv.

usage: select_bursts.py <discovery_dir> <n_select>

Eligibility (screener homogeneity rule): Make google (any case), Model
sailfish|marlin|Pixel|Pixel XL,
full-res CFA IFD0 (NewSubFileType 0, Photometric 32803, LJ92 compression 7,
4048x3036, 256x256 tiles x192, WhiteLevel 1023, 2x2 BGGR CFA, no linearization
table, no SubIFDs). Digitally zoomed (pre-cropped) and Nexus bursts fail the
dimension / model checks. Selection: eligible bursts sorted by burst folder
name, then N evenly spaced picks (all of them if fewer than N).
"""
from __future__ import annotations

import base64
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hdrplus_dng as hd  # noqa: E402

out = Path(sys.argv[1])
n_select = int(sys.argv[2])

items = {}
for f in sorted(glob.glob(str(out / "listing_*.json"))):
    for it in json.load(open(f)).get("items", []):
        items[it["name"]] = it

rows = []
for name, it in sorted(items.items()):
    if not name.endswith("/payload_N000.dng"):
        continue
    burst = name.split("/")[-2]
    hdr = out / "headers" / f"{burst}.bin"
    rec = {"burst": burst, "key": name, "size_bytes": int(it["size"]),
           "md5_hex": base64.b64decode(it["md5Hash"]).hex(), "generation": it.get("generation", "")}
    try:
        info = hd.dng_raw_info(hd.parse_tiff_ifd0(hdr.read_bytes(), allow_truncated=True))
        rec.update({k: info.get(k) for k in ("make", "model", "width", "height", "compression", "photometric",
                                             "cfa_pattern", "black_level", "white_level", "tile_count",
                                             "orientation", "datetime")})
        try:
            hd.check_pixel_cfa(info)
            rec["eligible"] = True
            rec["reason"] = "ok"
        except hd.DngError as exc:
            rec["eligible"] = False
            rec["reason"] = str(exc)
    except Exception as exc:  # noqa: BLE001
        rec["eligible"] = False
        rec["reason"] = f"header parse failed: {exc}"
    rows.append(rec)

cols = ["burst", "eligible", "reason", "make", "model", "width", "height", "cfa_pattern", "black_level",
        "white_level", "orientation", "datetime", "size_bytes", "md5_hex", "key"]
with open(out / "candidates.tsv", "w") as fh:
    fh.write("\t".join(cols) + "\n")
    for r in rows:
        fh.write("\t".join(json.dumps(r.get(c)) if isinstance(r.get(c), list) else str(r.get(c)) for c in cols) + "\n")

elig = sorted((r for r in rows if r["eligible"]), key=lambda r: r["burst"])
if len(elig) <= n_select:
    picks = elig
else:
    idx = sorted({round(k * (len(elig) - 1) / (n_select - 1)) for k in range(n_select)})
    picks = [elig[i] for i in idx]

with open(out / "sources.candidate.tsv", "w") as fh:
    fh.write("burst\tmodel\tcfa_pattern\tsize_bytes\tmd5_hex\tgeneration\turl\n")
    for r in picks:
        fh.write(f"{r['burst']}\t{r['model']}\t{r['cfa_pattern']}\t{r['size_bytes']}\t{r['md5_hex']}\t"
                 f"{r['generation']}\thttps://storage.googleapis.com/hdrplusdata/{r['key']}\n")

from collections import Counter
print(f"bursts={len(rows)} eligible={len(elig)} selected={len(picks)} "
      f"selected_bytes={sum(r['size_bytes'] for r in picks)}")
print("models:", Counter((r.get("make"), r.get("model")) for r in rows))
print("reasons:", Counter(r["reason"].split("=")[0] for r in rows))
print("eligible cfa:", Counter(r.get("cfa_pattern") for r in elig), "black:", Counter(str(r.get("black_level")) for r in elig))
