#!/usr/bin/env python3
"""Check the NIH FAQ_CHESTXRAY.pdf licence evidence.

Verifies the pinned size and SHA-256, then extracts the text drawn by the
PDF's Flate-compressed content streams (Tj/TJ string operands) and requires
the Q04 'usage ... is unrestricted' sentence after whitespace normalisation.

Usage: faq_check.py <FAQ_CHESTXRAY.pdf>
"""
from __future__ import annotations

import hashlib
import re
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nih_pins as pins  # noqa: E402


def pdf_text(data: bytes) -> str:
    pieces: list[bytes] = []
    for match in re.finditer(rb"stream\r?\n", data):
        start = match.end()
        end = data.find(b"endstream", start)
        try:
            content = zlib.decompressobj().decompress(data[start:end])
        except zlib.error:
            continue
        if b"BT" not in content:
            continue
        for op in re.finditer(rb"\[(.*?)\]\s*TJ|\(((?:\\.|[^\\)])*)\)\s*Tj", content, re.S):
            if op.group(1) is not None:
                pieces.extend(re.findall(rb"\(((?:\\.|[^\\)])*)\)", op.group(1)))
            else:
                pieces.append(op.group(2))
    text = b"".join(pieces).decode("latin-1")
    text = re.sub(r"\\(.)", r"\1", text)
    return re.sub(r"\s+", " ", text)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    data = Path(argv[1]).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != pins.FAQ_BYTES or digest != pins.FAQ_SHA256:
        raise SystemExit(f"FATAL: FAQ_CHESTXRAY.pdf is {len(data)} bytes sha256 {digest}; expected {pins.FAQ_BYTES} {pins.FAQ_SHA256}")
    if not data.startswith(b"%PDF-"):
        raise SystemExit("FATAL: FAQ_CHESTXRAY.pdf is not a PDF")
    text = pdf_text(data)
    sentence = re.sub(r"\s+", " ", pins.FAQ_LICENSE_SENTENCE)
    if sentence not in text or "Are there any restrictions in using this dataset?" not in text:
        raise SystemExit("FATAL: FAQ Q04 licence sentence not found in extracted PDF text")
    print(f"faq_validation=ok bytes={len(data)} sha256={digest} q04='{sentence}'")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
