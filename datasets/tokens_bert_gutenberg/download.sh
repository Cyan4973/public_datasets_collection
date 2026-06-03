#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="tokens_bert_gutenberg"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
TEXT_DIR="$DOWNLOAD_DIR/texts"
mkdir -p "$LOG_DIR" "$TEXT_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

VOCAB_OUT="$DOWNLOAD_DIR/vocab.txt"
if [ -s "$VOCAB_OUT" ]; then
  vocab_bytes="$(wc -c < "$VOCAB_OUT" | tr -d ' ')"
  echo "cached vocab bytes=$vocab_bytes"
else
  curl -fL --retry 3 --retry-delay 2 -o "$VOCAB_OUT" \
    https://huggingface.co/google-bert/bert-base-uncased/resolve/main/vocab.txt
fi
test -s "$VOCAB_OUT"
test "$(wc -l < "$VOCAB_OUT" | tr -d ' ')" -ge 30000

download_book() {
  local name="$1"
  local url="$2"
  local out="$TEXT_DIR/$name.txt"
  if [ -s "$out" ]; then
    bytes="$(wc -c < "$out" | tr -d ' ')"
    echo "cached book=$name bytes=$bytes"
    return
  fi
  curl -fL --retry 3 --retry-delay 2 \
    -H "User-Agent: Mozilla/5.0 (openzl dataset collection)" \
    -o "$out" "$url"
  test -s "$out"
}

download_book pride_and_prejudice https://www.gutenberg.org/cache/epub/1342/pg1342.txt
download_book origin_of_species https://www.gutenberg.org/cache/epub/1228/pg1228.txt
download_book meditations https://www.gutenberg.org/cache/epub/2680/pg2680.txt
download_book moby_dick https://www.gutenberg.org/cache/epub/2701/pg2701.txt
download_book les_miserables https://www.gutenberg.org/cache/epub/135/pg135.txt
download_book metamorphosis https://www.gutenberg.org/cache/epub/5200/pg5200.txt
download_book leaves_of_grass https://www.gutenberg.org/cache/epub/1322/pg1322.txt
download_book us_constitution https://www.gutenberg.org/cache/epub/5/pg5.txt
download_book frankenstein https://www.gutenberg.org/cache/epub/84/pg84.txt
download_book alice_wonderland https://www.gutenberg.org/cache/epub/11/pg11.txt
download_book sherlock_holmes https://www.gutenberg.org/cache/epub/1661/pg1661.txt
download_book time_machine https://www.gutenberg.org/cache/epub/35/pg35.txt

book_count="$(find "$TEXT_DIR" -maxdepth 1 -type f -name '*.txt' | wc -l | tr -d ' ')"
test "$book_count" = "12"

echo "[$(date -Is)] download done dataset=$DATASET_ID book_count=$book_count"
