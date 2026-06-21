#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="wikimedia_pageviews_daily"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
TOP_DIR="$DOWNLOAD_DIR/top"
SERIES_DIR="$DOWNLOAD_DIR/series"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$TOP_DIR" "$SERIES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

# Many article-samples of one quantity (daily pageviews). Articles are discovered
# from the public "top" endpoint across several large Wikipedia projects and a few
# reference months (to favour evergreen, long-lived pages); each article then gets
# its full daily series. All tunable via env vars.
BASE="https://wikimedia.org/api/rest_v1/metrics/pageviews"
WIKI_PROJECTS="${WIKI_PROJECTS:-en.wikipedia de.wikipedia fr.wikipedia es.wikipedia ru.wikipedia ja.wikipedia}"
WIKI_REF_MONTHS="${WIKI_REF_MONTHS:-2019/01 2023/01}"
WIKI_TOP_N="${WIKI_TOP_N:-20}"
WIKI_START="${WIKI_START:-20150701}"
WIKI_END="${WIKI_END:-20241231}"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"

# ---- Stage 1: fetch top-article lists -------------------------------------------------
for project in $WIKI_PROJECTS; do
  for ym in $WIKI_REF_MONTHS; do
    year="${ym%%/*}"
    month="${ym##*/}"
    out="$TOP_DIR/top_${project}_${year}_${month}.json"
    if [ -s "$out" ]; then
      echo "cached top=$project $year-$month"
      continue
    fi
    echo "fetch top project=$project month=$year-$month"
    curl --globoff -fL --retry 4 --retry-delay 3 --max-time 120 \
      -A "$UA" -H "Accept: application/json" \
      -o "$out" \
      "$BASE/top/$project/all-access/$year/$month/all-days" || {
        echo "WARN: top fetch failed for $project $year-$month"; rm -f "$out"; }
    sleep 0.2
  done
done

# ---- Stage 2: select articles -> manifest --------------------------------------------
MANIFEST="$DOWNLOAD_DIR/article_manifest.tsv"
export TOP_DIR MANIFEST WIKI_TOP_N
python3 - <<'PY'
import json, os, hashlib
from pathlib import Path
from urllib.parse import quote

top_dir = Path(os.environ["TOP_DIR"])
manifest = Path(os.environ["MANIFEST"])
top_n = int(os.environ["WIKI_TOP_N"])

# Landing/main pages are a different traffic regime, not content articles. Colon-
# namespaced main pages (de/fr/es) fall out via the ":" rule; these localized titles
# carry no colon and must be listed explicitly.
MAIN_PAGES = {"Main_Page", "Заглавная_страница", "メインページ"}

def is_junk(title: str) -> bool:
    if not title or title == "-":
        return True
    if title in MAIN_PAGES:
        return True
    # namespace pages (Special:, Wikipedia:, Portal:, Category:, File:, Help:, ...)
    if ":" in title:
        return True
    return False

seen = {}  # (project, article) -> slug
for path in sorted(top_dir.glob("top_*.json")):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        continue
    items = payload.get("items") or []
    for block in items:
        project = block.get("project")
        arts = block.get("articles") or []
        kept = 0
        for entry in arts:
            if kept >= top_n:
                break
            article = entry.get("article")
            if not project or not article or is_junk(article):
                continue
            kept += 1
            key = (project, article)
            if key in seen:
                continue
            h = hashlib.sha1(f"{project}\t{article}".encode("utf-8")).hexdigest()[:8]
            safe_proj = project.replace(".", "_")
            seen[key] = f"{safe_proj}__{h}"

rows = sorted(seen.items())
with manifest.open("w", encoding="utf-8") as fh:
    for (project, article), slug in rows:
        enc = quote(article, safe="")  # keep underscores, encode "/" and unicode
        fh.write(f"{project}\t{article}\t{slug}\t{enc}\n")
print(f"selected articles={len(rows)} from {len(list(top_dir.glob('top_*.json')))} top lists")
if len(rows) < 5:
    raise SystemExit(f"too few articles selected: {len(rows)}")
PY

# ---- Stage 3: fetch per-article daily series -----------------------------------------
total=0
fetched=0
cached=0
failed=0
while IFS=$'\t' read -r project article slug enc; do
  total=$((total + 1))
  out="$SERIES_DIR/${slug}.json"
  if [ -s "$out" ]; then
    cached=$((cached + 1))
    continue
  fi
  url="$BASE/per-article/$project/all-access/all-agents/$enc/daily/$WIKI_START/$WIKI_END"
  if curl --globoff -fsSL --retry 3 --retry-delay 2 --max-time 120 \
      -A "$UA" -H "Accept: application/json" -o "$out" "$url"; then
    # quick structural validation; drop empty payloads
    if python3 - "$out" <<'PY'
import json, sys
try:
    items = (json.load(open(sys.argv[1])) or {}).get("items")
except Exception:
    sys.exit(1)
sys.exit(0 if isinstance(items, list) and items else 1)
PY
    then
      fetched=$((fetched + 1))
    else
      echo "WARN: empty/invalid series project=$project article=$article"
      rm -f "$out"
      failed=$((failed + 1))
    fi
  else
    echo "WARN: series fetch failed project=$project article=$article"
    rm -f "$out"
    failed=$((failed + 1))
  fi
  sleep 0.15
done < "$MANIFEST"

have="$(find "$SERIES_DIR" -maxdepth 1 -type f -name '*.json' | wc -l | tr -d ' ')"
echo "[$(date -Is)] download done dataset=$DATASET_ID manifest=$total fetched=$fetched cached=$cached failed=$failed series_on_disk=$have"
test "$have" -ge 5
