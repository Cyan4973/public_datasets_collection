#!/usr/bin/env python3
"""discover.sh helper (parses what curl fetched; no network I/O here).

  discover.py next-token <page.xml>              -> continuation token or empty line
  discover.py candidates <listing_dir>           -> TSV of SW *_uncal.fits keys (stdout)
  discover.py selected                           -> selected file names, one per line
  discover.py finalize <discover_dir> <sources>  -> population check + sources.tsv
"""
from __future__ import annotations

import collections
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jwst_uncal as ju  # noqa: E402

BUCKET = "https://stpubdata.s3.amazonaws.com"
PREFIX = "jwst/public/jw02736/jw02736001001/"
KEY_RE = re.compile(r"^jwst/public/jw02736/jw02736001001/(jw02736001001_(\d{5})_(\d{5})_(nrc[ab][1-4])_uncal\.fits)$")

# 12 exposures: six F090W (visit group 02101) and six F200W (02105); every one of the eight
# SW detectors appears at least once (A2, A3, B1, B4 twice, once per filter); dither
# exposures are spread so that no exposure number repeats within a filter except 02101_00001
# (only five F090W exposures are public for six picks).  Twelve 67,108,864-byte cubes =
# 805,306,368 bytes, kept well under the 1 GB primary cap.
SELECTION = [
    "jw02736001001_02101_00001_nrca3_uncal.fits",
    "jw02736001001_02101_00001_nrcb4_uncal.fits",
    "jw02736001001_02101_00002_nrca2_uncal.fits",
    "jw02736001001_02101_00003_nrca1_uncal.fits",
    "jw02736001001_02101_00004_nrcb1_uncal.fits",
    "jw02736001001_02101_00006_nrca4_uncal.fits",
    "jw02736001001_02105_00003_nrca2_uncal.fits",
    "jw02736001001_02105_00004_nrca3_uncal.fits",
    "jw02736001001_02105_00005_nrcb1_uncal.fits",
    "jw02736001001_02105_00006_nrcb2_uncal.fits",
    "jw02736001001_02105_00007_nrcb3_uncal.fits",
    "jw02736001001_02105_00009_nrcb4_uncal.fits",
]
EXPECTED_SIZE = 75556800
# sha256 sits mid-row (filled after the first full download) so an empty value never leaves trailing whitespace.
COLUMNS = ["filename", "url", "key", "version_id", "size_bytes", "crc64nvme", "sha256", "etag", "last_modified",
           "detector", "filter", "act_id", "exposure", "date_obs", "time_obs", "sdp_ver"]


def next_token(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"<NextContinuationToken>(.*?)</NextContinuationToken>", text)
    return html.unescape(match.group(1)) if match else ""


def candidates(listing_dir: Path) -> None:
    print("key\tsize_bytes\tlast_modified\tetag")
    for page in sorted(listing_dir.glob("page_*.xml")):
        text = page.read_text(encoding="utf-8")
        for block in re.findall(r"<Contents>(.*?)</Contents>", text, flags=re.S):
            def field(tag: str) -> str:
                match = re.search(rf"<{tag}>(.*?)</{tag}>", block, flags=re.S)
                return html.unescape(match.group(1)) if match else ""
            key = field("Key")
            if KEY_RE.match(key):
                print(f"{key}\t{field('Size')}\t{field('LastModified')}\t{field('ETag').strip(chr(34))}")


def parse_head(path: Path) -> dict[str, str]:
    blocks = re.split(r"\r?\n\r?\n", path.read_text(encoding="latin-1").strip())
    last = blocks[-1].splitlines()
    if not last or " 200 " not in last[0] + " ":
        raise SystemExit(f"{path.name}: HEAD did not return 200: {last[:1]}")
    headers = {}
    for line in last[1:]:
        if ":" in line:
            name, value = line.split(":", 1)
            headers[name.strip().lower()] = value.strip()
    return headers


def finalize(discover_dir: Path, sources_path: Path) -> None:
    rows = (discover_dir / "candidates.tsv").read_text(encoding="utf-8").splitlines()[1:]
    listing = {}
    for line in rows:
        key, size, last_modified, etag = line.split("\t")
        listing[key.rsplit("/", 1)[1]] = {"key": key, "size": int(size), "last_modified": last_modified, "etag": etag}
    population = collections.Counter()
    regime_ok = 0
    failures = {}
    headers = {}
    for name in sorted(listing):
        buf = (discover_dir / "hdr" / name).read_bytes()
        primary, plen = ju.parse_header(buf, 0)
        sci, _ = ju.parse_header(buf, plen)
        headers[name] = primary
        population[(primary.get("FILTER"), primary.get("READPATT"), primary.get("NGROUPS"), primary.get("NINTS"),
                    primary.get("SUBARRAY"), listing[name]["size"])] += 1
        try:
            ju.check_headers(primary, sci, {"filename": name})
            if listing[name]["size"] != EXPECTED_SIZE:
                raise ju.UncalError(f"size {listing[name]['size']}")
            regime_ok += 1
        except ju.UncalError as exc:
            failures[name] = str(exc)
    print(f"sw_uncal_files={len(listing)} pass_regime={regime_ok}")
    for key, count in sorted(population.items(), key=str):
        print(f"  population filter={key[0]} readpatt={key[1]} ngroups={key[2]} nints={key[3]} subarray={key[4]} size={key[5]} count={count}")
    for name, why in failures.items():
        print(f"  outside_regime {name}: {why}")

    out = []
    for name in SELECTION:
        if name not in listing:
            raise SystemExit(f"selected {name} is not in the public listing")
        if name in failures:
            raise SystemExit(f"selected {name} fails the regime: {failures[name]}")
        head = parse_head(discover_dir / "head" / f"{name}.txt")
        item = listing[name]
        if int(head["content-length"]) != item["size"] or head["etag"].strip('"') != item["etag"]:
            raise SystemExit(f"{name}: HEAD and listing disagree")
        if head.get("x-amz-checksum-type") != "FULL_OBJECT" or not head.get("x-amz-checksum-crc64nvme"):
            raise SystemExit(f"{name}: no full-object CRC64-NVME checksum exposed")
        primary = headers[name]
        version = head["x-amz-version-id"]
        out.append({
            "filename": name,
            "url": f"{BUCKET}/{item['key']}?versionId={version}",
            "key": item["key"],
            "version_id": version,
            "size_bytes": str(item["size"]),
            "crc64nvme": head["x-amz-checksum-crc64nvme"],
            "etag": item["etag"],
            "last_modified": item["last_modified"],
            "detector": primary["DETECTOR"],
            "filter": primary["FILTER"],
            "act_id": primary["ACT_ID"],
            "exposure": primary["EXPOSURE"],
            "date_obs": primary["DATE-OBS"],
            "time_obs": primary["TIME-OBS"],
            "sdp_ver": primary["SDP_VER"],
            "sha256": "",
        })
    previous = {}
    if sources_path.exists():
        previous = {r["filename"]: r for r in ju.read_sources(sources_path)}
    with sources_path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(COLUMNS) + "\n")
        for row in out:
            old = previous.get(row["filename"])
            if old and old.get("crc64nvme") == row["crc64nvme"] and old.get("sha256"):
                row["sha256"] = old["sha256"]  # keep a frozen SHA-256 while the content pin is unchanged
            handle.write("\t".join(row[c] for c in COLUMNS) + "\n")
    summary = {
        "sw_uncal_files": len(listing),
        "pass_regime": regime_ok,
        "selected": len(out),
        "selected_bytes": sum(int(r["size_bytes"]) for r in out),
        "detectors": dict(collections.Counter(r["detector"] for r in out)),
        "filters": dict(collections.Counter(r["filter"] for r in out)),
    }
    (discover_dir / "discover_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary))


def main() -> int:
    mode = sys.argv[1]
    if mode == "next-token":
        print(next_token(Path(sys.argv[2])))
    elif mode == "candidates":
        candidates(Path(sys.argv[2]))
    elif mode == "selected":
        print("\n".join(SELECTION))
    elif mode == "finalize":
        finalize(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        raise SystemExit(f"unknown mode {mode}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
