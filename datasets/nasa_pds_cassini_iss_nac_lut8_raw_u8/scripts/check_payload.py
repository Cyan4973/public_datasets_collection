#!/usr/bin/env python3
"""download.sh helpers: semantic validation of fetched payloads.

  check_payload.py frame <img> <product> <image_number>   -> prints "<md5> <sha256>" of the IMG
  check_payload.py index <index_dir> <sources.tsv>         -> selection re-derived from the 3 indexes must equal sources.tsv
  check_payload.py evidence <aareadme.txt>                 -> volume id / data set present, no use restriction text
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coiss  # noqa: E402


def check_frame(img: Path, product: str, image_number: str) -> str:
    raw = img.read_bytes()
    _pixels, stats = coiss.decode(raw, product, image_number)
    if stats["minimum"] == stats["maximum"]:
        raise coiss.FrameError(f"{product}: constant frame")
    md5, sha = coiss.digests(raw)
    return f"{md5} {sha}"


def check_index(index_dir: Path, sources: Path) -> None:
    rows = []
    for vol in coiss.VOLUMES:
        label = (index_dir / f"{vol}_index.lbl").read_text(encoding="ascii")
        rows += coiss.parse_index((index_dir / f"{vol}_index.tab").read_bytes(), label, vol)
    selected = coiss.select(rows)
    pinned = coiss.read_sources(sources)
    derived = coiss.selection_keys(selected)
    expected = [(s["volume"], s["file_specification_name"], s["image_number"]) for s in pinned]
    if derived != expected:
        raise coiss.FrameError(
            f"selection re-derived from the indexes ({len(derived)} frames) differs from sources.tsv ({len(expected)})")
    if any(r["DATA_SET_ID"] != "CO-S-ISSNA/ISSWA-2-EDR-V1.0" for r in selected):
        raise coiss.FrameError("selected row with unexpected DATA_SET_ID")
    print(f"index_ok rows={len(rows)} eligible={sum(coiss.eligible(r) for r in rows)} selected={len(selected)}")


def check_evidence(path: Path) -> None:
    text = " ".join(path.read_text(encoding="ascii", errors="replace").split())
    for needle in ("Volume ID: COISS_2050", "CASSINI IMAGING SCIENCE SUBSYSTEM EDR AND CALIBRATION FILES",
                   "Cognizant Persons & Acknowledgments"):
        if needle not in text:
            raise coiss.FrameError(f"aareadme.txt lacks {needle!r}")
    for forbidden in ("copyright", "all rights reserved"):
        if forbidden in text.lower():
            raise coiss.FrameError(f"aareadme.txt unexpectedly mentions {forbidden!r}")
    print("evidence_ok aareadme=COISS_2050 copyright_text=absent")


def main() -> int:
    mode = sys.argv[1]
    if mode == "frame":
        print(check_frame(Path(sys.argv[2]), sys.argv[3], sys.argv[4]))
    elif mode == "index":
        check_index(Path(sys.argv[2]), Path(sys.argv[3]))
    elif mode == "evidence":
        check_evidence(Path(sys.argv[2]))
    else:
        raise SystemExit(f"unknown mode {mode}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (coiss.FrameError, UnicodeDecodeError, KeyError, ValueError) as exc:
        print(f"payload rejected: {exc}", file=sys.stderr)
        sys.exit(3)
