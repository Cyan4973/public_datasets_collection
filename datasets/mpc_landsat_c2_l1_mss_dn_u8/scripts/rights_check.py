#!/usr/bin/env python3
"""Offline checks of the captured rights evidence (no network I/O).

download.sh fetches the documents with curl and runs these checks before any
raster is downloaded; verify.sh re-runs them on the saved files.

Subcommands (exit 0 = pass, 1 = fail):
  mpc <mpc_collection_landsat-c2-l1.json>
      Required. The Planetary Computer collection JSON: id landsat-c2-l1; a
      link rel=license titled 'Public Domain' whose href is a usgs.gov
      data-policy page; providers NASA and USGS both carrying the 'licensor'
      role; cite-as DOI 10.5066/P9AF14YV; item_assets green/red/nir08/nir09
      raster:bands uint8 with nodata 0 (the emitted bands) and qa_pixel /
      qa_radsat uint16 (the excluded QA bands); summaries listing landsat-5
      and instrument mss.
  usgs <usgs_data_policy.html>
      Grant, option A: the USGS data policy page that MPC links as its
      license. Visible text (scripts/styles/tags stripped, unescaped,
      whitespace collapsed, lowercased) must match the regex
      r'public domain\\s*\\(\\s*such as landsat or aster\\s*\\)' AND contain
      'redistributed without restriction'.
  aws <usgs_landsat_open_data_registry.(html|yaml)>
      Grant, option B: the USGS-managed AWS Open Data Registry entry 'USGS
      Landsat' (HTML page or its YAML source). Normalized text must contain
      'there are no restrictions on landsat data downloaded from the usgs;
      it can be used or redistributed as desired' AND name the 'united
      states geological survey' (the ManagedBy field).

download.sh requires 'mpc' plus at least one of 'usgs' / 'aws' to pass.
"""
from __future__ import annotations

import html
import json
import re
import sys

USGS_GRANT_RE = re.compile(r"public domain\s*\(\s*such as landsat or aster\s*\)")
USGS_PHRASE = "redistributed without restriction"
AWS_PHRASE = ("there are no restrictions on landsat data downloaded from the usgs; "
              "it can be used or redistributed as desired")
AWS_MANAGER = "united states geological survey"
SENTENCE_END = re.compile(r"(?<!\b[A-Za-z])[.!?](?=\s|$)")  # skips abbreviations such as "U.S."


def normalized_text(raw: bytes) -> str:
    """Visible text: no script/style, no tags, unescaped, single spaces (case kept)."""
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1\s*>", " ", text)
    text = re.sub(r"(?s)<!--.*?-->", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def sentence_around(text: str, start: int, end: int) -> str:
    left, right = 0, len(text)
    for m in SENTENCE_END.finditer(text):
        if m.end() <= start:
            left = m.end()
        elif m.start() >= end - 1:
            right = m.end()
            break
    return text[left:right].strip()


def _context_dump(view: str, lower: str, needle: str) -> None:
    hits = [m.start() for m in re.finditer(re.escape(needle), lower)]
    if not hits:
        print(f"no {needle!r} in text; first 1500 chars: {view[:1500]}", file=sys.stderr)
    for p in hits[:5]:
        print(f"context: ...{view[max(0, p - 600):p + 600]}...", file=sys.stderr)


def check_usgs(path: str) -> int:
    raw = open(path, "rb").read()
    text = normalized_text(raw)
    lower = text.lower()
    view = text if len(lower) == len(text) else lower
    grant = list(USGS_GRANT_RE.finditer(lower))
    phrase = [m.start() for m in re.finditer(re.escape(USGS_PHRASE), lower)]
    for m in grant:
        print(f"usgs_grant_sentence: {sentence_around(view, m.start(), m.end())}")
    for p in phrase:
        print(f"usgs_redistribution_sentence: {sentence_around(view, p, p + len(USGS_PHRASE))}")
    if grant and phrase:
        print(f"usgs_check=ok file={path} bytes={len(raw)} grant_matches={len(grant)} phrase_matches={len(phrase)}")
        return 0
    print(f"usgs_check=FAIL file={path} grant_matches={len(grant)} phrase_matches={len(phrase)}", file=sys.stderr)
    _context_dump(view, lower, "public domain")
    return 1


def check_aws(path: str) -> int:
    raw = open(path, "rb").read()
    text = normalized_text(raw)
    # Markdown links in the YAML source ("[statement of the data source](url)")
    # do not affect the checked phrase, which precedes them.
    lower = text.lower()
    view = text if len(lower) == len(text) else lower
    at = lower.find(AWS_PHRASE)
    manager = AWS_MANAGER in lower
    if at >= 0:
        print(f"aws_license_sentence: {sentence_around(view, at, at + len(AWS_PHRASE))}")
        tail = view[at + len(AWS_PHRASE):at + len(AWS_PHRASE) + 260]
        print(f"aws_license_continuation: {tail}")
    if at >= 0 and manager:
        print(f"aws_check=ok file={path} bytes={len(raw)} managed_by_usgs={manager}")
        return 0
    print(f"aws_check=FAIL file={path} phrase_found={at >= 0} managed_by_usgs={manager}", file=sys.stderr)
    _context_dump(view, lower, "restriction")
    return 1


def check_mpc(path: str) -> int:
    doc = json.load(open(path, encoding="utf-8"))
    problems = []
    if doc.get("id") != "landsat-c2-l1":
        problems.append(f"collection id {doc.get('id')!r}")
    links = doc.get("links", [])
    lic = [l for l in links if l.get("rel") == "license"]
    good = [l for l in lic if l.get("title") == "Public Domain"
            and "usgs.gov" in str(l.get("href", "")) and "data-policy" in str(l.get("href", ""))]
    if not good:
        problems.append(f"no rel=license 'Public Domain' usgs.gov data-policy link (license links: {lic})")
    cite = [l for l in links if l.get("rel") == "cite-as" and "10.5066/P9AF14YV" in str(l.get("href", ""))]
    if not cite:
        problems.append("no cite-as link to DOI 10.5066/P9AF14YV")
    providers = doc.get("providers", [])

    def licensor(tag: str) -> list:
        return [p for p in providers if tag in str(p.get("name", "")).upper() and "licensor" in (p.get("roles") or [])]

    nasa, usgs = licensor("NASA"), licensor("USGS")
    if not nasa or not usgs:
        problems.append(f"providers lack NASA and USGS licensors: {[(p.get('name'), p.get('roles')) for p in providers]}")
    assets = doc.get("item_assets", {})
    for key in ("green", "red", "nir08", "nir09"):
        bands = (assets.get(key) or {}).get("raster:bands")
        if not isinstance(bands, list) or len(bands) != 1 or bands[0].get("data_type") != "uint8" \
                or bands[0].get("nodata") != 0:
            problems.append(f"item_assets.{key} raster:bands not 1 x uint8 nodata 0: {bands}")
    for key in ("qa_pixel", "qa_radsat"):
        bands = (assets.get(key) or {}).get("raster:bands")
        if not isinstance(bands, list) or not bands or bands[0].get("data_type") != "uint16":
            problems.append(f"item_assets.{key} is not uint16: {bands}")
    summaries = doc.get("summaries", {})
    if "landsat-5" not in (summaries.get("platform") or []) or (summaries.get("instruments") or []) != ["mss"]:
        problems.append(f"summaries platform/instruments unexpected: {summaries.get('platform')} {summaries.get('instruments')}")
    if problems:
        for p in problems:
            print(f"mpc_check=FAIL {p}", file=sys.stderr)
        return 1
    print(f"mpc_license={doc.get('license')!r} license_link={good[0]['href']} title={good[0]['title']!r}")
    print(f"mpc_licensors NASA={[p['name'] for p in nasa]} USGS={[p['name'] for p in usgs]}")
    print(f"mpc_cite_as={cite[0]['href']}")
    print("mpc_bands green/red/nir08/nir09=uint8 nodata 0; qa_pixel/qa_radsat=uint16 (excluded)")
    print(f"mpc_check=ok file={path}")
    return 0


def main(argv: list[str]) -> int:
    checks = {"usgs": check_usgs, "aws": check_aws, "mpc": check_mpc}
    if len(argv) != 3 or argv[1] not in checks:
        print(__doc__, file=sys.stderr)
        return 2
    return checks[argv[1]](argv[2])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
