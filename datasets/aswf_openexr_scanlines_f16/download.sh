#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$REPO_ROOT/datasets/aswf_openexr_scanlines_f16"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="aswf_openexr_scanlines_f16"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
METADATA_DIR="$DOWNLOAD_DIR/metadata"
TOOL_DIR="$REPO_ROOT/$DATA_DIR/tools/tinyexr_v1.0.12"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"

mkdir -p "$DOWNLOAD_DIR" "$METADATA_DIR" "$TOOL_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

valid_file() {
  python3 - "$1" "$2" "$3" "$4" "$5" <<'PY'
import hashlib,sys
from pathlib import Path
p=Path(sys.argv[1]);size=int(sys.argv[2]);kind=sys.argv[3];identity=sys.argv[4];expected_sha=sys.argv[5]
if not p.is_file() or p.stat().st_size!=size:raise SystemExit(1)
blob=hashlib.sha1();sha=hashlib.sha256()
if kind=="git_blob_sha1":blob.update(f"blob {size}\0".encode())
with p.open("rb") as h:
 while chunk:=h.read(8*1024*1024):blob.update(chunk);sha.update(chunk)
actual=blob.hexdigest() if kind=="git_blob_sha1" else sha.hexdigest()
raise SystemExit(0 if actual==identity and sha.hexdigest()==expected_sha else 1)
PY
}

while IFS=$'\t' read -r kind repository_path local_name size identity_type identity sha256 url; do
  [[ "$kind" == "kind" ]] && continue
  target_dir="$DOWNLOAD_DIR"
  [[ "$kind" == "license" || "$kind" == "provenance" ]] && target_dir="$METADATA_DIR"
  [[ "$kind" == "tool" ]] && target_dir="$TOOL_DIR"
  target="$target_dir/$local_name"
  if valid_file "$target" "$size" "$identity_type" "$identity" "$sha256";then
    echo "validated existing kind=$kind name=$local_name bytes=$size";continue
  fi
  reused=false
  for reuse_dir in "$REPO_ROOT/$DATA_DIR/downloads/aswf_openexr_scanlines" \
                   "$REPO_ROOT/$DATA_DIR/downloads/aswf_openexr_scanlines/metadata" \
                   "$REPO_ROOT/$DATA_DIR/tools/tinyexr_v1.0.12";do
    candidate="$reuse_dir/$local_name"
    if valid_file "$candidate" "$size" "$identity_type" "$identity" "$sha256";then
      cp --reflink=auto "$candidate" "$target";echo "reused name=$local_name from=$candidate";reused=true;break
    fi
  done
  [[ "$reused" == true ]] && continue
  rm -f "$target.part"
  echo "fetch kind=$kind name=$local_name bytes=$size"
  curl --fail --show-error --location --retry 3 --retry-delay 2 --max-time 900 \
    --max-filesize "$size" --user-agent "openzl-public-datasets-openexr/1.0" \
    --output "$target.part" "$url"
  valid_file "$target.part" "$size" "$identity_type" "$identity" "$sha256" || {
    echo "identity validation failed: $local_name" >&2;exit 1;}
  mv "$target.part" "$target"
done < "$RECIPE_DIR/selection.tsv"

export DOWNLOAD_DIR METADATA_DIR TOOL_DIR RECIPE_DIR
python3 - <<'PY'
import hashlib,json,os,struct
from pathlib import Path
download=Path(os.environ["DOWNLOAD_DIR"]);metadata=Path(os.environ["METADATA_DIR"])
tool=Path(os.environ["TOOL_DIR"]);selection=Path(os.environ["RECIPE_DIR"])/"selection.tsv"
if "redistribution and use in source and binary forms" not in (metadata/"LICENSE.openexr-images").read_text().lower():
 raise SystemExit("BSD redistribution grant missing")
if "SPDX-License-Identifier: BSD-3-Clause" not in (metadata/"README.ScanLines.rst").read_text():
 raise SystemExit("ScanLines BSD-3-Clause identifier missing")
if "TINYEXR_IMPLEMENTATION" not in (tool/"tinyexr.h").read_text():raise SystemExit("invalid TinyEXR header")
rows=[]
for line in selection.read_text().splitlines()[1:]:
 kind,repo_path,name,size,id_type,identity,expected_sha,url=line.split("\t")
 root=tool if kind=="tool" else metadata if kind in {"license","provenance"} else download
 path=root/name
 if kind=="exr":
  with path.open("rb") as h:prefix=h.read(8)
  if len(prefix)<8 or struct.unpack_from("<I",prefix)[0]!=20000630:raise SystemExit(f"bad EXR {name}")
 rows.append({"kind":kind,"repository_path":repo_path,"name":name,"size_bytes":int(size),
  "identity_type":id_type,"identity":identity,"sha256":expected_sha,"url":url})
(download/"acquisition.json").write_text(json.dumps(rows,indent=2,sort_keys=True)+"\n")
print(f"validated files={len(rows)} exr_files={sum(r['kind']=='exr' for r in rows)}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
