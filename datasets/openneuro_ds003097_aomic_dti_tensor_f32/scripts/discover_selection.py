#!/usr/bin/env python3
"""Metadata-only discovery for the AOMIC-ID1000 DTI tensor selection.

Lists the public OpenNeuro S3 prefix ds003097/derivatives/dwipreproc/ with
anonymous ListObjectsV2 requests (via curl, so the user's proxy settings are
honoured), keeps participants that publish both the WLS diffusion-tensor
volume (model-DTI_desc-WLS_diffmodel) and the companion FA map, picks
TARGET participants at evenly spaced ranks of the sorted participant list,
and confirms each picked tensor header with a small gzip range read. If a
picked participant's header deviates from the expected geometry, the next
eligible participant in sorted order is substituted (and logged).

Output: selection.tsv (kind, subject, key, bytes, md5) and summary.json.
No tensor payloads are downloaded beyond a 4 KiB header range per pick.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import subprocess
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

BUCKET = "https://s3.amazonaws.com/openneuro.org"
PREFIX = "ds003097/derivatives/dwipreproc/"
USER_AGENT = "openzl-public-datasets-metadata-discovery/1.0 (aomic-dti-tensor)"
KEY_RE = re.compile(
    r"^ds003097/derivatives/dwipreproc/(sub-\d{4})/dwi/\1_model-DTI_desc-WLS_(diffmodel|FA)\.nii\.gz$"
)
EXPECTED_DIM = {"diffmodel": (4, 112, 112, 60, 6), "FA": (3, 112, 112, 60)}


def curl(url: str, byte_range: str | None = None) -> bytes:
    cmd = [
        "curl", "--fail", "--silent", "--show-error", "--location",
        "--retry", "5", "--retry-delay", "2", "--max-time", "120",
        "--user-agent", USER_AGENT,
    ]
    if byte_range:
        cmd += ["--range", byte_range]
    cmd.append(url)
    return subprocess.run(cmd, check=True, stdout=subprocess.PIPE).stdout


def list_objects() -> list[dict]:
    objects: list[dict] = []
    token = None
    pages = 0
    while True:
        query = {"list-type": "2", "prefix": PREFIX, "max-keys": "1000"}
        if token:
            query["continuation-token"] = token
        root = ET.fromstring(curl(f"{BUCKET}?{urllib.parse.urlencode(query)}"))
        pages += 1
        ns = root.tag.split("}", 1)[0] + "}" if root.tag.startswith("{") else ""
        for item in root.findall(f"{ns}Contents"):
            objects.append(
                {
                    "key": item.findtext(f"{ns}Key") or "",
                    "size": int(item.findtext(f"{ns}Size") or 0),
                    "etag": (item.findtext(f"{ns}ETag") or "").strip('"'),
                    "last_modified": item.findtext(f"{ns}LastModified") or "",
                }
            )
        if (root.findtext(f"{ns}IsTruncated") or "false").lower() != "true":
            break
        token = root.findtext(f"{ns}NextContinuationToken")
        if not token:
            raise SystemExit("truncated S3 listing without continuation token")
    print(f"listed objects={len(objects)} pages={pages}")
    return objects


def header_ok(key: str, kind: str) -> tuple[bool, str]:
    raw = curl(f"{BUCKET}/{key}", "0-4095")
    head = zlib.decompressobj(31).decompress(raw)
    if len(head) < 352:
        return False, "short header"
    sizeof_hdr = struct.unpack_from("<i", head, 0)[0]
    dims = struct.unpack_from("<8h", head, 40)
    datatype, bitpix = struct.unpack_from("<2h", head, 70)
    vox_offset = struct.unpack_from("<f", head, 108)[0]
    slope, inter = struct.unpack_from("<2f", head, 112)
    magic = head[344:348]
    want = EXPECTED_DIM[kind]
    got = tuple(dims[: len(want)])
    if (
        sizeof_hdr != 348 or magic != b"n+1\0" or got != want
        or datatype != 16 or bitpix != 32 or vox_offset != 352.0
        or slope not in (0.0, 1.0) or inter != 0.0
    ):
        return False, f"sizeof={sizeof_hdr} magic={magic!r} dim={dims} dt={datatype} bp={bitpix} off={vox_offset} scl={slope}/{inter}"
    return True, f"dim={got}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=32)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    objects = list_objects()
    subject_dirs = {o["key"][len(PREFIX):].split("/", 1)[0] for o in objects if o["key"][len(PREFIX):].startswith("sub-")}
    found: dict[str, dict[str, dict]] = {}
    for obj in objects:
        match = KEY_RE.match(obj["key"])
        if match:
            found.setdefault(match.group(1), {})[match.group(2)] = obj
    eligible = sorted(s for s, kinds in found.items() if {"diffmodel", "FA"} <= kinds.keys())
    for subject in eligible:
        for kind in ("diffmodel", "FA"):
            obj = found[subject][kind]
            if obj["size"] <= 0 or "-" in obj["etag"] or not re.fullmatch(r"[0-9a-f]{32}", obj["etag"]):
                raise SystemExit(f"{obj['key']}: unusable size/etag {obj['size']} {obj['etag']}")
    n = len(eligible)
    print(f"participant_dirs={len(subject_dirs)} with_diffmodel_and_fa={n}")
    if n < args.target:
        raise SystemExit(f"only {n} eligible participants")

    # Evenly spaced ranks: floor((i + 0.5) * n / target), i = 0..target-1.
    picks: list[str] = []
    skipped: list[dict] = []
    used: set[int] = set()
    for i in range(args.target):
        rank = (2 * i + 1) * n // (2 * args.target)
        while rank in used:
            rank += 1
        while True:
            if rank >= n:
                raise SystemExit("ran out of eligible participants while substituting")
            subject = eligible[rank]
            ok, detail = header_ok(found[subject]["diffmodel"]["key"], "diffmodel")
            if ok:
                ok, detail = header_ok(found[subject]["FA"]["key"], "FA")
            if ok:
                break
            print(f"skip {subject}: {detail}")
            skipped.append({"subject": subject, "detail": detail})
            used.add(rank)
            rank += 1
        used.add(rank)
        picks.append(subject)
        print(f"pick {i:02d} rank={rank} {subject} {detail}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    total = {"diffmodel": 0, "FA": 0}
    with args.out.open("w", encoding="utf-8") as handle:
        handle.write("kind\tsubject\tkey\tbytes\tmd5\n")
        for subject in picks:
            for kind in ("diffmodel", "FA"):
                obj = found[subject][kind]
                total[kind] += obj["size"]
                handle.write(f"{kind}\t{subject}\t{obj['key']}\t{obj['size']}\t{obj['etag']}\n")
    summary = {
        "prefix": PREFIX,
        "listed_objects": len(objects),
        "participant_dirs": len(subject_dirs),
        "eligible_participants": n,
        "target": args.target,
        "selected": picks,
        "skipped": skipped,
        "diffmodel_bytes": total["diffmodel"],
        "fa_bytes": total["FA"],
        "total_bytes": total["diffmodel"] + total["FA"],
        "last_modified_range": [
            min(found[s][k]["last_modified"] for s in picks for k in ("diffmodel", "FA")),
            max(found[s][k]["last_modified"] for s in picks for k in ("diffmodel", "FA")),
        ],
    }
    args.summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "selected"}, indent=2))


if __name__ == "__main__":
    main()
