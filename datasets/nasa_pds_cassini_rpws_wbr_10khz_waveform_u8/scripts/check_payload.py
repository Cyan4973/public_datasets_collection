#!/usr/bin/env python3
"""Semantic payload checks used by download.sh.

  check_payload.py label <lbl> <product> <dat_size> <record_bytes>
      Validate a detached label (rpws.check_label) and its RECORD_BYTES pin.
  check_payload.py dat <dat> <lbl> <product> <record_bytes>
      Walk every record of a complete DAT file: RECORD_BYTES in every prefix
      equals the label, SAMPLES within capacity, at least one record kept by
      the Ex / 10-kHz selection rule. Prints "<sha256> <kept_values>".
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rpws  # noqa: E402


def main(argv: list[str]) -> int:
    mode = argv[1]
    if mode == "label":
        lbl, product, dat_size, record_bytes = argv[2], argv[3], int(argv[4]), int(argv[5])
        meta = rpws.check_label(Path(lbl).read_text(encoding="latin-1"), product, dat_size)
        if meta["record_bytes"] != record_bytes:
            raise SystemExit(f"{product}: label RECORD_BYTES {meta['record_bytes']} != pinned {record_bytes}")
        return 0
    if mode == "dat":
        dat, lbl, product, record_bytes = argv[2], argv[3], argv[4], int(argv[5])
        data = Path(dat).read_bytes()
        meta = rpws.check_label(Path(lbl).read_text(encoding="latin-1"), product, len(data))
        if meta["record_bytes"] != record_bytes:
            raise SystemExit(f"{product}: label RECORD_BYTES {meta['record_bytes']} != pinned {record_bytes}")
        payload, stats = rpws.extract(data, record_bytes)
        if stats["records"] != meta["file_records"]:
            raise SystemExit(f"{product}: parsed {stats['records']} records, label says {meta['file_records']}")
        if not payload:
            raise SystemExit(f"{product}: no Ex 10-kHz records survive the selection rule: {stats}")
        print(hashlib.sha256(data).hexdigest(), len(payload))
        return 0
    raise SystemExit(f"unknown mode {mode}")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
