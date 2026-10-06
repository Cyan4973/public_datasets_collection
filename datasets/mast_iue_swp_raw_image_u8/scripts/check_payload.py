#!/usr/bin/env python3
"""download.sh helpers: semantic validation of fetched payloads.

  check_payload.py rilo <path> <image_no> <crc32> <isize>   -> prints sha256 on success
  check_payload.py evidence <path>                            -> MAST data-use policy check
"""
from __future__ import annotations

import hashlib
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import iue_rilo as rilo  # noqa: E402


def check_rilo(path: Path, image_no: int, crc32: str, isize: int) -> None:
    raw = rilo.gunzip_checked(path, crc32, isize)
    pixels, _cards = rilo.decode(raw, image_no)
    if min(pixels) == max(pixels):
        raise rilo.RiloError(f"image {image_no}: constant frame")
    print(hashlib.sha256(path.read_bytes()).hexdigest())


def check_evidence(path: Path) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S | re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"\s+", " ", text)
    needle = "Most data hosted at MAST are in the public domain"
    if needle not in text:
        raise SystemExit("MAST data-use page no longer states the public-domain default")
    start = text.find("Copyrighted Data")
    stop = text.find("DSS Copyright Holders", start)
    if start < 0 or stop < 0:
        raise SystemExit("MAST data-use page lacks the copyrighted-collections section")
    section = text[start:stop]
    if "Digitized Sky Survey" not in section or re.search(r"\bIUE\b|International Ultraviolet", section):
        raise SystemExit("MAST copyrighted-collections list changed or now names IUE")
    print("evidence_ok public_domain_default=yes iue_in_copyrighted_list=no")


def main() -> int:
    mode = sys.argv[1]
    if mode == "rilo":
        check_rilo(Path(sys.argv[2]), int(sys.argv[3]), sys.argv[4], int(sys.argv[5]))
    elif mode == "evidence":
        check_evidence(Path(sys.argv[2]))
    else:
        raise SystemExit(f"unknown mode {mode}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except rilo.RiloError as exc:
        print(f"payload rejected: {exc}", file=sys.stderr)
        sys.exit(3)
