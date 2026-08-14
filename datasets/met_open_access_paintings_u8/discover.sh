#!/usr/bin/env bash
# Discover public-domain Met paintings without downloading image payloads.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="met_open_access_paintings_u8"
DISCOVERY_DIR="$REPO_ROOT/$DATA_DIR/discovery/$DATASET_ID"
SEARCH_DIR="$DISCOVERY_DIR/search"
OBJECT_DIR="$DISCOVERY_DIR/objects"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
POLICY_URL="https://metmuseum.github.io/"
API_ROOT="https://collectionapi.metmuseum.org/public/collection/v1"
MAX_IDS_PER_TOPIC="${MET_MAX_IDS_PER_TOPIC:-10}"

mkdir -p "$SEARCH_DIR" "$OBJECT_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discovery start dataset=$DATASET_ID"

curl --fail --silent --show-error --location --retry 8 --retry-all-errors --retry-delay 5 --max-time 240 \
  --user-agent "openzl-public-datasets/1.0" \
  --output "$DISCOVERY_DIR/open_access_policy.html.part" "$POLICY_URL"
[[ -s "$DISCOVERY_DIR/open_access_policy.html.part" ]] || { echo "empty Met Open Access policy" >&2; exit 1; }
mv "$DISCOVERY_DIR/open_access_policy.html.part" "$DISCOVERY_DIR/open_access_policy.html"

topics=(landscape still-life seascape architecture garden night snow forest flowers animals)
for topic in "${topics[@]}"; do
  query="${topic//-/ }"
  target="$SEARCH_DIR/$topic.json"
  curl --fail --silent --show-error --location --retry 8 --retry-all-errors --retry-delay 5 --max-time 240 \
    --user-agent "openzl-public-datasets/1.0" --get \
    --data-urlencode "departmentId=11" \
    --data-urlencode "hasImages=true" \
    --data-urlencode "q=$query" \
    --output "$target.part" "$API_ROOT/search"
  python3 - "$target.part" "$topic" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]);topic=sys.argv[2]
data=json.loads(p.read_text(encoding="utf-8"))
ids=data.get("objectIDs")
if not isinstance(ids,list) or not ids:
    raise SystemExit(f"empty or malformed search result for {topic}")
if any(not isinstance(value,int) or value <= 0 for value in ids):
    raise SystemExit(f"invalid object ID in search result for {topic}")
print(f"topic={topic} result_count={len(ids)}")
PY
  mv "$target.part" "$target"
  sleep 1
done

export SEARCH_DIR MAX_IDS_PER_TOPIC
python3 - <<'PY' > "$DISCOVERY_DIR/candidate_ids.tsv"
import json,os
from pathlib import Path
root=Path(os.environ["SEARCH_DIR"]);limit=int(os.environ["MAX_IDS_PER_TOPIC"])
print("topic\trank\tobject_id")
for path in sorted(root.glob("*.json")):
    ids=json.loads(path.read_text(encoding="utf-8"))["objectIDs"]
    for rank,object_id in enumerate(ids[:limit],1):
        print(f"{path.stem}\t{rank}\t{object_id}")
PY

cut -f3 "$DISCOVERY_DIR/candidate_ids.tsv" | tail -n +2 | sort -nu | while read -r object_id; do
  target="$OBJECT_DIR/$object_id.json"
  if [[ -s "$target" ]] && python3 -m json.tool "$target" >/dev/null 2>&1; then
    echo "reuse object_id=$object_id"
    continue
  fi
  rm -f "$target" "$target.part"
  if ! curl --fail --silent --show-error --location --retry 8 --retry-all-errors --retry-delay 5 --max-time 240 \
      --user-agent "openzl-public-datasets/1.0" \
      --output "$target.part" "$API_ROOT/objects/$object_id"; then
    echo "object fetch failed object_id=$object_id" >&2
    rm -f "$target.part"
    continue
  fi
  python3 -m json.tool "$target.part" >/dev/null
  mv "$target.part" "$target"
  sleep 1
done

export DISCOVERY_DIR OBJECT_DIR
python3 "$REPO_ROOT/datasets/$DATASET_ID/scripts/select_candidates.py"
echo "[$(date -Is)] discovery done dataset=$DATASET_ID"
