#!/usr/bin/env python3
"""Semantic payload checks used by download.sh.

  check_payload.py label <lbl> <product_id> <dat_size> <start_time>
      Validate a detached frame label against the pinned product.
  check_payload.py dat <dat> <lbl> <product_id> <start_time>
      Validate a complete DAT: label consistency, Voyager 1 header string,
      record walk with the shared line rule, at least one kept line.
      Prints "<sha256> <kept_lines> <values>".
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vgpws  # noqa: E402


def main(argv: list[str]) -> int:
    mode = argv[1]
    if mode == "label":
        lbl, product, dat_size, start = argv[2], argv[3], int(argv[4]), argv[5]
        vgpws.check_label(Path(lbl).read_text(encoding="latin-1"), product, dat_size, start)
        return 0
    if mode == "dat":
        dat, lbl, product, start = argv[2], argv[3], argv[4], argv[5]
        data = Path(dat).read_bytes()
        meta = vgpws.check_label(Path(lbl).read_text(encoding="latin-1"), product, len(data), start)
        payload, stats = vgpws.extract(data)
        if stats["data_records"] != meta["file_records"] - 1:
            raise SystemExit(f"{product}: walked {stats['data_records']} data records, label implies "
                             f"{meta['file_records'] - 1}")
        if not stats["kept_lines"]:
            raise SystemExit(f"{product}: no waveform line survives the line rule: {stats}")
        print(hashlib.sha256(data).hexdigest(), stats["kept_lines"], len(payload))
        return 0
    raise SystemExit(f"unknown mode {mode}")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
