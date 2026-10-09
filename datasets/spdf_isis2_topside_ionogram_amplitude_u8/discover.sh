#!/usr/bin/env bash
# Documents how sources.tsv was resolved (not called by download.sh).
# Lists the anonymous NASA HDRL S3 mirror of SPDF/CDAWeb with ListObjectsV2 for
# the ISIS-2 average-ionogram CDFs of station ULA (Fairbanks), year 1974, and
# writes the listing as TSV for comparison with the pinned sources.tsv.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="spdf_isis2_topside_ionogram_amplitude_u8"
OUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
BUCKET="https://gov-nasa-hdrl-data1.s3.amazonaws.com"
PREFIX="spdf/cdaweb/data/isis/ionogram_cdf/isis2/ULA_65N_212E/1974/"

mkdir -p "$OUT_DIR" "$LOG_DIR"
exec > >(tee "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discover start prefix=$PREFIX"

rm -f "$OUT_DIR"/list_page_*.xml
cont=""
page=0
while :; do
  url="$BUCKET/?list-type=2&max-keys=1000&prefix=$PREFIX"
  if [[ -n "$cont" ]]; then
    enc="$(printf '%s' "$cont" | sed -e 's/+/%2B/g' -e 's#/#%2F#g' -e 's/=/%3D/g')"
    url="$url&continuation-token=$enc"
  fi
  curl --globoff -fsS --retry 5 --retry-delay 2 --max-time 120 -o "$OUT_DIR/list_page_$page.xml" "$url"
  cont="$(grep -o '<NextContinuationToken>[^<]*' "$OUT_DIR/list_page_$page.xml" | sed 's/<NextContinuationToken>//' || true)"
  page=$((page + 1))
  [[ -n "$cont" ]] || break
done

python3 -I - "$OUT_DIR" > "$OUT_DIR/listing.tsv" <<'EOF'
import glob, re, sys
rows = []
for f in sorted(glob.glob(sys.argv[1] + "/list_page_*.xml")):
    t = open(f).read()
    for c in re.findall(r"<Contents>(.*?)</Contents>", t):
        k = re.search(r"<Key>(.*?)</Key>", c).group(1)
        s = re.search(r"<Size>(.*?)</Size>", c).group(1)
        e = re.search(r"<ETag>(.*?)</ETag>", c).group(1).replace("&quot;", "").strip('"')
        lm = re.search(r"<LastModified>(.*?)</LastModified>", c).group(1)
        if k.endswith(".cdf"):
            rows.append((k, k.rsplit("/", 1)[1], s, e, lm))
print("key\tfilename\tsize_bytes\tmd5\tlast_modified")
for r in sorted(rows):
    print("\t".join(r))
EOF

if cmp -s "$OUT_DIR/listing.tsv" "$RECIPE_DIR/sources.tsv"; then
  echo "listing identical to pinned sources.tsv"
else
  echo "listing differs from pinned sources.tsv:"
  diff "$RECIPE_DIR/sources.tsv" "$OUT_DIR/listing.tsv" | head -20 || true
fi
echo "[$(date -Is)] discover done objects=$(($(wc -l < "$OUT_DIR/listing.tsv") - 1))"
