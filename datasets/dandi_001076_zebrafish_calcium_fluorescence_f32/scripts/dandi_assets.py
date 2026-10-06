#!/usr/bin/env python3
"""Parse and validate DANDI:001076 draft metadata fetched by download.sh.

Standard library only (no PyYAML): DANDI's S3 ``dandisets/<id>/draft/*.yaml``
files are machine-written with a fixed two-space layout, so the handful of
fields used here are extracted with anchored regular expressions and every
item must yield every field exactly once.

Commands:
  license <dandiset.yaml>             assert identity, open access, CC-BY-4.0
  compare <assets.yaml> <assets.tsv>  assert the draft asset set equals the pin
  table <assets.yaml>                 print the identity columns (discovery aid)
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

DANDISET = "001076"
EXPECTED_NAME = "OMR Robot CaImaging"
EXPECTED_LICENSE = "spdx:CC-BY-4.0"
ASSET_FIELDS = ("asset_path", "asset_id", "blob_url", "size_bytes", "sha256")
BLOB_RE = re.compile(r"^https://dandiarchive\.s3\.amazonaws\.com/blobs/[0-9a-f]{3}/[0-9a-f]{3}/[0-9a-f-]{36}$")


def one(pattern: str, text: str, what: str) -> str:
    hits = re.findall(pattern, text, flags=re.MULTILINE)
    if len(hits) != 1:
        raise ValueError(f"expected one {what}, found {len(hits)}")
    return hits[0]


def check_license(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if one(r"^identifier: (\S+)$", text, "identifier") != f"DANDI:{DANDISET}":
        raise ValueError("dandiset.yaml identifier changed")
    if one(r"^name: (.+)$", text, "name").strip() != EXPECTED_NAME:
        raise ValueError("dandiset.yaml name changed")
    licenses = re.findall(r"^license:\n((?:- .+\n)+)", text, flags=re.MULTILINE)
    if len(licenses) != 1 or [line[2:].strip() for line in licenses[0].splitlines()] != [EXPECTED_LICENSE]:
        raise ValueError(f"dandiset.yaml license changed: {licenses}")
    if "status: dandi:OpenAccess" not in text:
        raise ValueError("dandiset.yaml no longer declares dandi:OpenAccess")
    print(f"license_validation=ok dandiset=DANDI:{DANDISET} license={EXPECTED_LICENSE} access=dandi:OpenAccess")


def parse_assets(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("- '@context'"):
        raise ValueError("assets.yaml does not start with an asset list item")
    rows = []
    for item in text.split("\n- '@context'"):
        blobs = re.findall(r"^  - (https://dandiarchive\.s3\.amazonaws\.com/blobs/\S+)$", item, flags=re.MULTILINE)
        if len(blobs) != 1:
            raise ValueError(f"expected one S3 blob contentUrl per asset, found {len(blobs)}")
        row = {
            "asset_path": one(r"^  path: (\S+)$", item, "path"),
            "asset_id": one(r"^  identifier: ([0-9a-f-]{36})$", item, "identifier"),
            "blob_url": blobs[0],
            "size_bytes": one(r"^  contentSize: (\d+)$", item, "contentSize"),
            "sha256": one(r"^    dandi:sha2-256: ([0-9a-f]{64})$", item, "dandi:sha2-256"),
        }
        if one(r"^  encodingFormat: (\S+)$", item, "encodingFormat") != "application/x-nwb":
            raise ValueError(f"unexpected encodingFormat for {row['asset_path']}")
        if not BLOB_RE.match(row["blob_url"]):
            raise ValueError(f"unexpected blob URL shape {row['blob_url']}")
        rows.append(row)
    rows.sort(key=lambda row: row["asset_path"])
    return rows


def load_pinned(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    rows.sort(key=lambda row: row["asset_path"])
    return rows


def compare(assets_yaml: Path, pinned_tsv: Path) -> None:
    live = {tuple(row[key] for key in ASSET_FIELDS) for row in parse_assets(assets_yaml)}
    pinned = {tuple(row[key] for key in ASSET_FIELDS) for row in load_pinned(pinned_tsv)}
    if live != pinned:
        added = sorted(live - pinned)
        removed = sorted(pinned - live)
        raise ValueError(
            f"draft asset set changed: {len(added)} new/changed, {len(removed)} missing/changed; "
            f"first new={added[:1]} first missing={removed[:1]}"
        )
    total = sum(int(row[3]) for row in live)
    print(f"asset_set_validation=ok assets={len(live)} bytes={total}")


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "license":
        check_license(Path(sys.argv[2]))
    elif len(sys.argv) >= 4 and sys.argv[1] == "compare":
        compare(Path(sys.argv[2]), Path(sys.argv[3]))
    elif len(sys.argv) >= 3 and sys.argv[1] == "table":
        print("\t".join(ASSET_FIELDS))
        for row in parse_assets(Path(sys.argv[2])):
            print("\t".join(row[key] for key in ASSET_FIELDS))
    else:
        raise SystemExit(__doc__)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        raise SystemExit(f"dandi_assets: {exc}") from exc
