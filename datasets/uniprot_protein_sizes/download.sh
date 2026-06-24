#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="uniprot_protein_sizes"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

# One streamed request for the whole reviewed (Swiss-Prot) set with field projection;
# build groups by organism into per-organism samples.
QUERY="${UNIPROT_QUERY:-reviewed:true}"
OUT="$DOWNLOAD_DIR/uniprot_protein_sizes.tsv.gz"
TMP="$OUT.tmp"

if [ -s "$OUT" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  echo "[$(date -Is)] cache_hit dataset=$DATASET_ID path=$OUT"
else
  rm -f "$TMP"
  echo "[$(date -Is)] stream query='$QUERY' fields=accession,length,mass,organism_id"
  curl --globoff -fL --retry 6 --retry-delay 5 --speed-limit 1024 --speed-time 120 \
    -A "openzl-public-datasets/1.0" \
    -G "https://rest.uniprot.org/uniprotkb/stream" \
    --data-urlencode "query=${QUERY}" \
    --data-urlencode "fields=accession,length,mass,organism_id" \
    --data-urlencode "format=tsv" \
    --data-urlencode "compressed=true" \
    -o "$TMP"
  python3 - "$TMP" <<'PY'
import gzip, sys
path = sys.argv[1]
with gzip.open(path, "rt", encoding="utf-8") as fh:
    header = fh.readline().rstrip("\n").split("\t")
    if header[:3] != ["Entry", "Length", "Mass"]:
        raise SystemExit(f"unexpected TSV header: {header}")
    rows = 0
    for _ in fh:
        rows += 1
        if rows >= 5:
            break
    if rows == 0:
        raise SystemExit("no data rows in stream")
print("payload header/columns ok")
PY
  mv "$TMP" "$OUT"
fi

python3 - "$OUT" "$DOWNLOAD_DIR/download_stats.json" <<'PY'
import gzip, json, sys
from collections import Counter
path, stats_path = sys.argv[1], sys.argv[2]
per_org = Counter()
total = 0
with gzip.open(path, "rt", encoding="utf-8") as fh:
    header = fh.readline().rstrip("\n").split("\t")
    org_idx = header.index("Organism (ID)") if "Organism (ID)" in header else 3
    for line in fh:
        parts = line.rstrip("\n").split("\t")
        if len(parts) <= org_idx:
            continue
        total += 1
        per_org[parts[org_idx]] += 1
big = {k: v for k, v in per_org.items() if v >= 1000}
json.dump({
    "dataset_id": "uniprot_protein_sizes",
    "total_rows": total,
    "distinct_organisms": len(per_org),
    "organisms_with_1000plus": len(big),
}, open(stats_path, "w"), indent=2, sort_keys=True)
print(f"total_rows={total} distinct_organisms={len(per_org)} organisms_1000plus={len(big)}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
