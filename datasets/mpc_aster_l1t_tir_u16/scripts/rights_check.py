#!/usr/bin/env python3
"""Offline checks of the captured rights evidence (no network I/O).

download.sh fetches the pages with curl and runs these checks before any
raster is downloaded; verify.sh re-runs them on the saved files.

Subcommands:
  usgs <usgs_data_policy.html>
      The grant. Drop <script>/<style> blocks, strip tags, html.unescape,
      collapse whitespace, lowercase; require the regex
      r'public domain\\s*\\(\\s*such as landsat or aster\\s*\\)' AND the phrase
      'redistributed without restriction'. Prints the matched sentences. On
      failure prints ~1500 characters of context around every 'public
      domain' occurrence and exits 1.
  mpc <mpc_collection_aster-l1t.json>
      Require a link rel=license, title 'Public Domain', href containing
      'usgs.gov' and 'data-policy'; providers named NASA and USGS that both
      carry the 'licensor' role; item_assets.TIR raster:bands with exactly 5
      entries, each data_type 'uint16' and nodata 0.
  earthdata <earthdata_aster_no_charge.html>
      Informational only: prints whether the page mentions 'aster' and
      'no charge'; always exits 0.
"""
from __future__ import annotations

import html
import json
import re
import sys

GRANT_RE = re.compile(r"public domain\s*\(\s*such as landsat or aster\s*\)")
GRANT_PHRASE = "redistributed without restriction"


def normalized_text(raw: bytes) -> str:
    """Case-preserving visible text: no script/style, no tags, unescaped, single spaces."""
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1\s*>", " ", text)
    text = re.sub(r"(?s)<!--.*?-->", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


SENTENCE_END = re.compile(r"(?<!\b[A-Za-z])[.!?](?=\s|$)")  # skips abbreviations such as "U.S."


def sentence_around(text: str, start: int, end: int) -> str:
    left, right = 0, len(text)
    for m in SENTENCE_END.finditer(text):
        if m.end() <= start:
            left = m.end()
        elif m.start() >= end - 1:
            right = m.end()
            break
    return text[left:right].strip()


def check_usgs(path: str) -> int:
    raw = open(path, "rb").read()
    text = normalized_text(raw)
    lower = text.lower()
    same_len = len(lower) == len(text)
    view = text if same_len else lower
    grant = list(GRANT_RE.finditer(lower))
    phrase_at = [m.start() for m in re.finditer(re.escape(GRANT_PHRASE), lower)]
    for m in grant:
        print(f"usgs_grant_sentence: {sentence_around(view, m.start(), m.end())}")
    for p in phrase_at:
        print(f"usgs_redistribution_sentence: {sentence_around(view, p, p + len(GRANT_PHRASE))}")
    if grant and phrase_at:
        print(f"usgs_check=ok file={path} bytes={len(raw)} grant_matches={len(grant)} phrase_matches={len(phrase_at)}")
        return 0
    print(f"usgs_check=FAIL file={path} grant_matches={len(grant)} phrase_matches={len(phrase_at)}", file=sys.stderr)
    occurrences = [m.start() for m in re.finditer("public domain", lower)]
    if not occurrences:
        print(f"no 'public domain' in page text; first 1500 chars: {view[:1500]}", file=sys.stderr)
    for p in occurrences:
        print(f"context: ...{view[max(0, p - 750):p + 750]}...", file=sys.stderr)
    return 1


def check_mpc(path: str) -> int:
    doc = json.load(open(path, encoding="utf-8"))
    problems = []
    if doc.get("id") != "aster-l1t":
        problems.append(f"collection id {doc.get('id')!r}")
    links = [l for l in doc.get("links", []) if l.get("rel") == "license"]
    good_links = [l for l in links if l.get("title") == "Public Domain"
                  and "usgs.gov" in str(l.get("href", "")) and "data-policy" in str(l.get("href", ""))]
    if not good_links:
        problems.append(f"no rel=license 'Public Domain' usgs.gov data-policy link (license links: {links})")
    providers = doc.get("providers", [])

    def licensor(tag: str) -> list:
        return [p for p in providers if tag in str(p.get("name", "")).upper() and "licensor" in (p.get("roles") or [])]

    nasa, usgs = licensor("NASA"), licensor("USGS")
    if not nasa or not usgs:
        problems.append(f"providers lack NASA and USGS licensors: {[(p.get('name'), p.get('roles')) for p in providers]}")
    bands = (doc.get("item_assets", {}).get("TIR", {}) or {}).get("raster:bands")
    if not isinstance(bands, list) or len(bands) != 5 or any(
            b.get("data_type") != "uint16" or b.get("nodata") != 0 for b in bands):
        problems.append(f"item_assets.TIR raster:bands not 5 x uint16 nodata 0: {bands}")
    if problems:
        for p in problems:
            print(f"mpc_check=FAIL {p}", file=sys.stderr)
        return 1
    print(f"mpc_license={doc.get('license')!r} license_link={good_links[0]['href']} title={good_links[0]['title']!r}")
    print(f"mpc_licensors NASA={[p['name'] for p in nasa]} USGS={[p['name'] for p in usgs]}")
    print("mpc_tir_bands=5 x uint16 nodata=0")
    print(f"mpc_check=ok file={path}")
    return 0


def check_earthdata(path: str) -> int:
    lower = normalized_text(open(path, "rb").read()).lower()
    has_aster, has_no_charge = "aster" in lower, "no charge" in lower
    status = "ok" if has_aster and has_no_charge else "phrases_missing"
    print(f"earthdata_check={status} aster={has_aster} no_charge={has_no_charge}")
    anchor = re.search(r"began distributing[^.]*no charge", lower) or re.search("no charge", lower)
    if anchor:
        print(f"earthdata_sentence: {sentence_around(lower, anchor.start(), anchor.end())}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("usgs", "mpc", "earthdata"):
        print(__doc__, file=sys.stderr)
        return 2
    return {"usgs": check_usgs, "mpc": check_mpc, "earthdata": check_earthdata}[argv[1]](argv[2])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
