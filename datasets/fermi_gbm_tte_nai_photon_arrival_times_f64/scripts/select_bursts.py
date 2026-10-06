#!/usr/bin/env python3
"""Deterministic burst/detector selection for the GBM TTE recipe (discovery only).

Population: every burst directory fermi/data/gbm/bursts/<YYYY>/bn<YYMMDDFFF>/
for YYYY in 2008..2025 (complete years; 2026 is still growing), sorted by
burst name (= chronological trigger order), from the S3 ListObjectsV2
listing written by discover.sh.

Targets: N_BURSTS evenly spaced positions t_k = floor((k + 0.5) * P / N_BURSTS)
over the P bursts. Each target tries population indices t, t+1, t-1, t+2, t-2,
... and takes the first not-yet-chosen burst that qualifies:

  * its current/ prefix lists at least one uncompressed NaI TTE file
    glg_tte_n[0-9ab]_<burst>_vNN.fit (BGO b0/b1, CTIME, CSPEC are ignored);
  * per detector only the highest vNN counts;
  * detector rule: the NaI file with the largest S3 Size (ties -> lowest
    detector index n0 < ... < n9 < na < nb), i.e. the detector that recorded
    the most photons in the TTE window, normally the one facing the burst;
  * the file's S3 ETag is a verifiable MD5 form;
  * a range-GET header probe validates PRIMARY/EVENTS identity and schema
    (gbm_tte.locate_events), NAXIS2 >= ROW_FLOOR, the TSTART/TSTOP window
    relative to TRIGTIME is plausible, and the EVENTS data unit fits inside
    the listed object size.

Bursts that fail are logged with the reason and never padded or merged.
"""
from __future__ import annotations

import argparse
import math
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gbm_tte import (  # noqa: E402
    DETECTORS, FIRST_MAX, FIRST_MIN, LAST_MAX, LAST_MIN, ROW_BYTES, ROW_FLOOR, Truncated, padded,
    probe_bytes,
)

N_BURSTS = 60
YEARS = range(2008, 2026)
BASE = "https://nasa-heasarc.s3.amazonaws.com/"
NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
PROBE_BYTES = 40_320
UA = "openzl-public-datasets-fermi-gbm-tte/1.0"


def curl(args: list[str]) -> None:
    subprocess.run(["curl", "-fsS", "--retry", "5", "--retry-delay", "3", "--max-time", "120", "-A", UA, *args],
                   check=True)


def list_current(year: str, burst: str, cache: Path) -> list[tuple[str, int, str]]:
    prefix = f"fermi/data/gbm/bursts/{year}/{burst}/current/"
    if not cache.is_file():
        curl(["-o", str(cache), "--get", "--data-urlencode", "list-type=2", "--data-urlencode", f"prefix={prefix}",
              "--data-urlencode", "max-keys=1000", BASE])
    root = ET.parse(cache).getroot()
    if root.findtext("s3:IsTruncated", namespaces=NS) != "false":
        raise SystemExit(f"current/ listing for {burst} unexpectedly truncated")
    return [
        (item.findtext("s3:Key", namespaces=NS), int(item.findtext("s3:Size", namespaces=NS)),
         item.findtext("s3:ETag", namespaces=NS).strip('"'))
        for item in root.findall("s3:Contents", NS)
    ]


def pick_detector(burst: str, keys: list[tuple[str, int, str]]) -> tuple[str, int, str, str, int] | None:
    pattern = re.compile(rf".*/current/glg_tte_(n[0-9ab])_{burst}_v(\d\d)\.fit")
    best: dict[str, tuple[int, str, int, str]] = {}
    for key, size, etag in keys:
        match = pattern.fullmatch(key)
        if not match:
            continue
        detector, version = match.group(1), int(match.group(2))
        if detector not in best or version > best[detector][0]:
            best[detector] = (version, key, size, etag)
    if not best:
        return None
    detector = min(best, key=lambda d: (-best[d][2], DETECTORS.index(d[1])))
    version, key, size, etag = best[detector]
    return detector, version, key, size, etag


def probe(key: str, size: int, filename: str, detector: str, heads: Path) -> dict[str, object]:
    length = PROBE_BYTES
    while True:
        cache = heads / f"{filename}.{length}"
        if not (cache.is_file() and cache.stat().st_size == min(length, size)):
            curl(["-r", f"0-{min(length, size) - 1}", "-o", str(cache), BASE + key])
        data = cache.read_bytes()
        if len(data) != min(length, size):
            raise SystemExit(f"range probe for {key} returned {len(data)} bytes")
        try:
            info = probe_bytes(data, filename, detector)
            # bytes consumed up to the EVENTS data start = end of probed headers
            info["events_data_start"] = _events_data_start(data)
            return info
        except Truncated:
            if length >= size or length >= 1 << 20:
                raise
            length *= 4


def _events_data_start(prefix: bytes) -> int:
    position = 0
    while True:
        end = None
        block_start = position
        while end is None:
            block = prefix[position:position + 2880]
            if len(block) != 2880:
                raise Truncated("no EVENTS header in prefix")
            position += 2880
            for offset in range(0, 2880, 80):
                if block[offset:offset + 8] == b"END     ":
                    end = position
                    break
        header = prefix[block_start:end].decode("ascii")
        cards = {header[i:i + 8].strip(): header[i + 10:i + 80] for i in range(0, len(header), 80)
                 if header[i + 8:i + 10] == "= "}
        naxis = int(cards.get("NAXIS", "0").split("/")[0])
        size = 0
        if naxis:
            size = abs(int(cards["BITPIX"].split("/")[0])) // 8
            for axis in range(1, naxis + 1):
                size *= int(cards[f"NAXIS{axis}"].split("/")[0])
        if cards.get("EXTNAME", "").split("/")[0].strip().strip("'").strip() == "EVENTS":
            return position
        position += padded(size)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bursts", type=Path, required=True, help="burst_inventory.tsv from discover.sh")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    lists = args.work_dir / "current_listings"
    heads = args.work_dir / "heads"
    lists.mkdir(parents=True, exist_ok=True)
    heads.mkdir(parents=True, exist_ok=True)
    population = []
    for line in args.bursts.read_text(encoding="utf-8").splitlines()[1:]:
        year, burst = line.split("\t")
        if int(year) in YEARS:
            population.append((burst, year))
    population.sort()
    total = len(population)
    print(f"population={total} years={YEARS.start}..{YEARS.stop - 1} first={population[0][0]} last={population[-1][0]}")
    chosen: dict[int, dict[str, object]] = {}
    skipped: list[str] = []
    for k in range(N_BURSTS):
        target = math.floor((k + 0.5) * total / N_BURSTS)
        for step in range(0, 40):
            offset = (step + 1) // 2 * (1 if step % 2 else -1)
            index = target + offset
            if index < 0 or index >= total or index in chosen:
                continue
            burst, year = population[index]
            keys = list_current(year, burst, lists / f"{burst}.xml")
            picked = pick_detector(burst, keys)
            if picked is None:
                skipped.append(f"{burst}:no_nai_tte_fit")
                continue
            detector, version, key, size, etag = picked
            if not re.fullmatch(r"[0-9a-f]{32}(-\d+)?", etag):
                skipped.append(f"{burst}:unverifiable_etag")
                continue
            filename = Path(key).name
            try:
                info = probe(key, size, filename, detector, heads)
            except (ValueError, Truncated) as error:
                skipped.append(f"{burst}:probe_failed:{error}")
                continue
            rows = int(info["rows"])
            end = int(info["events_data_start"]) + padded(rows * ROW_BYTES)
            if rows < ROW_FLOOR:
                skipped.append(f"{burst}:rows={rows}")
                continue
            if not (FIRST_MIN <= float(info["tstart_rel"]) < FIRST_MAX and LAST_MIN < float(info["tstop_rel"]) <= LAST_MAX):
                skipped.append(f"{burst}:window={info['tstart_rel']:.3f}..{info['tstop_rel']:.3f}")
                continue
            if end > size:
                skipped.append(f"{burst}:events_beyond_object({end}>{size})")
                continue
            chosen[index] = {
                "burst": burst, "year": year, "detector": detector, "version": version, "key": key,
                "bytes": size, "s3_etag": etag, "rows": rows, "tzero1": repr(info["tzero1"]),
                "tstart_rel": f"{info['tstart_rel']:.6f}", "tstop_rel": f"{info['tstop_rel']:.6f}",
                "population_index": index, "target_index": target,
                "nai_files": sum(1 for kk, _, _ in keys if re.search(r"/glg_tte_n[0-9ab]_", kk)),
                "datasum": int(bool(info["has_datasum"])), "checksum": int(bool(info["has_checksum"])),
                "creator": info["creator"],
            }
            print(f"k={k} target={target} pick={index} {burst} {detector} v{version:02d} bytes={size} rows={rows} "
                  f"window={info['tstart_rel']:.1f}..{info['tstop_rel']:.1f} creator={info['creator']!r}")
            break
        else:
            raise SystemExit(f"no eligible burst near target {target}")
    columns = ["burst", "year", "detector", "version", "key", "bytes", "s3_etag", "rows", "tzero1",
               "tstart_rel", "tstop_rel", "population_index", "target_index"]
    with args.out.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(columns) + "\n")
        for index in sorted(chosen):
            handle.write("\t".join(str(chosen[index][c]) for c in columns) + "\n")
    rows = sum(int(c["rows"]) for c in chosen.values())
    print(f"selected={len(chosen)} bytes={sum(int(c['bytes']) for c in chosen.values())} rows={rows} "
          f"output_bytes={rows * 8} skipped={skipped}")
    print("datasum_present=" + str(sum(int(c["datasum"]) for c in chosen.values()))
          + " checksum_present=" + str(sum(int(c["checksum"]) for c in chosen.values()))
          + " multipart_etags=" + str(sum(1 for c in chosen.values() if "-" in str(c["s3_etag"]))))
    print("creators=" + repr(sorted({str(c["creator"]) for c in chosen.values()})))


if __name__ == "__main__":
    main()
