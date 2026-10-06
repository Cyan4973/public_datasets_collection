#!/usr/bin/env python3
"""download.sh helpers: semantic validation of fetched payloads.

  check_payload.py frame <img> <lbl> <image_number> <product>  -> prints "<md5> <sha256>" of the IMG
  check_payload.py label <lbl> <image_number> <product>        -> prints md5 of the label
  check_payload.py index <INDEX.TAB> <INDEX.LBL> <sources.tsv> -> selection re-derived from the index must equal sources.tsv
  check_payload.py evidence <AAREADME.TXT>                     -> data-set id and citation request present
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vgiss  # noqa: E402


def check_label(lbl: Path, image_number: str, product: str) -> str:
    blob = lbl.read_bytes()
    vgiss.check_label(blob.decode("ascii"), image_number, product)
    return vgiss.digests(blob)[0]


def check_frame(img: Path, lbl: Path, image_number: str, product: str) -> str:
    check_label(lbl, image_number, product)
    raw = img.read_bytes()
    pixels, stats = vgiss.decode(raw, image_number, product)
    if stats["minimum"] == stats["maximum"]:
        raise vgiss.FrameError(f"{product}: constant frame")
    md5, sha = vgiss.digests(raw)
    return f"{md5} {sha}"


def check_index(tab: Path, lbl: Path, sources: Path) -> None:
    label = lbl.read_text(encoding="ascii")
    for needle in ("ROW_BYTES                    = 395", "VOLUME_ID                       = VGISS_0005",
                   'DATA_SET_ID                     = "VG1/VG2-S-ISS-2/3/4/6-PROCESSED-V1.0"'):
        if needle not in label:
            raise vgiss.FrameError(f"INDEX.LBL lacks {needle!r}")
    rows = vgiss.parse_index(tab)
    if f"ROWS                         = {len(rows)}" not in label:
        raise vgiss.FrameError(f"INDEX.TAB has {len(rows)} rows, label disagrees")
    selected = vgiss.select(rows)
    pinned = vgiss.read_sources(sources)
    derived = [(r["image_number"], r["file_specification_name"][: -len(".LBL")]) for r in selected]
    expected = [(r["image_number"], r["volume_path"]) for r in pinned]
    if derived != expected:
        raise vgiss.FrameError(f"selection re-derived from INDEX.TAB ({len(derived)} frames) differs from sources.tsv ({len(expected)})")
    print(f"index_ok rows={len(rows)} selected={len(selected)}")


def check_evidence(path: Path) -> None:
    text = " ".join(path.read_text(encoding="ascii", errors="replace").split())
    needles = [
        'DATA_SET_ID = "VG1/VG2-S-ISS-2/3/4/6-PROCESSED-V1.0"',
        "please cite the work of the PDS Rings Node",
        "Showalter, M.R., M.K. Gordon, and D. Olson, VG1/VG2 SATURN ISS PROCESSED IMAGES V1.0, VGISS_0001-0038, NASA Planetary Data System, 2006.",
        "Cnnnnnnn_RAW.IMG: uncompressed, raw image.",
    ]
    for needle in needles:
        if needle not in text:
            raise vgiss.FrameError(f"AAREADME.TXT lacks {needle!r}")
    print("evidence_ok citation_request=present")


def main() -> int:
    mode = sys.argv[1]
    if mode == "frame":
        print(check_frame(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], sys.argv[5]))
    elif mode == "label":
        print(check_label(Path(sys.argv[2]), sys.argv[3], sys.argv[4]))
    elif mode == "index":
        check_index(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
    elif mode == "evidence":
        check_evidence(Path(sys.argv[2]))
    else:
        raise SystemExit(f"unknown mode {mode}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (vgiss.FrameError, UnicodeDecodeError) as exc:
        print(f"payload rejected: {exc}", file=sys.stderr)
        sys.exit(3)
