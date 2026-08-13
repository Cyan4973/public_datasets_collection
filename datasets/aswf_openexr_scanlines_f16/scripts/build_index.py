#!/usr/bin/env python3
from __future__ import annotations

import argparse,csv,hashlib,json,shutil,statistics
from collections import Counter,defaultdict
from pathlib import Path

DATASET_ID="aswf_openexr_scanlines_f16"
RGB_SERIES="aswf_openexr_rgb_half_f16"
ALPHA_SERIES="aswf_openexr_alpha_half_f16"
EXPECTED={
 "Blobbies.exr":((1040,1040),"zip",{"A","B","G","R"}),
 "CandleGlass.exr":((810,1000),"piz",{"A","B","G","R"}),
 "Carrots.exr":((400,600),"zip",{"B","G","R"}),
 "Desk.exr":((874,644),"piz",{"B","G","R"}),
 "MtTamWest.exr":((732,1214),"piz",{"B","G","R"}),
 "PrismsLenses.exr":((865,1200),"piz",{"A","B","G","R"}),
 "StillLife.exr":((846,1240),"piz",{"B","G","R"}),
 "Tree.exr":((906,928),"piz",{"B","G","R"}),
}

def file_sha256(path:Path)->str:
 d=hashlib.sha256()
 with path.open("rb") as h:
  while chunk:=h.read(8*1024*1024):d.update(chunk)
 return d.hexdigest()

def main()->None:
 p=argparse.ArgumentParser()
 for name in ("data_root","download_dir","filtered_dir","index_dir","sample_root","temp_dir"):
  p.add_argument("--"+name.replace("_","-"),type=Path,required=True)
 a=p.parse_args()
 acquisition=json.loads((a.download_dir/"acquisition.json").read_text())
 source_sha={r["name"]:r["sha256"] for r in acquisition if r["kind"]=="exr"}
 decoded=[]
 for path in sorted(a.filtered_dir.glob("decode_*.tsv")):
  with path.open(newline="") as h:decoded.extend(csv.DictReader(h,delimiter="\t"))
 counts=Counter(r["status"] for r in decoded)
 if counts!={"retained":27,"skipped_constant":5,"skipped_non_half":1}:
  raise SystemExit(f"unexpected decode statuses: {counts}")
 retained=defaultdict(set);rows=[]
 for r in decoded:
  if r["status"]!="retained":continue
  source=r["source_file"]
  if source not in EXPECTED:raise SystemExit(f"unexpected source: {source}")
  (height,width),compression,channels=EXPECTED[source]
  if (int(r["height"]),int(r["width"]))!=(height,width) or r["compression"]!=compression:
   raise SystemExit(f"geometry/compression mismatch: {r}")
  retained[source].add(r["channel"])
  series=ALPHA_SERIES if r["channel"]=="A" else RGB_SERIES
  if r["channel"] not in {"A","B","G","R"}:raise SystemExit(f"unexpected channel: {r}")
  out_dir=a.sample_root/series;out_dir.mkdir(parents=True,exist_ok=True)
  src=a.temp_dir/r["output_file"];dst=out_dir/r["output_file"];shutil.move(src,dst)
  size=int(r["value_count"])*2
  if dst.stat().st_size!=size:raise SystemExit(f"size mismatch: {dst}")
  rows.append({"dataset_id":DATASET_ID,"series_id":series,"role":"primary",
   "sample_path":dst.relative_to(a.data_root).as_posix(),"numeric_kind":"float","bit_width":16,
   "endianness":"little","element_size_bytes":2,"sample_size_bytes":size,
   "value_count":int(r["value_count"]),"sample_format":"raw IEEE-754 binary16 channel plane",
   "sample_geometry":"2d_openexr_channel_plane","sample_rank":2,"sample_shape":[height,width],
   "sample_axes":["y","x"],"natural_record_kind":"openexr_channel_plane",
   "source_path":(a.download_dir/source).relative_to(a.data_root).as_posix(),
   "source_sha256":source_sha[source],"channel":r["channel"],"compression":compression,
   "minimum":float(r["min_value"]),"maximum":float(r["max_value"]),"zero_count":int(r["zero_count"]),
   "sha256":file_sha256(dst)})
 for source,(_,_,channels) in EXPECTED.items():
  if retained[source]!=channels:raise SystemExit(f"channel mismatch {source}: {retained[source]}")
 rows.sort(key=lambda r:(r["series_id"],r["source_path"],r["channel"]))
 a.index_dir.mkdir(parents=True,exist_ok=True)
 with (a.index_dir/"samples.jsonl").open("w") as h:
  for r in rows:h.write(json.dumps(r,sort_keys=True)+"\n")
 series_stats={}
 for series in (ALPHA_SERIES,RGB_SERIES):
  selected=[r for r in rows if r["series_id"]==series]
  series_stats[series]={"sample_count":len(selected),"values":sum(r["value_count"] for r in selected),
   "bytes":sum(r["sample_size_bytes"] for r in selected),
   "median_sample_values":statistics.median(r["value_count"] for r in selected)}
 stats={"dataset_id":DATASET_ID,"source_count":8,"sample_count":len(rows),
  "primary_values":sum(r["value_count"] for r in rows),"primary_bytes":sum(r["sample_size_bytes"] for r in rows),
  "status_counts":dict(counts),"series":series_stats,"excluded_b44_source":"Cannon.exr",
  "excluded_float_channel":"Blobbies.exr:Z","tinyexr_version":"v1.0.12",
  "tinyexr_sha256":"e3eb50490af81dc3f5f067cf7f62955894d5db8f88a091c19bc4eef8e468095f"}
 if stats["primary_values"]!=22462336 or stats["primary_bytes"]!=44924672:raise SystemExit(f"aggregate mismatch: {stats}")
 (a.filtered_dir/"ingest_stats.json").write_text(json.dumps(stats,indent=2,sort_keys=True)+"\n")
 print(json.dumps(stats,indent=2,sort_keys=True))

if __name__=="__main__":main()
