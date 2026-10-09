#!/usr/bin/env python3
"""Select and pin the weekly LAT photon files (run by discover.sh, not by download.sh).

Modes:
  targets LISTING_HTML N              print the N selected file names
  pin LISTING_HTML N PROBE_DIR OUT    write sources.tsv from HEAD + range probes

Population: every lat_photon_weekly_wNNN_p305_v001.fits in the HEASARC
directory listing with 10 <= NNN <= 950. w009 is the partial first week
(mission data start on 2008-08-04), and weeks after w950 were excluded
because the newest files are still being rewritten. N targets are taken at
population indices floor((k + 0.5) * len / N) for k = 0..N-1.

The probes per selected file: an HTTP HEAD (Content-Length, Last-Modified), a
28,800-byte prefix range GET (primary + EVENTS header: identity, full schema,
NAXIS2, DATASUM, TSTART/TSTOP) and a 28,800-byte suffix range GET (GTI
header). The pinned size must equal the FITS layout exactly:
primary header + EVENTS header + padded(98 * NAXIS2) + GTI header +
padded(16 * GTI NAXIS2).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lat_events import FITS_BLOCK, ROW_BYTES, ROW_FLOOR, padded, parse_value, probe_prefix, text  # noqa: E402

NAME_RE = re.compile(r'href="(lat_photon_weekly_w(\d{3})_p305_v001\.fits)"')
WEEK_MIN, WEEK_MAX = 10, 950


def population(listing: Path) -> list[tuple[int, str]]:
    found = {}
    for name, week in NAME_RE.findall(listing.read_text(encoding="utf-8", errors="replace")):
        found[int(week)] = name
    return sorted((week, name) for week, name in found.items() if WEEK_MIN <= week <= WEEK_MAX)


def targets(listing: Path, count: int) -> list[tuple[int, int, str]]:
    pop = population(listing)
    picks = []
    for k in range(count):
        index = int((k + 0.5) * len(pop) / count)
        picks.append((index, *pop[index]))
    return picks


def parse_head(path: Path) -> tuple[int, str]:
    length = modified = None
    for line in path.read_text(encoding="latin-1").splitlines():
        key, _, value = line.partition(":")
        if key.strip().lower() == "content-length":
            length = int(value.strip())
        elif key.strip().lower() == "last-modified":
            modified = value.strip()
    if length is None or modified is None:
        raise SystemExit(f"{path}: missing Content-Length/Last-Modified")
    return length, modified


def gti_from_tail(tail: bytes, filename: str) -> tuple[int, int]:
    """Return (GTI header length, GTI NAXIS2) from the file's last bytes."""
    if len(tail) % FITS_BLOCK:
        raise SystemExit(f"{filename}: tail probe not block aligned")
    for start in range(0, len(tail), FITS_BLOCK):
        if tail[start:start + 20] == b"XTENSION= 'BINTABLE'":
            values = {}
            position = start
            while True:
                card = tail[position:position + 80].decode("ascii")
                position += 80
                if card[:8] == "END     ":
                    break
                if card[8:10] == "= ":
                    values[card[:8].strip()] = parse_value(card)
            if text(values, "EXTNAME") != "GTI" or int(values["NAXIS1"]) != 16:
                continue
            header_len = padded(position - start)
            rows = int(values["NAXIS2"])
            if start + header_len + padded(16 * rows) != len(tail):
                raise SystemExit(f"{filename}: GTI does not end the file")
            return header_len, rows
    raise SystemExit(f"{filename}: GTI header not found in tail probe")


def pin(listing: Path, count: int, probe_dir: Path, out: Path) -> None:
    columns = ["week", "filename", "bytes", "last_modified", "rows", "events_datasum", "tstart", "tstop",
               "date_obs", "date_end", "gti_rows", "population_index", "target_index"]
    lines = ["\t".join(columns)]
    total_bytes = total_rows = 0
    pop_size = len(population(listing))
    for k, (index, week, name) in enumerate(targets(listing, count)):
        size, modified = parse_head(probe_dir / f"{name}.head")
        info = probe_prefix((probe_dir / f"{name}.prefix").read_bytes(), name)
        gti_header, gti_rows = gti_from_tail((probe_dir / f"{name}.tail").read_bytes(), name)
        rows = int(info["rows"])
        layout = int(info["events_header_end"]) + padded(ROW_BYTES * rows) + gti_header + padded(16 * gti_rows)
        if layout != size:
            raise SystemExit(f"{name}: FITS layout {layout} != Content-Length {size}")
        if rows < ROW_FLOOR:
            raise SystemExit(f"{name}: {rows} rows below floor")
        if not info["events_datasum"].isdigit() or not info["has_checksum"]:
            raise SystemExit(f"{name}: EVENTS lacks CHECKSUM/DATASUM")
        lines.append("\t".join(str(v) for v in [
            week, name, size, modified, rows, info["events_datasum"], repr(info["tstart"]), repr(info["tstop"]),
            info["date_obs"], info["date_end"], gti_rows, index, int((k + 0.5) * pop_size / count)]))
        total_bytes += size
        total_rows += rows
        print(f"w{week:03d} bytes={size} rows={rows} gti={gti_rows} {info['date_obs']}..{info['date_end']}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"population={pop_size} files={count} bytes={total_bytes} rows={total_rows} "
          f"primary_bytes(5 fields)={total_rows * 20}")


def main() -> None:
    mode = sys.argv[1]
    if mode == "targets":
        for _index, _week, name in targets(Path(sys.argv[2]), int(sys.argv[3])):
            print(name)
    elif mode == "pin":
        pin(Path(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4]), Path(sys.argv[5]))
    else:
        raise SystemExit(f"unknown mode {mode}")


if __name__ == "__main__":
    main()
