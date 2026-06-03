#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="tokens_t5_gutenberg"
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
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
text_dir = download_dir / "texts"
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
series_id = "tokens_t5_ids"
series_dir = samples_dir / series_id
tok_path = download_dir / "tokenizer.json"
SPIECE_UNDERLINE = "\u2581"

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


class T5Tokenizer:
    def __init__(self, path: Path):
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        model = data["model"]
        vocab_list = model["vocab"]
        self.unk_id = model.get("unk_id", 2)
        self.vocab: dict[str, tuple[int, float]] = {}
        for i, (token, score) in enumerate(vocab_list):
            self.vocab[token] = (i, score)
        self.max_token_len = max(len(t) for t in self.vocab)

    def _tokenize_inner(self, text: str) -> list[int]:
        n = len(text)
        if n == 0:
            return []
        neg_inf = float("-inf")
        best = [(neg_inf, -1, -1)] * (n + 1)
        best[0] = (0.0, -1, -1)
        for i in range(n):
            if best[i][0] == neg_inf:
                continue
            max_len = min(self.max_token_len, n - i)
            for length in range(1, max_len + 1):
                piece = text[i:i + length]
                entry = self.vocab.get(piece)
                if entry is None:
                    continue
                tid, score = entry
                new_score = best[i][0] + score
                if new_score > best[i + length][0]:
                    best[i + length] = (new_score, tid, i)
        if best[n][0] == neg_inf:
            return [self.unk_id] * n
        out = []
        pos = n
        while pos > 0:
            _, tid, prev = best[pos]
            out.append(tid)
            pos = prev
        out.reverse()
        return out

    def encode(self, text: str) -> list[int]:
        token_ids = []
        for word in text.split():
            token_ids.extend(self._tokenize_inner(SPIECE_UNDERLINE + word))
        return token_ids


if not tok_path.is_file():
    raise RuntimeError(f"missing tokenizer: {tok_path}")
tokenizer = T5Tokenizer(tok_path)
if len(tokenizer.vocab) < 30000:
    raise RuntimeError("unexpectedly small tokenizer vocabulary")

if series_dir.exists():
    shutil.rmtree(series_dir)
series_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

sample_rows = []
stats = {"dataset_id": "tokens_t5_gutenberg", "vocab_size": len(tokenizer.vocab), "series": {series_id: {"files": 0, "values": 0, "bytes": 0}}, "books": []}

for book in BOOKS:
    source_path = text_dir / f"{book}.txt"
    if not source_path.is_file():
        raise RuntimeError(f"missing source file: {source_path}")
    raw_text = source_path.read_text(encoding="utf-8", errors="replace")
    stripped = strip_gutenberg(raw_text)
    token_ids = tokenizer.encode(stripped)
    payload = struct.pack("<" + "H" * len(token_ids), *token_ids)
    out_path = series_dir / f"{book}_u16_n{len(token_ids):07d}.bin"
    out_path.write_bytes(payload)
    sample_rows.append({
        "dataset_id": "tokens_t5_gutenberg",
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
