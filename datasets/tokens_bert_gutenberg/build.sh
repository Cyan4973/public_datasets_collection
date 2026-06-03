#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="tokens_bert_gutenberg"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import unicodedata
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
text_dir = download_dir / "texts"
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
series_id = "tokens_bert_ids"
series_dir = samples_dir / series_id
vocab_path = download_dir / "vocab.txt"

BOOKS = [
    "alice_wonderland",
    "frankenstein",
    "leaves_of_grass",
    "les_miserables",
    "meditations",
    "metamorphosis",
    "moby_dick",
    "origin_of_species",
    "pride_and_prejudice",
    "sherlock_holmes",
    "time_machine",
    "us_constitution",
]


def rel_data(path: Path) -> str:
    return path.relative_to(data_root).as_posix()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def strip_gutenberg(text: str) -> str:
    start_markers = [
        "*** START OF THIS PROJECT GUTENBERG",
        "*** START OF THE PROJECT GUTENBERG",
        "*END*THE SMALL PRINT",
    ]
    start = 0
    for marker in start_markers:
        idx = text.find(marker)
        if idx != -1:
            nl = text.find("\n", idx)
            if nl != -1:
                start = nl + 1
            break
    end_markers = [
        "*** END OF THIS PROJECT GUTENBERG",
        "*** END OF THE PROJECT GUTENBERG",
        "End of the Project Gutenberg",
        "End of Project Gutenberg",
    ]
    end = len(text)
    for marker in end_markers:
        idx = text.find(marker)
        if idx != -1:
            end = idx
            break
    return text[start:end].strip()


def load_vocab(path: Path) -> dict[str, int]:
    vocab = {}
    with path.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            vocab[line.rstrip("\n")] = idx
    return vocab


def whitespace_tokenize(text: str) -> list[str]:
    return text.strip().split()


def is_punctuation(char: str) -> bool:
    cp = ord(char)
    if (33 <= cp <= 47) or (58 <= cp <= 64) or (91 <= cp <= 96) or (123 <= cp <= 126):
        return True
    return unicodedata.category(char).startswith("P")


def is_whitespace(char: str) -> bool:
    return char in (" ", "\t", "\n", "\r") or unicodedata.category(char) == "Zs"


def is_control(char: str) -> bool:
    if char in ("\t", "\n", "\r"):
        return False
    return unicodedata.category(char).startswith("C")


def clean_text(text: str) -> str:
    output = []
    for ch in text:
        if ord(ch) == 0 or ord(ch) == 0xFFFD or is_control(ch):
            continue
        output.append(" " if is_whitespace(ch) else ch)
    return "".join(output)


def tokenize_basic(text: str) -> list[str]:
    text = clean_text(text).lower()
    normalized = unicodedata.normalize("NFD", text)
    stripped = [ch for ch in normalized if unicodedata.category(ch) != "Mn"]
    text = "".join(stripped)
    tokens = []
    for word in whitespace_tokenize(text):
        buf: list[str] = []
        for ch in word:
            if is_punctuation(ch):
                if buf:
                    tokens.append("".join(buf))
                    buf = []
                tokens.append(ch)
            else:
                buf.append(ch)
        if buf:
            tokens.append("".join(buf))
    return tokens


def wordpiece_tokenize(word: str, vocab: dict[str, int], max_chars: int = 200) -> list[str]:
    if len(word) > max_chars:
        return ["[UNK]"]
    tokens = []
    start = 0
    while start < len(word):
        end = len(word)
        found = None
        while start < end:
            piece = word[start:end]
            if start > 0:
                piece = "##" + piece
            if piece in vocab:
                found = piece
                break
            end -= 1
        if found is None:
            return ["[UNK]"]
        tokens.append(found)
        start = end
    return tokens


if not vocab_path.is_file():
    raise RuntimeError(f"missing vocab: {vocab_path}")
vocab = load_vocab(vocab_path)
if len(vocab) < 30000:
    raise RuntimeError("unexpectedly small BERT vocabulary")

if series_dir.exists():
    shutil.rmtree(series_dir)
series_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

sample_rows = []
stats = {"dataset_id": "tokens_bert_gutenberg", "vocab_size": len(vocab), "series": {series_id: {"files": 0, "values": 0, "bytes": 0}}, "books": []}

for book in BOOKS:
    source_path = text_dir / f"{book}.txt"
    if not source_path.is_file():
        raise RuntimeError(f"missing source file: {source_path}")
    raw_text = source_path.read_text(encoding="utf-8", errors="replace")
    stripped = strip_gutenberg(raw_text)
    basic_tokens = tokenize_basic(stripped)
    token_ids = []
    for tok in basic_tokens:
        for piece in wordpiece_tokenize(tok, vocab):
            token_ids.append(vocab.get(piece, vocab.get("[UNK]", 0)))
    payload = struct.pack("<" + "H" * len(token_ids), *token_ids)
    out_path = series_dir / f"{book}_u16_n{len(token_ids):07d}.bin"
    out_path.write_bytes(payload)
    sample_rows.append({
        "dataset_id": "tokens_bert_gutenberg",
        "series_id": series_id,
        "sample_path": rel_data(out_path),
        "numeric_kind": "uint",
        "bit_width": 16,
        "endianness": "little",
        "element_size_bytes": 2,
        "sample_size_bytes": len(payload),
        "value_count": len(token_ids),
    })
    stats["series"][series_id]["files"] += 1
    stats["series"][series_id]["values"] += len(token_ids)
    stats["series"][series_id]["bytes"] += len(payload)
    stats["books"].append({
        "book": book,
        "source_file": rel_data(source_path),
        "source_sha256": sha256_file(source_path),
        "tokens": len(token_ids),
        "chars_after_strip": len(stripped),
        "sample_file": rel_data(out_path),
        "sample_sha256": sha256_file(out_path),
    })

(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sample_rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
