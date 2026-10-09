#!/usr/bin/env python3
"""Download-time semantic validation for the JunoCam perijove lossless colour EDR recipe.

  check_payload.py evidence <AAREADME.TXT> <SIS.HTM>
  check_payload.py candidates <index_dir> <candidates.tsv>
  check_payload.py selection <index_dir> <label_dir> <candidates.tsv> <sources.tsv>
  check_payload.py image <IMG> <LBL> <product_id> <orbit>     -> prints "<md5> <sha256>"
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import junocam as jc  # noqa: E402


def fail(message: str) -> None:
    print(f"FATAL {message}", file=sys.stderr)
    raise SystemExit(1)


def evidence(readme: Path, sis: Path) -> None:
    text = readme.read_text(encoding="latin-1")
    for needle in ("JUNO JUNOCAM EXPERIMENT DATA RECORD (EDR)", "National Aeronautics and Space Administration",
                   "Planetary Data System"):
        if needle.lower() not in " ".join(text.split()).lower():
            fail(f"AAREADME lacks {needle!r}")
    doc = " ".join(sis.read_text(encoding="latin-1").split())
    for needle in ("Huffman (lossless)", "1648 pixels wide and 128 pixels high", "zero-filled by the decompression software"):
        if needle not in doc:
            fail(f"SIS lacks {needle!r}")
    print("evidence_ok")


def candidates(index_dir: Path, pinned_path: Path) -> list[dict]:
    derived = jc.candidates(index_dir)
    pinned = jc.read_tsv(pinned_path)
    got = [(c["product_id"], c["volume"], str(c["orbit"]), str(c["rel_minutes"]), c["label_md5"]) for c in derived]
    want = [(p["product_id"], p["volume"], p["orbit"], p["rel_minutes"], p["label_md5"]) for p in pinned]
    if got != want:
        missing = sorted(set(want) - set(got))[:5]
        extra = sorted(set(got) - set(want))[:5]
        fail(f"candidate list re-derived from INDEX.TAB differs from candidates.tsv (pinned-only {missing}, derived-only {extra})")
    print(f"candidates_ok n={len(derived)} orbits={len({c['orbit'] for c in derived})}")
    return derived


def selection(index_dir: Path, label_dir: Path, cand_path: Path, sources_path: Path) -> None:
    derived = candidates(index_dir, cand_path)
    for cand in derived:
        data = (label_dir / f"{cand['product_id']}.LBL").read_bytes()
        if hashlib.md5(data).hexdigest() != cand["label_md5"]:
            fail(f"label MD5 mismatch for {cand['product_id']}")
    chosen = jc.select(derived, label_dir)
    got = [(c["product_id"], c["volume"], str(c["orbit"]), str(c["lines"]), str(c["img_size"]), c["img_md5"]) for c in chosen]
    want = [(s["product_id"], s["volume"], s["orbit"], s["lines"], s["img_size"], s["img_md5"]) for s in jc.read_tsv(sources_path)]
    if got != want:
        fail(f"selection re-derived from labels differs from sources.tsv: derived {got[:3]}... pinned {want[:3]}...")
    print(f"selection_ok n={len(chosen)}")


def image(img: Path, lbl: Path, product_id: str, orbit: int) -> None:
    label = jc.parse_label(lbl.read_text(encoding="latin-1"))
    problems = jc.label_checks(label, product_id, orbit)
    if problems:
        fail(f"{product_id}: label deviates: {'; '.join(problems)}")
    lines = int(label["IMAGE.LINES"])
    size = img.stat().st_size
    if size != lines * jc.LINE_SAMPLES:
        fail(f"{product_id}: IMG size {size} != LINES {lines} x {jc.LINE_SAMPLES}")
    md5 = hashlib.md5()
    sha = hashlib.sha256()
    seen = set()
    with open(img, "rb") as handle:
        while chunk := handle.read(1 << 22):
            md5.update(chunk)
            sha.update(chunk)
            if len(seen) < 2:
                seen.update(chunk[:: 4097])
    if md5.hexdigest() != label["IMAGE.MD5_CHECKSUM"].lower():
        fail(f"{product_id}: IMG MD5 {md5.hexdigest()} != label IMAGE MD5_CHECKSUM {label['IMAGE.MD5_CHECKSUM']}")
    if len(seen) < 2:
        fail(f"{product_id}: IMG looks constant")
    print(md5.hexdigest(), sha.hexdigest())


def main() -> None:
    args = sys.argv[1:]
    if not args:
        fail(__doc__)
    command, rest = args[0], args[1:]
    if command == "evidence" and len(rest) == 2:
        evidence(Path(rest[0]), Path(rest[1]))
    elif command == "candidates" and len(rest) == 2:
        candidates(Path(rest[0]), Path(rest[1]))
    elif command == "selection" and len(rest) == 4:
        selection(*(Path(x) for x in rest))
    elif command == "image" and len(rest) == 4:
        image(Path(rest[0]), Path(rest[1]), rest[2], int(rest[3]))
    else:
        fail(__doc__)


if __name__ == "__main__":
    main()
