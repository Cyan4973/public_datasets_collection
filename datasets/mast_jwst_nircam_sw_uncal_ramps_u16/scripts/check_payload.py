#!/usr/bin/env python3
"""download.sh helpers: semantic validation of fetched payloads.

  check_payload.py uncal <path> <sources.tsv> <filename>  -> prints sha256 on success
  check_payload.py evidence <path>                         -> MAST data-use policy check
"""
from __future__ import annotations

import hashlib
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jwst_uncal as ju  # noqa: E402


def check_uncal(path: Path, sources_path: Path, filename: str) -> None:
    rows = [r for r in ju.read_sources(sources_path) if r["filename"] == filename]
    if len(rows) != 1:
        raise ju.UncalError(f"{filename}: not exactly one row in sources.tsv")
    source = rows[0]
    buf = path.read_bytes()
    if len(buf) != int(source["size_bytes"]):
        raise ju.UncalError(f"{filename}: size {len(buf)} != pinned {source['size_bytes']}")
    crc = ju.crc64nvme_b64(buf)
    if crc != source["crc64nvme"]:
        raise ju.UncalError(f"{filename}: CRC64-NVME {crc} != pinned S3 checksum {source['crc64nvme']}")
    sci = ju.validate(buf, source)
    # Cheap degeneracy probe on the decoded cube: strided values must not be constant.
    start = sci["data_offset"]
    step = 2 * 4099  # odd word stride spreads the probe over rows and groups
    probe = {buf[i] << 8 | buf[i + 1] for i in range(start, start + sci["data_len"] - 1, step)}
    if len(probe) < 64:
        raise ju.UncalError(f"{filename}: SCI cube looks degenerate ({len(probe)} distinct probe values)")
    digest = hashlib.sha256(buf).hexdigest()
    if source.get("sha256") and digest != source["sha256"]:
        raise ju.UncalError(f"{filename}: SHA-256 {digest} != pinned {source['sha256']}")
    print(digest)


def check_evidence(path: Path) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S | re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"\s+", " ", text)
    needle = "Most data hosted at MAST are in the public domain"
    if needle not in text:
        raise SystemExit("MAST data-use page no longer states the public-domain default")
    # The copyrighted-collections list runs from the "Copyrighted Data" heading to the
    # paragraph that follows the bullet list ("Scientists and educators ..."). Note that
    # "DSS Copyright Holders" already occurs inside the first bullet, so it is not a usable end.
    start = text.find("Copyrighted Data")
    stop = text.find("Scientists and educators", start)
    if start < 0 or stop < 0 or stop - start > 2000:
        raise SystemExit("MAST data-use page lacks the copyrighted-collections section")
    section = text[start:stop]
    if "Digitized Sky Survey" not in section or "Guide Star Catalogs" not in section \
            or re.search(r"\bJWST\b|\bWebb\b|NIRCam", section, flags=re.I):
        raise SystemExit("MAST copyrighted-collections list changed or now names JWST")
    print("evidence_ok public_domain_default=yes jwst_in_copyrighted_list=no")


def main() -> int:
    mode = sys.argv[1]
    if mode == "uncal":
        check_uncal(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4])
    elif mode == "evidence":
        check_evidence(Path(sys.argv[2]))
    else:
        raise SystemExit(f"unknown mode {mode}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ju.UncalError, KeyError, ValueError) as exc:
        print(f"payload rejected: {exc}", file=sys.stderr)
        sys.exit(3)
