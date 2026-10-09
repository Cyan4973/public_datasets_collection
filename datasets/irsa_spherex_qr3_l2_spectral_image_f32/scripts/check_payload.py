#!/usr/bin/env python3
"""download.sh validator (no network I/O).

  check_payload.py evidence-license <html>   NASA science-data license page must grant CC0
  check_payload.py evidence-irsa <html>      IRSA SPHEREx page must carry the acknowledgement
  check_payload.py prefix <file> <sources.tsv> <name>
      PRIMARY+IMAGE prefix: size, pinned header SHA-256, header regime, IMAGE data sanity.
      Prints the SHA-256 of the whole prefix on success.
"""
from __future__ import annotations

import csv
import hashlib
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spherex_fits as sf  # noqa: E402


def page_text(path: Path) -> str:
    t = path.read_text(encoding="utf-8", errors="replace")
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", t)


def fail(msg: str) -> None:
    print(f"FATAL {msg}", file=sys.stderr)
    raise SystemExit(1)


def load_row(sources: Path, name: str) -> dict:
    with sources.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            if row["name"] == name:
                return row
    fail(f"{name} not pinned in {sources}")
    return {}


def main() -> None:
    mode = sys.argv[1]
    if mode == "evidence-license":
        t = page_text(Path(sys.argv[2]))
        need = ["data that is provided from a NASA-led mission", "licensed as Creative Commons Zero",
                "There are no restrictions on the usage of these data"]
        missing = [s for s in need if s not in t]
        if missing:
            fail(f"license page no longer carries {missing}")
        print("license_evidence_ok CC0 sentence present")
        return
    if mode == "evidence-irsa":
        t = page_text(Path(sys.argv[2]))
        need = ["SPHEREx", "This publication makes use of data products from the Spectro-Photometer",
                "funded by the National Aeronautics and Space Administration"]
        missing = [s for s in need if s not in t]
        if missing:
            fail(f"IRSA SPHEREx page no longer carries {missing}")
        print("irsa_evidence_ok acknowledgement present")
        return
    if mode != "prefix":
        fail(f"unknown mode {mode}")
    path, sources, name = Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
    row = load_row(sources, name)
    buf = path.read_bytes()
    if len(buf) != int(row["prefix_bytes"]):
        fail(f"{name}: {len(buf)} bytes, expected {row['prefix_bytes']}")
    off = int(row["data_offset"])
    if sf.sha256_bytes(buf[:off]) != row["header_sha256"]:
        fail(f"{name}: header bytes differ from the pinned header SHA-256")
    try:
        info = sf.walk_prefix(buf)
    except (sf.FitsError, UnicodeDecodeError) as exc:
        fail(f"{name}: FITS walk failed: {exc}")
    if info["data_offset"] != off or info["prefix_bytes"] != len(buf):
        fail(f"{name}: data offset {info['data_offset']} differs from pin {off}")
    bad = sf.check_regime(info, name)
    if bad:
        fail(f"{name}: header regime violations {bad}")
    if info["image"].get("OBSID") != row["obsid"] or str(info["image"].get("EXPIDN")) != row["expidn"]:
        fail(f"{name}: OBSID/EXPIDN differ from pin")
    st = sf.image_stats(sf.decode_be_f32(buf[off:]))
    probs = sf.stats_problems(st)
    if probs:
        fail(f"{name}: degenerate IMAGE data {probs}")
    print(f"{name} nan={st['nan_count']} distinct={st['distinct_bit_patterns']} "
          f"mean={st['finite_mean']:.4f}", file=sys.stderr)
    print(hashlib.sha256(buf).hexdigest())


if __name__ == "__main__":
    main()
