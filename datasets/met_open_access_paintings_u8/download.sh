#!/usr/bin/env bash
# Download the reviewed Met Open Access painting images selected in discovery.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$REPO_ROOT/datasets/met_open_access_paintings_u8"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="met_open_access_paintings_u8"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
METADATA_DIR="$DOWNLOAD_DIR/metadata"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
POLICY_URL="https://metmuseum.github.io/"
API_ROOT="https://collectionapi.metmuseum.org/public/collection/v1"

mkdir -p "$DOWNLOAD_DIR" "$METADATA_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

valid_policy() {
  python3 - "$1" <<'PY'
import html,re,sys
from pathlib import Path
p=Path(sys.argv[1])
if not p.is_file():raise SystemExit(1)
text=html.unescape(re.sub(r"<[^>]+>"," ",p.read_text(encoding="utf-8"))).lower()
text=re.sub(r"\s+"," ",text)
ok="open access" in text and "public domain" in text and ("creative commons zero" in text or "cc0" in text)
raise SystemExit(0 if ok else 1)
PY
}

policy="$METADATA_DIR/open_access_policy.html"
if valid_policy "$policy"; then
  echo "validated existing Met Open Access policy"
else
  rm -f "$policy" "$policy.part"
  curl --fail --silent --show-error --location --retry 8 --retry-all-errors --retry-delay 5 \
    --max-time 240 --user-agent "openzl-public-datasets/1.0" \
    --output "$policy.part" "$POLICY_URL"
  valid_policy "$policy.part" || { echo "invalid Met Open Access policy evidence" >&2; exit 1; }
  mv "$policy.part" "$policy"
fi

inventory="$DOWNLOAD_DIR/acquisition.tsv"
printf 'topic\tobject_id\timage_name\twidth\theight\tprecision\tcomponents\tsize_bytes\tsha256\tprimary_image_url\tobject_url\n' > "$inventory.part"

valid_image() {
  local path="$1" expected_width="$2" expected_height="$3" expected_size="$4" expected_sha="$5"
  local parsed width height precision components size sha256
  parsed="$(python3 "$RECIPE_DIR/scripts/jpeg_info.py" "$path" 2>/dev/null)" || return 1
  IFS=$'\t' read -r width height precision components size sha256 <<< "$parsed"
  [[ "$width" == "$expected_width" && "$height" == "$expected_height" \
     && "$precision" == "8" && "$components" == "3" \
     && "$size" == "$expected_size" && "$sha256" == "$expected_sha" ]]
}

valid_metadata() {
  python3 - "$1" "$2" "$3" "$4" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]);expected_id=int(sys.argv[2]);image_url=sys.argv[3];object_url=sys.argv[4]
if not p.is_file():raise SystemExit(1)
obj=json.loads(p.read_text(encoding="utf-8"))
ok=(int(obj.get("objectID",0))==expected_id
    and obj.get("department")=="European Paintings"
    and obj.get("classification")=="Paintings"
    and obj.get("isPublicDomain") is True
    and obj.get("primaryImage")==image_url
    and obj.get("objectURL")==object_url)
raise SystemExit(0 if ok else 1)
PY
}

while IFS=$'\t' read -r topic object_id image_name expected_width expected_height expected_size expected_sha image_url object_url; do
  [[ "$topic" == "topic" ]] && continue
  target_metadata="$METADATA_DIR/$object_id.json"
  if valid_metadata "$target_metadata" "$object_id" "$image_url" "$object_url"; then
    echo "validated existing metadata object_id=$object_id"
  else
    rm -f "$target_metadata" "$target_metadata.part"
    curl --fail --silent --show-error --location --retry 8 --retry-all-errors --retry-delay 5 \
      --max-time 240 --user-agent "openzl-public-datasets/1.0" \
      --output "$target_metadata.part" "$API_ROOT/objects/$object_id"
    valid_metadata "$target_metadata.part" "$object_id" "$image_url" "$object_url" || {
      echo "invalid public-domain object metadata object_id=$object_id" >&2; exit 1; }
    mv "$target_metadata.part" "$target_metadata"
    sleep 1
  fi

  target="$DOWNLOAD_DIR/$image_name"
  if valid_image "$target" "$expected_width" "$expected_height" "$expected_size" "$expected_sha"; then
    echo "validated existing object_id=$object_id image=$image_name"
  else
    rm -f "$target" "$target.part"
    echo "fetch object_id=$object_id topic=$topic image=$image_name"
    curl --fail --silent --show-error --location --retry 8 --retry-all-errors --retry-delay 5 \
      --max-time 1800 --max-filesize 200000000 --user-agent "openzl-public-datasets/1.0" \
      --output "$target.part" "$image_url"
    valid_image "$target.part" "$expected_width" "$expected_height" "$expected_size" "$expected_sha" || {
      echo "pinned JPEG identity mismatch object_id=$object_id" >&2; exit 1; }
    mv "$target.part" "$target"
    sleep 1
  fi
  info="$(python3 "$RECIPE_DIR/scripts/jpeg_info.py" "$target")"
  IFS=$'\t' read -r width height precision components size sha256 <<< "$info"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$topic" "$object_id" "$image_name" "$width" "$height" "$precision" "$components" \
    "$size" "$sha256" "$image_url" "$object_url" >> "$inventory.part"
done < "$RECIPE_DIR/selection.tsv"

mv "$inventory.part" "$inventory"
python3 - "$inventory" <<'PY'
import csv,sys
from pathlib import Path
rows=list(csv.DictReader(Path(sys.argv[1]).open(encoding="utf-8"),delimiter="\t"))
if len(rows)!=10 or len({row["object_id"] for row in rows})!=10:
    raise SystemExit("acquisition inventory must contain ten unique objects")
pixels=sum(int(row["width"])*int(row["height"]) for row in rows)
source_bytes=sum(int(row["size_bytes"]) for row in rows)
print(f"validated_images={len(rows)} total_pixels={pixels} projected_plane_bytes={pixels*3} source_bytes={source_bytes}")
if pixels*3 > 1_000_000_000:
    raise SystemExit("decoded RGB planes would exceed the 1 GB acceptance cap")
PY
echo "[$(date -Is)] download done dataset=$DATASET_ID"
