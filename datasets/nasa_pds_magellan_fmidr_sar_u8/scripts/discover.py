#!/usr/bin/env python3
"""Parse curl-fetched S3 listings of the asc-pds-magellan bucket.

discover.sh does all network I/O with curl; this helper only parses the
saved XML/histogram files.  It documents how the six pinned full-resolution
MIDRs were chosen and regenerates the pinned source plan (sources.tsv).

Selection criteria (applied to the 765 F-MIDR directories of MIDR volumes
mg_0001..mg_0127; C1/C2/C3 compressed MIDRs, P-MIDRs, FMAP volumes
mg_11xx-14xx, GxDR mg_3001/3002 and edr/ are never considered):

* the F-MIDR directory name occurs in exactly one volume (no re-released or
  re-mosaicked duplicates of the same tile),
* volume mg_0001 is excluded (its framelets use an older one-record VICAR
  header layout; all later volumes use the 2-record layout parsed here),
* whole-MIDR DN-0 (missing data) fraction below 0.2 % and no DN above 251,
  according to the MIDR's own published HIST.TAB,
* one MIDR per volume, spread across latitude (-35 to +65 deg) and longitude
  (3 to 286 deg E) to cover tessera, rift, volcanic and plains terrain.
"""
from __future__ import annotations

import argparse
import collections
import csv
import re
import struct
import sys
from pathlib import Path

SELECTED = [
    # (volume, midr directory, indicative terrain note)
    ("mg_0006", "f25s003", "25S 3E, Alpha Regio tessera"),
    ("mg_0007", "f65n018", "65N 18E, Ishtar Terra highlands"),
    ("mg_0013", "f35s130", "35S 130E, Artemis region"),
    ("mg_0015", "f05s098", "5S 98E, Aphrodite Terra"),
    ("mg_0025", "f10n188", "10N 188E, Sapas Mons volcano"),
    ("mg_0046", "f20n286", "20N 286E, Beta Regio / Devana Chasma rift"),
]
DESCRIPTION_LABEL = ("mg_0046", "label", "fmidrds.lbl")
MIDR_VOLUME = re.compile(r"mg_0\d{3}")
FMIDR_DIR = re.compile(r"f\d\d[ns]\d{3}")
MAX_ZERO_FRACTION = 0.002
MAX_VALID_DN = 251
MIDR_PIXELS = 56 * 1024 * 1024


def contents(xml_text: str) -> list[tuple[str, str, int]]:
    if "<IsTruncated>false</IsTruncated>" not in xml_text:
        raise SystemExit("S3 listing is truncated or malformed")
    rows = []
    for block in re.findall(r"<Contents>(.*?)</Contents>", xml_text, flags=re.S):
        key = re.search(r"<Key>([^<]+)</Key>", block).group(1)
        etag = re.search(r"<ETag>(?:&quot;|\")([0-9a-f]+)(?:&quot;|\")</ETag>", block)
        size = int(re.search(r"<Size>(\d+)</Size>", block).group(1))
        if etag is None:
            raise SystemExit(f"missing or multipart ETag for {key}")
        rows.append((key, etag.group(1), size))
    return rows


def prefixes(xml_text: str) -> list[str]:
    if "<IsTruncated>false</IsTruncated>" not in xml_text:
        raise SystemExit("S3 listing is truncated or malformed")
    return re.findall(r"<CommonPrefixes><Prefix>([^<]+)</Prefix></CommonPrefixes>", xml_text)


def histogram(path: Path) -> list[int]:
    raw = path.read_bytes()
    if len(raw) != 1024:
        raise SystemExit(f"{path}: HIST.TAB must be 1024 bytes")
    return list(struct.unpack("<256I", raw))


def cmd_volumes(args: argparse.Namespace) -> None:
    for prefix in prefixes(Path(args.root).read_text(encoding="utf-8")):
        volume = prefix.rstrip("/")
        if MIDR_VOLUME.fullmatch(volume):
            print(volume)


def cmd_fmidr_dirs(args: argparse.Namespace) -> None:
    for path in sorted(Path(args.volumes_dir).glob("mg_0*.xml")):
        for prefix in prefixes(path.read_text(encoding="utf-8")):
            parts = prefix.rstrip("/").split("/")
            if len(parts) == 2 and FMIDR_DIR.fullmatch(parts[1]):
                print("/".join(parts))


def cmd_selected(_: argparse.Namespace) -> None:
    for volume, midr, _note in SELECTED:
        print(f"{volume}/{midr}")


def cmd_plan(args: argparse.Namespace) -> None:
    out = Path(args.output_dir)
    dirs = [line.strip() for line in Path(args.fmidr_dirs).read_text().splitlines() if line.strip()]
    name_counts = collections.Counter(d.split("/")[1] for d in dirs)
    print(f"fmidr_directories={len(dirs)} volumes_with_fmidr={len({d.split('/')[0] for d in dirs})}")

    survey_rows = []
    for tab in sorted((out / "hist").glob("*.tab")):
        volume, midr = tab.stem[:7], tab.stem[8:]
        hist = histogram(tab)
        if sum(hist) != MIDR_PIXELS:
            raise SystemExit(f"{tab}: histogram total {sum(hist)} != {MIDR_PIXELS}")
        max_dn = max(i for i, count in enumerate(hist) if count)
        survey_rows.append((volume, midr, hist[0] / MIDR_PIXELS, max_dn, name_counts[midr]))
    with (out / "histogram_survey.tsv").open("w", encoding="utf-8") as handle:
        handle.write("volume\tmidr\tzero_fraction\tmax_dn\tname_occurrences\n")
        for row in survey_rows:
            handle.write(f"{row[0]}\t{row[1]}\t{row[2]:.6f}\t{row[3]}\t{row[4]}\n")
    eligible = [r for r in survey_rows if r[0] != "mg_0001" and r[2] < MAX_ZERO_FRACTION and r[3] <= MAX_VALID_DN and r[4] == 1]
    print(f"histograms_surveyed={len(survey_rows)} eligible_by_criteria={len(eligible)}")

    plan: list[tuple[str, str, str, str, int, str]] = []
    volumes_used = set()
    for volume, midr, note in SELECTED:
        if f"{volume}/{midr}" not in dirs:
            raise SystemExit(f"selected {volume}/{midr} not listed as an F-MIDR directory")
        if name_counts[midr] != 1:
            raise SystemExit(f"selected {midr} occurs in {name_counts[midr]} volumes")
        if volume == "mg_0001" or volume in volumes_used:
            raise SystemExit(f"selected volume {volume} violates the one-per-volume rule")
        volumes_used.add(volume)
        hist = histogram(out / "hist" / f"{volume}_{midr}.tab")
        zero_fraction = hist[0] / MIDR_PIXELS
        max_dn = max(i for i, count in enumerate(hist) if count)
        if zero_fraction >= MAX_ZERO_FRACTION or max_dn > MAX_VALID_DN:
            raise SystemExit(f"selected {volume}/{midr} fails histogram criteria")
        print(f"selected {volume}/{midr} zero_fraction={zero_fraction:.6f} max_dn={max_dn} note={note!r}")
        listing = contents((out / "selected" / f"{volume}_{midr}.xml").read_text(encoding="utf-8"))
        by_name = {key.rsplit("/", 1)[1]: (etag, size) for key, etag, size in listing}
        for number in range(1, 57):
            for suffix, kind in (("img", "framelet_image"), ("lbl", "framelet_label")):
                name = f"ff{number:02d}.{suffix}"
                if name not in by_name:
                    raise SystemExit(f"{volume}/{midr}/{name} missing from listing")
                etag, size = by_name[name]
                plan.append((volume, midr, name, kind, size, etag))
        for name, kind in (("hist.tab", "midr_histogram"), ("hist.lbl", "midr_histogram_label")):
            etag, size = by_name[name]
            plan.append((volume, midr, name, kind, size, etag))
    label_listing = contents((out / "selected" / "mg_0046_label.xml").read_text(encoding="utf-8"))
    label_by_name = {key.rsplit("/", 1)[1]: (etag, size) for key, etag, size in label_listing}
    etag, size = label_by_name[DESCRIPTION_LABEL[2]]
    plan.append((DESCRIPTION_LABEL[0], DESCRIPTION_LABEL[1], DESCRIPTION_LABEL[2], "dataset_description_label", size, etag))

    generated = out / "sources.generated.tsv"
    with generated.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["volume", "directory", "file", "kind", "size_bytes", "md5"])
        writer.writerows(plan)
    total = sum(row[4] for row in plan)
    print(f"plan_rows={len(plan)} plan_bytes={total} generated={generated}")
    pinned = Path(args.pinned)
    if pinned.is_file():
        same = pinned.read_bytes() == generated.read_bytes()
        print(f"pinned_sources_match={int(same)}")
        if not same:
            sys.exit(2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("volumes")
    p.add_argument("--root", required=True)
    p.set_defaults(func=cmd_volumes)
    p = sub.add_parser("fmidr-dirs")
    p.add_argument("--volumes-dir", required=True)
    p.set_defaults(func=cmd_fmidr_dirs)
    p = sub.add_parser("selected")
    p.set_defaults(func=cmd_selected)
    p = sub.add_parser("plan")
    p.add_argument("--output-dir", required=True)
    p.add_argument("--fmidr-dirs", required=True)
    p.add_argument("--pinned", required=True)
    p.set_defaults(func=cmd_plan)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
