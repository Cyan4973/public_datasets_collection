#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="statsbomb_open_events_numeric"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

# StatsBomb open data is a public GitHub repository of association-football match
# event streams. A match's event stream (data/events/<match_id>.json) is the
# natural record; we download a bounded, multi-competition set of them and the
# build extracts per-event numeric fields (one sample per match). The numeric
# quantities (pitch coordinates, event duration, timing) share one coordinate
# and unit system across all competitions, so mixing matches stays homogeneous.
BASE="${STATSBOMB_BASE:-https://raw.githubusercontent.com/statsbomb/open-data/master}"
MATCH_LIMIT="${MATCH_LIMIT:-150}"          # total matches to collect
PER_SEASON_LIMIT="${PER_SEASON_LIMIT:-20}" # matches taken per competition-season (spreads variety)
MIN_MATCH_COUNT="${MIN_MATCH_COUNT:-30}"   # a usable download needs at least this many matches
MAX_DOWNLOAD_BYTES="${MAX_DOWNLOAD_BYTES:-1000000000}"
MAX_FILE_BYTES="${MAX_FILE_BYTES:-33554432}"   # 32 MB guard per event file
STATSBOMB_MATCHES_FILE="${STATSBOMB_MATCHES_FILE:-}"  # optional: newline list of match_ids (offline/reproducible)
UA="openzl-public-datasets/1.0 (numeric dataset collection)"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"

export BASE MATCH_LIMIT PER_SEASON_LIMIT PLAN DOWNLOAD_DIR STATSBOMB_MATCHES_FILE UA

# ---- Build the match plan (competitions -> matches -> match_ids, capped) ------
python3 - <<'PY'
from __future__ import annotations

import csv
import json
import os
import urllib.request
from pathlib import Path

BASE = os.environ["BASE"].rstrip("/")
MATCH_LIMIT = int(os.environ["MATCH_LIMIT"])
PER_SEASON_LIMIT = int(os.environ["PER_SEASON_LIMIT"])
PLAN = Path(os.environ["PLAN"])
DOWNLOAD_DIR = Path(os.environ["DOWNLOAD_DIR"])
MATCHES_FILE = os.environ.get("STATSBOMB_MATCHES_FILE", "").strip()
UA = os.environ["UA"]


def apply_curlrc_proxy_fallback() -> None:
    if any(os.environ.get(n) for n in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY")):
        return
    curlrc = Path.home() / ".curlrc"
    if not curlrc.exists():
        return
    for raw in curlrc.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if line.startswith("proxy="):
            proxy = line.split("=", 1)[1].strip().strip('"')
            if proxy:
                os.environ["http_proxy"] = proxy
                os.environ["https_proxy"] = proxy
        elif line.startswith("noproxy="):
            no_proxy = line.split("=", 1)[1].strip().strip('"')
            if no_proxy:
                os.environ.setdefault("no_proxy", no_proxy)


def fetch_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def plan_rows() -> list[dict]:
    rows: list[dict] = []
    seen: set[int] = set()

    # Offline / reproducible override: an explicit match_id list.
    if MATCHES_FILE:
        for line in Path(MATCHES_FILE).read_text(encoding="utf-8").splitlines():
            token = line.strip()
            if not token or token.startswith("#"):
                continue
            mid = int(token)
            if mid in seen:
                continue
            seen.add(mid)
            rows.append({"match_id": mid, "local_name": f"events_{mid}.json",
                         "competition_id": "", "season_id": "",
                         "competition_name": "", "season_name": ""})
            if len(rows) >= MATCH_LIMIT:
                break
        return rows

    apply_curlrc_proxy_fallback()
    competitions = fetch_json(f"{BASE}/data/competitions.json")
    # Deterministic order; unique (competition_id, season_id) pairs.
    pairs: list[tuple[int, int, str, str]] = []
    pair_seen: set[tuple[int, int]] = set()
    for comp in competitions:
        try:
            cid = int(comp["competition_id"])
            sid = int(comp["season_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if (cid, sid) in pair_seen:
            continue
        pair_seen.add((cid, sid))
        pairs.append((cid, sid, str(comp.get("competition_name") or ""), str(comp.get("season_name") or "")))
    pairs.sort(key=lambda p: (p[0], p[1]))

    for cid, sid, cname, sname in pairs:
        if len(rows) >= MATCH_LIMIT:
            break
        try:
            matches = fetch_json(f"{BASE}/data/matches/{cid}/{sid}.json")
        except Exception as exc:  # a missing season file is not fatal
            print(f"  WARN: no match list for competition={cid} season={sid}: {exc}")
            continue
        taken = 0
        for match in sorted(matches, key=lambda m: int(m.get("match_id", 0))):
            try:
                mid = int(match["match_id"])
            except (KeyError, TypeError, ValueError):
                continue
            if mid in seen:
                continue
            seen.add(mid)
            rows.append({"match_id": mid, "local_name": f"events_{mid}.json",
                         "competition_id": cid, "season_id": sid,
                         "competition_name": cname, "season_name": sname})
            taken += 1
            if taken >= PER_SEASON_LIMIT or len(rows) >= MATCH_LIMIT:
                break
    return rows


rows = plan_rows()
if not rows:
    raise SystemExit("FATAL: no matches resolved for the download plan")
with PLAN.open("w", encoding="utf-8", newline="") as fh:
    writer = csv.DictWriter(
        fh,
        fieldnames=["match_id", "local_name", "competition_id", "season_id", "competition_name", "season_name"],
        delimiter="\t",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
print(f"planned_matches={len(rows)} competitions={len({r['competition_id'] for r in rows})}")
PY

# ---- Download the event streams (resumable, bounded, JSON-validated) ----------
is_valid_json_list() {
  python3 - "$1" <<'PY' 2>/dev/null || return 1
import json, sys
obj = json.load(open(sys.argv[1], encoding="utf-8"))
sys.exit(0 if isinstance(obj, list) and len(obj) > 0 else 1)
PY
}

downloaded_total=0
ok=0
while IFS=$'\t' read -r match_id local_name cid sid cname sname; do
  [[ -n "$match_id" && "$match_id" != "match_id" ]] || continue
  target="$DOWNLOAD_DIR/$local_name"
  url="$BASE/data/events/$match_id.json"

  if [[ -s "$target" ]] && [[ "${FORCE_DOWNLOAD:-0}" != "1" ]] && is_valid_json_list "$target"; then
    size="$(wc -c < "$target" | tr -d ' ')"
    echo "cache_hit match_id=$match_id bytes=$size"
  else
    # Stall-based abort (no hard total-time cap); resume partial files.
    if ! curl --globoff -fL --retry 10 --retry-delay 5 \
          --speed-limit 1024 --speed-time 120 \
          --max-filesize "$MAX_FILE_BYTES" \
          -C - -A "$UA" -o "$target" "$url"; then
      echo "  WARN: download failed match_id=$match_id"; rm -f "$target"; continue
    fi
    if ! is_valid_json_list "$target"; then
      echo "  WARN: not a non-empty JSON event list match_id=$match_id"; rm -f "$target"; continue
    fi
    size="$(wc -c < "$target" | tr -d ' ')"
    echo "downloaded match_id=$match_id bytes=$size"
  fi

  downloaded_total=$((downloaded_total + size))
  ok=$((ok + 1))
  if (( downloaded_total > MAX_DOWNLOAD_BYTES )); then
    echo "  reached aggregate download cap ($downloaded_total > $MAX_DOWNLOAD_BYTES); stopping"
    break
  fi
done < <(tail -n +2 "$PLAN")

echo "usable_match_files=$ok downloaded_bytes=$downloaded_total"
if (( ok < MIN_MATCH_COUNT )); then
  echo "FATAL: only $ok usable match files (need >= $MIN_MATCH_COUNT)."
  echo "       Provide match ids via STATSBOMB_MATCHES_FILE=/path/to/ids.txt if upstream is unavailable."
  exit 1
fi

echo "[$(date -Is)] download done dataset=$DATASET_ID matches=$ok"
