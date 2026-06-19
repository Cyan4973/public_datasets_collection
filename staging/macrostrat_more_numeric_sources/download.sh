#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="macrostrat_more_numeric_sources"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

USER_AGENT="${MACROSTRAT_USER_AGENT:-openzl-public-datasets/1.0}"
FAILURES="$DOWNLOAD_DIR/download_failures.tsv"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
INVENTORY="$DOWNLOAD_DIR/download_inventory.json"
printf 'candidate_id\tstatus\tdetail\turl\n' > "$FAILURES"
printf 'candidate_id\turl\tlocal_name\tnote\n' > "$PLAN"

echo "[$(date -Is)] download start dataset=$DATASET_ID"

cat > "$DOWNLOAD_DIR/candidate_urls.tsv" <<'EOF'
candidate_id	url	note
macrostrat_columns_long	https://macrostrat.org/api/columns?response=long	Column table candidate; expected numeric fields include area/coordinates/count metadata if exposed.
macrostrat_sections_long	https://macrostrat.org/api/sections?response=long	Section table candidate; expected stratigraphic section numeric fields if exposed.
macrostrat_measurements_long	https://macrostrat.org/api/measurements?response=long	Measurement table candidate; expected largest potential new homogeneous numeric material if endpoint is public.
macrostrat_def_intervals	https://macrostrat.org/api/defs/intervals	Interval definition table; may be too small but useful for documentation.
macrostrat_def_columns	https://macrostrat.org/api/defs/columns	Column definition table; may be a compact metadata table.
macrostrat_def_lithologies	https://macrostrat.org/api/defs/lithologies	Lithology definition table; likely code definitions, not primary unless large enough.
macrostrat_def_environments	https://macrostrat.org/api/defs/environments	Environment definition table; likely code definitions, not primary unless large enough.
macrostrat_def_econs	https://macrostrat.org/api/defs/econs	Economic resource definition table; likely code definitions, not primary unless large enough.
EOF

fetch_url() {
  local url="$1"
  local target="$2"
  rm -f "$target.tmp"
  if ! curl \
    --globoff \
    --fail \
    --location \
    --show-error \
    --retry 4 \
    --retry-delay 3 \
    --retry-all-errors \
    --connect-timeout 30 \
    --max-time 600 \
    -A "$USER_AGENT" \
    -o "$target.tmp" \
    "$url"; then
    rm -f "$target.tmp"
    return 1
  fi
  mv "$target.tmp" "$target"
}

validate_and_summarize() {
  local candidate_id="$1"
  local path="$2"
  python3 - "$candidate_id" "$path" <<'PY'
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

candidate_id = sys.argv[1]
path = Path(sys.argv[2])

obj = json.loads(path.read_text(encoding="utf-8"))
data = None
if isinstance(obj, dict):
    success = obj.get("success")
    if isinstance(success, dict) and isinstance(success.get("data"), list):
        data = success["data"]
    elif isinstance(obj.get("data"), list):
        data = obj["data"]
    elif isinstance(obj.get("success"), list):
        data = obj["success"]
if data is None:
    raise SystemExit(f"{candidate_id}: no list payload found")

numeric_fields: dict[str, int] = {}
field_counts: Counter[str] = Counter()
for row in data:
    if not isinstance(row, dict):
        continue
    for key, value in row.items():
        field_counts[key] += 1
        if value in (None, "") or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            numeric_fields[key] = numeric_fields.get(key, 0) + 1
            continue
        if isinstance(value, str):
            try:
                float(value)
            except ValueError:
                continue
            numeric_fields[key] = numeric_fields.get(key, 0) + 1

summary = {
    "candidate_id": candidate_id,
    "file": path.name,
    "bytes": path.stat().st_size,
    "records": len(data),
    "dict_records": sum(1 for row in data if isinstance(row, dict)),
    "numeric_fields": dict(sorted(numeric_fields.items())),
    "field_count": len(field_counts),
}
print(json.dumps(summary, sort_keys=True))
PY
}

summary_jsonl="$DOWNLOAD_DIR/resource_summaries.jsonl"
: > "$summary_jsonl"

while IFS=$'\t' read -r candidate_id url note; do
  if [[ "$candidate_id" == "candidate_id" ]]; then
    continue
  fi
  local_name="${candidate_id}.json"
  target="$DOWNLOAD_DIR/$local_name"
  printf '%s\t%s\t%s\t%s\n' "$candidate_id" "$url" "$local_name" "$note" >> "$PLAN"

  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    echo "dry_run candidate_id=$candidate_id url=$url"
    continue
  fi

  if [[ -s "$target" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "cache_hit candidate_id=$candidate_id path=$target"
  else
    echo "fetch candidate_id=$candidate_id url=$url"
    if ! fetch_url "$url" "$target"; then
      printf '%s\tfailed\tcurl_failed\t%s\n' "$candidate_id" "$url" >> "$FAILURES"
      continue
    fi
  fi

  if summary="$(validate_and_summarize "$candidate_id" "$target")"; then
    echo "$summary" >> "$summary_jsonl"
    echo "validated candidate_id=$candidate_id summary=$summary"
  else
    printf '%s\tfailed\tsemantic_validation_failed\t%s\n' "$candidate_id" "$url" >> "$FAILURES"
  fi
done < "$DOWNLOAD_DIR/candidate_urls.tsv"

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "failure_count=0"
  echo "[$(date -Is)] download done dataset=$DATASET_ID"
  exit 0
fi

python3 - "$DOWNLOAD_DIR" "$INVENTORY" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

download_dir = Path(sys.argv[1])
inventory_path = Path(sys.argv[2])
resources = []
summary_path = download_dir / "resource_summaries.jsonl"
if summary_path.exists():
    for line in summary_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            resources.append(json.loads(line))

failures = []
failures_path = download_dir / "download_failures.tsv"
if failures_path.exists():
    for line in failures_path.read_text(encoding="utf-8").splitlines()[1:]:
        if not line.strip():
            continue
        candidate_id, status, detail, url = line.split("\t", 3)
        failures.append(
            {
                "candidate_id": candidate_id,
                "status": status,
                "detail": detail,
                "url": url,
            }
        )

inventory = {
    "dataset_id": "macrostrat_more_numeric_sources",
    "successful_resources": len(resources),
    "failed_resources": len(failures),
    "source_bytes": sum(int(item["bytes"]) for item in resources),
    "records": sum(int(item["records"]) for item in resources),
    "resources": resources,
    "failures": failures,
}
inventory_path.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
if not resources:
    raise SystemExit("no Macrostrat candidate resources downloaded successfully")
print(
    f"wrote download_inventory.json successes={len(resources)} failures={len(failures)} "
    f"records={inventory['records']} source_bytes={inventory['source_bytes']}"
)
PY

failure_count="$(awk -F '\t' 'NR>1 && $2=="failed"{c++} END{print c+0}' "$FAILURES")"
echo "failure_count=$failure_count"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
exit 0
