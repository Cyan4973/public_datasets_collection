#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="chesscom_blitz_games"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGES_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$PAGES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

# Chess.com asks for a descriptive User-Agent; without one the API returns 403.
UA="${CHESSCOM_UA:-openzl-public-datasets-collection/1.0 (numeric corpus collector)}"
PLAYERS_MAX="${CHESSCOM_PLAYERS_MAX:-50}"
MONTHS_MAX="${CHESSCOM_MONTHS_MAX:-24}"
SLEEP="${CHESSCOM_SLEEP:-0.3}"
API="https://api.chess.com/pub"

# Small request used for the leaderboard + archive-list pulls (each is tiny JSON).
get() { curl -fsS -H "User-Agent: $UA" --retry 5 --retry-delay 3 --max-time 120 "$@"; }

echo "[$(date -Is)] download start dataset=$DATASET_ID players_max=$PLAYERS_MAX months_max=$MONTHS_MAX"

# ---- 1. Build the player list ---------------------------------------------
# Seed from the live leaderboards (blitz first, then bullet/rapid for breadth);
# all of a player's games are later filtered to blitz, so the leaderboard only
# selects *who* to crawl. A small high-confidence fallback covers a leaderboard
# fetch failure.
PLAYERS_FILE="$DOWNLOAD_DIR/players.txt"
FALLBACK="hikaru magnuscarlsen danielnaroditsky firouzja2003 nihalsarin anishgiri gothamchess fabianocaruana"
{
  if get "$API/leaderboards" -o "$DOWNLOAD_DIR/leaderboards.json"; then
    jq -r '(.live_blitz[]?, .live_bullet[]?, .live_rapid[]?) | .username' \
      "$DOWNLOAD_DIR/leaderboards.json" 2>/dev/null || true
  fi
  printf '%s\n' $FALLBACK
} | tr 'A-Z' 'a-z' | awk 'NF && !seen[$0]++' | head -n "$PLAYERS_MAX" > "$PLAYERS_FILE"
echo "[$(date -Is)] players=$(wc -l < "$PLAYERS_FILE")"

# ---- 2. Crawl each player's recent monthly archives -----------------------
fetched=0; skipped=0; players=0
while IFS= read -r player; do
  [ -n "$player" ] || continue
  players=$((players+1))
  archives="$(get "$API/player/$player/games/archives" 2>/dev/null \
              | jq -r '.archives[]?' 2>/dev/null | tail -n "$MONTHS_MAX")" || {
    echo "[$(date -Is)] warn no_archives player=$player"; continue; }
  for url in $archives; do
    mm="${url##*/}"; rest="${url%/*}"; yyyy="${rest##*/}"
    out="$PAGES_DIR/${player}__${yyyy}_${mm}.json"
    if [ -s "$out" ]; then skipped=$((skipped+1)); continue; fi
    tmp="$out.tmp"; rm -f "$tmp"
    if get "$url" -o "$tmp" && jq -e '.games' "$tmp" >/dev/null 2>&1; then
      mv "$tmp" "$out"; fetched=$((fetched+1))
    else
      rm -f "$tmp"; echo "[$(date -Is)] warn fetch_failed url=$url"
    fi
    sleep "$SLEEP"
  done
done < "$PLAYERS_FILE"

echo "[$(date -Is)] download done dataset=$DATASET_ID players=$players fetched=$fetched skipped=$skipped pages=$(ls "$PAGES_DIR" | wc -l)"
