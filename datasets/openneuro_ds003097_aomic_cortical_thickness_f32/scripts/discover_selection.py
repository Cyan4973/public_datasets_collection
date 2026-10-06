#!/usr/bin/env python3
"""Metadata-only discovery of the pinned AOMIC-ID1000 cortical-thickness selection.

Uses anonymous S3 ListObjectsV2 requests (through curl) against the public
OpenNeuro bucket. It never downloads thickness payloads. Output is a
selection TSV with one row per object the downloader must fetch:

    kind  subject  key  bytes  md5

kind is one of thickness_lh, thickness_rh, build_stamp.

Selection rule (deterministic):
  1. Enumerate the delimiter prefixes below ds003097/derivatives/freesurfer/
     and keep only participant directories matching sub-NNNN (this drops the
     fsaverage and fsaverage5 template subjects).
  2. Sort the N participant IDs and compute TARGET evenly spaced slot
     positions floor(i * N / TARGET), i = 0..TARGET-1.
  3. For each slot, walk forward (wrapping) from the slot position to the
     first participant not already chosen whose listing contains
     surf/lh.thickness and surf/rh.thickness (single-part MD5 ETag, size of
     the form 15 + 4*n), scripts/recon-all.done, no scripts/recon-all.error,
     and a scripts/build-stamp.txt whose ETag/size equal the pinned FreeSurfer
     v6.0.1 stamp. Skipped participants are reported.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

BUCKET = "https://s3.amazonaws.com/openneuro.org"
ROOT_PREFIX = "ds003097/derivatives/freesurfer/"
SUBJECT_RE = re.compile(r"^sub-\d{4}$")
MD5_RE = re.compile(r"^[0-9a-f]{32}$")
STAMP_MD5 = "774616272edc9c5e46abf1ead8e96ff4"
STAMP_BYTES = 58
USER_AGENT = "openzl-public-datasets-metadata-discovery/1.0"


def curl(url: str) -> bytes:
    result = subprocess.run(
        [
            "curl", "--fail", "--silent", "--show-error", "--location",
            "--retry", "5", "--retry-delay", "2", "--retry-all-errors",
            "--max-time", "120", "--user-agent", USER_AGENT, url,
        ],
        check=True,
        stdout=subprocess.PIPE,
    )
    return result.stdout


def list_objects(prefix: str, delimiter: str | None = None):
    """Yield ('prefix', name) and ('object', key, size, etag) entries."""
    token = None
    while True:
        query = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        if delimiter:
            query["delimiter"] = delimiter
        if token:
            query["continuation-token"] = token
        root = ET.fromstring(curl(f"{BUCKET}?{urllib.parse.urlencode(query)}"))
        ns = root.tag.split("}", 1)[0] + "}" if root.tag.startswith("{") else ""
        for common in root.findall(f"{ns}CommonPrefixes"):
            yield ("prefix", common.findtext(f"{ns}Prefix") or "")
        for content in root.findall(f"{ns}Contents"):
            yield (
                "object",
                content.findtext(f"{ns}Key") or "",
                int(content.findtext(f"{ns}Size") or -1),
                (content.findtext(f"{ns}ETag") or "").strip('"').lower(),
            )
        if (root.findtext(f"{ns}IsTruncated") or "false").lower() != "true":
            return
        token = root.findtext(f"{ns}NextContinuationToken")
        if not token:
            raise SystemExit(f"truncated listing without continuation token: {prefix}")


def subject_eligibility(subject: str) -> tuple[list[tuple[str, str, int, str]] | None, str]:
    base = f"{ROOT_PREFIX}{subject}/"
    objects = {}
    for entry in list_objects(base):
        if entry[0] == "object":
            _, key, size, etag = entry
            objects[key[len(base):]] = (key, size, etag)
    rows = []
    for kind, rel in (("thickness_lh", "surf/lh.thickness"), ("thickness_rh", "surf/rh.thickness")):
        if rel not in objects:
            return None, f"missing {rel}"
        key, size, etag = objects[rel]
        if not MD5_RE.match(etag):
            return None, f"{rel} has non-MD5 ETag {etag}"
        if size <= 15 + 4 * 1000 or (size - 15) % 4:
            return None, f"{rel} has implausible size {size}"
        rows.append((kind, key, size, etag))
    if "scripts/recon-all.done" not in objects:
        return None, "missing scripts/recon-all.done"
    if "scripts/recon-all.error" in objects:
        return None, "has scripts/recon-all.error"
    stamp = objects.get("scripts/build-stamp.txt")
    if stamp is None:
        return None, "missing scripts/build-stamp.txt"
    if stamp[2] != STAMP_MD5 or stamp[1] != STAMP_BYTES:
        return None, f"build stamp differs (etag={stamp[2]} bytes={stamp[1]})"
    rows.append(("build_stamp", stamp[0], stamp[1], stamp[2]))
    return rows, "ok"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=200)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    prefixes = [e[1] for e in list_objects(ROOT_PREFIX, delimiter="/") if e[0] == "prefix"]
    names = [p[len(ROOT_PREFIX):].rstrip("/") for p in prefixes]
    subjects = sorted(n for n in names if SUBJECT_RE.match(n))
    skipped_templates = sorted(n for n in names if not SUBJECT_RE.match(n))
    total = len(subjects)
    if total < args.target:
        raise SystemExit(f"only {total} participant directories, need {args.target}")
    print(f"listed_prefixes={len(names)} participants={total} non_participant={skipped_templates}", flush=True)

    chosen: list[str] = []
    chosen_set: set[str] = set()
    rows: list[tuple[str, str, str, int, str]] = []
    rejected: dict[str, str] = {}
    checked: dict[str, list | None] = {}
    for slot in range(args.target):
        position = slot * total // args.target
        for step in range(total):
            subject = subjects[(position + step) % total]
            if subject in chosen_set or subject in rejected:
                continue
            if subject not in checked:
                result, reason = subject_eligibility(subject)
                checked[subject] = result
                if result is None:
                    rejected[subject] = reason
                    print(f"skip {subject}: {reason}", flush=True)
                    continue
            chosen.append(subject)
            chosen_set.add(subject)
            for kind, key, size, etag in checked[subject]:
                rows.append((kind, subject, key, size, etag))
            break
        else:
            raise SystemExit(f"slot {slot}: no eligible participant left")
        if (slot + 1) % 25 == 0:
            print(f"selected {slot + 1}/{args.target}", flush=True)

    rows.sort(key=lambda r: (r[1], r[0]))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        handle.write("kind\tsubject\tkey\tbytes\tmd5\n")
        for kind, subject, key, size, etag in rows:
            handle.write(f"{kind}\t{subject}\t{key}\t{size}\t{etag}\n")
    thickness = [r for r in rows if r[0].startswith("thickness")]
    summary = {
        "participants_listed": total,
        "non_participant_prefixes": skipped_templates,
        "target_participants": args.target,
        "selected_participants": len(chosen),
        "rejected_participants": rejected,
        "thickness_files": len(thickness),
        "thickness_bytes": sum(r[3] for r in thickness),
        "build_stamp_files": sum(1 for r in rows if r[0] == "build_stamp"),
        "all_bytes": sum(r[3] for r in rows),
        "vertices_min": min((r[3] - 15) // 4 for r in thickness),
        "vertices_max": max((r[3] - 15) // 4 for r in thickness),
        "first_subject": chosen[0] if chosen else None,
        "last_subject": max(chosen) if chosen else None,
    }
    args.summary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
