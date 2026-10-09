#!/usr/bin/env python3
"""Tile selection and payload validation for usgs_3dep_id_northforkpayette_laz_return_number_u8.

Subcommands
  select          print the deterministic tile selection derived from the
                  project VPC (STAC FeatureCollection) and the link list
  make-sources    join the selection with 8 KiB header range-GET probes and
                  write sources.tsv (used by discover.sh only)
  check-selection compare the re-derived selection with the pinned sources.tsv
  check-tile      validate one downloaded LAZ tile and print its sha256
  check-all       run check-tile over every pinned tile
  self-test       exercise the header checks, return-number extraction and
                  the selection rule on synthetic input

Selection rule (also documented in README.md and the manifest):
  1. VPC feature id has the project prefix and its LAZ URL is in the official
     0_file_download_links.txt;
  2. Idaho work area only: proj:bbox minimum easting >= 500,000 m (UTM 11N).
     This drops the 596-tile 11TLL block, a disjoint area near lon -118.5
     (northeastern Oregon) ~200 km west of the North Fork Payette basin;
  3. full 750 m tile footprint: proj:bbox x and y extents >= 749 m (drops
     clipped tiles at the project boundary);
  4. pc:count in [8,000,000, 11,000,000) (lower quartile of the project's
     per-tile counts, to bound pure-Python decode time);
  5. sort the qualifying tiles by tile id and keep the K=20 tiles at evenly
     spaced ranks floor((2i+1)*m/(2K)), i = 0..K-1.
The rule never looks at return numbers.

Only the Python standard library is used. The LAS header, VLRs and EVLRs are
plain LAS structures read with struct; LAZ decoding happens in build/verify.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import struct
import sys
import tempfile
from pathlib import Path

DATASET_ID = "usgs_3dep_id_northforkpayette_laz_return_number_u8"
URL_PREFIX = (
    "https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/"
    "ID_NorthForkPayette_2020_B20/ID_NorthForkPayette_1_2020/LAZ/"
)
NAME_PREFIX = "USGS_LPC_ID_NorthForkPayette_2020_B20_"
MIN_EASTING = 500_000.0
MIN_EXTENT = 749.0
COUNT_LO = 8_000_000  # inclusive
COUNT_HI = 11_000_000  # exclusive
K = 20
EXPECT_TILE_COUNT = 9761

EXPECT_SYSTEM_ID = "MERGE"
EXPECT_SOFTWARE = "LiDAR Suite"
EXPECT_CREATION_YEAR = 2021
EXPECT_POINT_FORMAT_RAW = 0x86  # format 6 with the LASzip compression bit
EXPECT_RECORD_LENGTH = 30
EXPECT_SCALE = (0.01, 0.01, 0.01)
EXPECT_CRS_SUBSTRING = b"UTM zone 11N"
LASZIP_USER_ID = b"laszip encoded"
LASZIP_RECORD_ID = 22204
CONTRACTOR_VLR_USER = b"NIIRS10"

SOURCES_FIELDS = [
    "tile_id", "pc_count", "vpc_datetime", "file_name", "size_bytes", "etag",
    "last_modified", "creation_day", "points_by_return", "sha256", "url",
]


def cstr(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("ascii", "replace").strip()


def load_sources(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not rows or list(rows[0].keys()) != SOURCES_FIELDS:
        raise SystemExit(f"{path}: unexpected sources.tsv columns")
    for row in rows:
        row["pc_count"] = int(row["pc_count"])
        row["size_bytes"] = int(row["size_bytes"])
        row["creation_day"] = int(row["creation_day"])
        row["points_by_return"] = [int(v) for v in row["points_by_return"].split(",")]
        if len(row["points_by_return"]) != 15:
            raise SystemExit(f"{path}: points_by_return of {row['tile_id']} must have 15 entries")
    return rows


def select(vpc_path: Path, links_path: Path) -> tuple[list[dict], int]:
    with vpc_path.open(encoding="utf-8") as handle:
        vpc = json.load(handle)
    if vpc.get("type") != "FeatureCollection" or not vpc.get("features"):
        raise SystemExit("VPC is not a non-empty STAC FeatureCollection")
    links = {line.strip() for line in links_path.read_text(encoding="utf-8").splitlines() if line.strip()}
    if not all(link.startswith(URL_PREFIX) and link.endswith(".laz") for link in links):
        raise SystemExit("link list contains URLs outside the expected rockyweb LAZ directory")
    if len(vpc["features"]) != EXPECT_TILE_COUNT or len(links) != EXPECT_TILE_COUNT:
        raise SystemExit(f"expected {EXPECT_TILE_COUNT} tiles, VPC has {len(vpc['features'])}, link list {len(links)}")
    qualifying = []
    for feature in vpc["features"]:
        props = feature["properties"]
        tile_id = feature["id"]
        if not tile_id.startswith(NAME_PREFIX):
            raise SystemExit(f"unexpected VPC feature id {tile_id}")
        file_name = tile_id + ".laz"
        url = URL_PREFIX + file_name
        if url not in links:
            raise SystemExit(f"VPC tile {file_name} is missing from 0_file_download_links.txt")
        href = feature.get("assets", {}).get("data", {}).get("href")
        if href != "./LAZ/" + file_name:
            raise SystemExit(f"unexpected asset href {href} for {tile_id}")
        x0, y0, _z0, x1, y1, _z1 = props["proj:bbox"]
        count = int(props["pc:count"])
        if x0 < MIN_EASTING:
            continue
        if x1 - x0 < MIN_EXTENT or y1 - y0 < MIN_EXTENT:
            continue
        if not COUNT_LO <= count < COUNT_HI:
            continue
        qualifying.append({
            "tile_id": tile_id[len(NAME_PREFIX):],
            "pc_count": count,
            "vpc_datetime": props["datetime"],
            "file_name": file_name,
            "url": url,
        })
    qualifying.sort(key=lambda row: row["tile_id"])
    m = len(qualifying)
    if m < K:
        raise SystemExit(f"only {m} qualifying tiles")
    return [qualifying[(2 * i + 1) * m // (2 * K)] for i in range(K)], m


def parse_las_header(raw: bytes) -> dict:
    if len(raw) < 375 or raw[:4] != b"LASF":
        raise ValueError("missing LASF signature or short header")
    (global_encoding,) = struct.unpack_from("<H", raw, 6)
    vmaj, vmin = raw[24], raw[25]
    day, year, header_size, offset_points, num_vlrs, fmt_raw, rec_len = struct.unpack_from("<HHHIIBH", raw, 90)
    scale = struct.unpack_from("<3d", raw, 131)
    offset = struct.unpack_from("<3d", raw, 155)
    start_evlr, num_evlrs, count64 = struct.unpack_from("<QIQ", raw, 235)
    return {
        "global_encoding": global_encoding,
        "version": (vmaj, vmin), "system_id": cstr(raw[26:58]), "software": cstr(raw[58:90]),
        "creation": (year, day), "header_size": header_size, "offset_to_points": offset_points,
        "num_vlrs": num_vlrs, "point_format_raw": fmt_raw, "record_length": rec_len,
        "scale": scale, "offset": offset,
        "start_evlr": start_evlr, "num_evlrs": num_evlrs, "point_count": count64,
        "points_by_return": list(struct.unpack_from("<15Q", raw, 255)),
    }


def check_header(raw: bytes, expected_count: int) -> dict:
    hdr = parse_las_header(raw)
    problems = []
    if hdr["version"] != (1, 4):
        problems.append(f"LAS version {hdr['version']}")
    if hdr["system_id"] != EXPECT_SYSTEM_ID:
        problems.append(f"system identifier {hdr['system_id']!r}")
    if hdr["software"] != EXPECT_SOFTWARE:
        problems.append(f"generating software {hdr['software']!r}")
    if hdr["creation"][0] != EXPECT_CREATION_YEAR:
        problems.append(f"creation year {hdr['creation'][0]}")
    if hdr["point_format_raw"] != EXPECT_POINT_FORMAT_RAW:
        problems.append(f"point format byte {hdr['point_format_raw']} (want 134 = compressed PDRF 6)")
    if hdr["record_length"] != EXPECT_RECORD_LENGTH:
        problems.append(f"record length {hdr['record_length']}")
    if not hdr["global_encoding"] & 0x10:
        problems.append(f"global encoding {hdr['global_encoding']} lacks the WKT bit")
    if hdr["scale"] != EXPECT_SCALE:
        problems.append(f"scale {hdr['scale']}")
    if any(value != 0.0 for value in hdr["offset"]):
        problems.append(f"offset {hdr['offset']}")
    if hdr["point_count"] != expected_count:
        problems.append(f"point count {hdr['point_count']} != pinned pc:count {expected_count}")
    pbr = hdr["points_by_return"]
    if sum(pbr) != hdr["point_count"]:
        problems.append(f"points-by-return sum {sum(pbr)} != point count {hdr['point_count']}")
    if pbr[0] <= 0 or pbr[1] <= 0:
        problems.append(f"points-by-return {pbr} lacks first or second returns")
    if hdr["header_size"] != 375 or hdr["num_vlrs"] < 2 or hdr["num_evlrs"] < 1:
        problems.append(f"header size {hdr['header_size']}, VLRs {hdr['num_vlrs']}, EVLRs {hdr['num_evlrs']}")
    if problems:
        raise ValueError("; ".join(problems))
    return hdr


def check_vlrs(prefix: bytes, hdr: dict) -> dict:
    """Parse the VLR block (bytes 0..offset_to_points of the file)."""
    if len(prefix) < hdr["offset_to_points"]:
        raise ValueError("VLR block truncated")
    pos = hdr["header_size"]
    laszip = None
    contractor = False
    for _ in range(hdr["num_vlrs"]):
        user_id = prefix[pos + 2:pos + 18].split(b"\0", 1)[0]
        record_id, length = struct.unpack_from("<HH", prefix, pos + 18)
        data = prefix[pos + 54:pos + 54 + length]
        if user_id == LASZIP_USER_ID and record_id == LASZIP_RECORD_ID:
            laszip = data
        if user_id == CONTRACTOR_VLR_USER:
            contractor = True
        pos += 54 + length
    if pos != hdr["offset_to_points"]:
        raise ValueError(f"VLRs end at {pos}, point data starts at {hdr['offset_to_points']}")
    if laszip is None or len(laszip) < 34:
        raise ValueError("LASzip VLR missing")
    if not contractor:
        raise ValueError("contractor VLR (user id NIIRS10) missing")
    compressor, coder = struct.unpack_from("<HH", laszip, 0)
    chunk_size = struct.unpack_from("<I", laszip, 12)[0]
    num_items = struct.unpack_from("<H", laszip, 32)[0]
    items = [struct.unpack_from("<HHH", laszip, 34 + 6 * i) for i in range(num_items)]
    if (compressor, coder) != (3, 0) or items != [(10, 30, 3)] or chunk_size != 50000:
        raise ValueError(f"LASzip VLR compressor={compressor} coder={coder} chunk={chunk_size} items={items}")
    return {"compressor": compressor, "chunk_size": chunk_size, "items": items}


def check_tail(fh, hdr: dict, file_size: int) -> None:
    if not (hdr["offset_to_points"] < hdr["start_evlr"] < file_size):
        raise ValueError(f"EVLR start {hdr['start_evlr']} outside the file")
    fh.seek(hdr["offset_to_points"])
    (table_offset,) = struct.unpack("<q", fh.read(8))
    if not (hdr["offset_to_points"] < table_offset <= hdr["start_evlr"]):
        raise ValueError(f"chunk table offset {table_offset} implausible")
    fh.seek(hdr["start_evlr"])
    crs_found = False
    for _ in range(hdr["num_evlrs"]):
        head = fh.read(60)
        if len(head) < 60:
            raise ValueError("truncated EVLR")
        user_id = head[2:18].split(b"\0", 1)[0]
        record_id, length = struct.unpack_from("<HQ", head, 18)
        body = fh.read(length)
        if user_id == b"LASF_Projection" and record_id == 2112 and EXPECT_CRS_SUBSTRING in body:
            crs_found = True
    if not crs_found:
        raise ValueError("OGC WKT EVLR with NAD83(2011) / UTM zone 11N not found")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 22), b""):
            digest.update(block)
    return digest.hexdigest()


def check_tile(row: dict, path: Path, recorded_sha: str = "") -> str:
    size = path.stat().st_size
    if size != row["size_bytes"]:
        raise ValueError(f"size {size} != pinned {row['size_bytes']}")
    with path.open("rb") as fh:
        raw = fh.read(375)
        hdr = check_header(raw, row["pc_count"])
        if hdr["creation"][1] != row["creation_day"]:
            raise ValueError(f"creation day {hdr['creation'][1]} != pinned {row['creation_day']}")
        if hdr["points_by_return"] != row["points_by_return"]:
            raise ValueError("header points-by-return differs from the pinned probe values")
        fh.seek(0)
        check_vlrs(fh.read(hdr["offset_to_points"]), hdr)
        check_tail(fh, hdr, size)
    digest = sha256_file(path)
    for expected in (row["sha256"], recorded_sha):
        if expected and digest != expected:
            raise ValueError(f"sha256 {digest} != expected {expected}")
    return digest


def read_recorded(path: Path) -> dict:
    out = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                name, digest = line.split("\t")
                out[name] = digest
    return out


def cmd_select(args) -> int:
    rows, m = select(Path(args.vpc), Path(args.links))
    writer = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    writer.writerow(["tile_id", "pc_count", "vpc_datetime", "file_name", "url"])
    for row in rows:
        writer.writerow([row[k] for k in ("tile_id", "pc_count", "vpc_datetime", "file_name", "url")])
    print(f"qualifying={m} selected={len(rows)} points={sum(r['pc_count'] for r in rows)}", file=sys.stderr)
    return 0


def cmd_make_sources(args) -> int:
    probe_dir = Path(args.probe_dir)
    rows, _m = select(Path(args.vpc), Path(args.links))
    with open(args.out, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(SOURCES_FIELDS)
        total = 0
        for row in rows:
            headers = (probe_dir / (row["tile_id"] + ".headers")).read_text(encoding="latin-1")
            # Keep only the final response block (a proxy CONNECT block may come first).
            block = re.split(r"\r?\n\r?\n(?=HTTP/)", headers.strip())[-1]
            size = int(re.search(r"^content-range: bytes 0-8191/(\d+)", block, re.I | re.M).group(1))
            etag = re.search(r"^etag: (\S+)", block, re.I | re.M).group(1).strip('"')
            modified = re.search(r"^last-modified: ([^\r\n]+)", block, re.I | re.M).group(1).strip()
            raw = (probe_dir / (row["tile_id"] + ".bin")).read_bytes()
            hdr = check_header(raw, row["pc_count"])
            check_vlrs(raw, hdr)
            total += size
            writer.writerow([row["tile_id"], row["pc_count"], row["vpc_datetime"], row["file_name"], size, etag,
                             modified, hdr["creation"][1], ",".join(str(v) for v in hdr["points_by_return"]),
                             "", row["url"]])
    print(f"sources={len(rows)} bytes={total} points={sum(r['pc_count'] for r in rows)}")
    return 0


def cmd_check_selection(args) -> int:
    derived, m = select(Path(args.vpc), Path(args.links))
    pinned = load_sources(Path(args.sources))
    key = lambda r: (r["tile_id"], int(r["pc_count"]), r["file_name"], r["url"])
    if [key(r) for r in derived] != [key(r) for r in pinned]:
        print("FATAL: selection re-derived from the live VPC/link list differs from sources.tsv", file=sys.stderr)
        print("derived:", [r["tile_id"] for r in derived], file=sys.stderr)
        print("pinned: ", [r["tile_id"] for r in pinned], file=sys.stderr)
        return 1
    print(f"selection=ok qualifying={m} tiles={len(pinned)} points={sum(r['pc_count'] for r in pinned)}")
    return 0


def cmd_check_tile(args) -> int:
    rows = {r["file_name"]: r for r in load_sources(Path(args.sources))}
    row = rows[args.name]
    try:
        digest = check_tile(row, Path(args.file))
    except (ValueError, OSError, struct.error) as exc:
        print(f"INVALID {args.name}: {exc}", file=sys.stderr)
        return 1
    print(digest)
    return 0


def cmd_check_all(args) -> int:
    download_dir = Path(args.download_dir)
    recorded = read_recorded(download_dir / "meta" / "sha256.tsv")
    bad = 0
    total = 0
    for row in load_sources(Path(args.sources)):
        path = download_dir / "laz" / row["file_name"]
        if not path.is_file():
            print(f"MISSING {row['file_name']}", file=sys.stderr)
            bad += 1
            continue
        try:
            digest = check_tile(row, path, recorded.get(row["file_name"], ""))
        except (ValueError, OSError, struct.error) as exc:
            print(f"INVALID {row['file_name']}: {exc}", file=sys.stderr)
            bad += 1
            continue
        total += row["size_bytes"]
        print(f"ok {row['file_name']} bytes={row['size_bytes']} points={row['pc_count']} sha256={digest}")
    if bad:
        print(f"FATAL: {bad} tile(s) missing or invalid", file=sys.stderr)
        return 1
    print(f"tiles=ok bytes={total}")
    return 0


# ---------------------------------------------------------------------------
# Return-number extraction shared by build (fast path) and self-test.
# ---------------------------------------------------------------------------

LOW_NIBBLE = bytes(b & 0x0F for b in range(256))
HIGH_NIBBLE = bytes(b >> 4 for b in range(256))
RETURN_BYTE = 14


def return_numbers(records: bytes, n: int, rlen: int = EXPECT_RECORD_LENGTH) -> bytes:
    """Low nibble of byte 14 of each PDRF-6 record (build path: slice + translate)."""
    return records[RETURN_BYTE:n * rlen:rlen].translate(LOW_NIBBLE)


def numbers_of_returns(records: bytes, n: int, rlen: int = EXPECT_RECORD_LENGTH) -> bytes:
    return records[RETURN_BYTE:n * rlen:rlen].translate(HIGH_NIBBLE)


def synthetic_header(count: int, by_return: list, system_id: str = EXPECT_SYSTEM_ID) -> bytes:
    raw = bytearray(375)
    raw[0:4] = b"LASF"
    struct.pack_into("<H", raw, 6, 17)
    raw[24], raw[25] = 1, 4
    raw[26:26 + len(system_id)] = system_id.encode()
    raw[58:58 + len(EXPECT_SOFTWARE)] = EXPECT_SOFTWARE.encode()
    struct.pack_into("<HHHIIBH", raw, 90, 278, 2021, 375, 4763, 4, 0x86, 30)
    struct.pack_into("<3d", raw, 131, 0.01, 0.01, 0.01)
    struct.pack_into("<3d", raw, 155, 0.0, 0.0, -0.0)
    struct.pack_into("<QIQ", raw, 235, 10_000, 1, count)
    struct.pack_into("<15Q", raw, 255, *by_return)
    return bytes(raw)


def cmd_self_test(_args) -> int:
    pbr = [700, 250, 40, 9, 1] + [0] * 10
    hdr = check_header(synthetic_header(1000, pbr), 1000)
    assert hdr["point_count"] == 1000 and hdr["points_by_return"] == pbr
    for bad in (synthetic_header(1000, pbr, "OTHER"), synthetic_header(999, pbr),
                synthetic_header(1000, [1000] + [0] * 14)):
        try:
            check_header(bad, 1000)
        except ValueError:
            pass
        else:
            raise AssertionError("bad header accepted")
    # Return-number extraction on synthetic POINT14 records: byte 14 packs
    # return number (bits 0-3) and number of returns (bits 4-7).
    pairs = [(1, 1), (1, 3), (2, 3), (3, 3), (1, 2), (2, 2), (15, 15), (7, 9), (0, 0)]
    recs = b"".join(struct.pack("<iiiHBBBBhHd", 1, 2, 3, 77, rn | (nr << 4), 0xA5, 2, 0, -3, 9, 1.5)
                    for rn, nr in pairs)
    assert len(recs) == 30 * len(pairs)
    assert list(return_numbers(recs, len(pairs))) == [p[0] for p in pairs]
    assert list(numbers_of_returns(recs, len(pairs))) == [p[1] for p in pairs]
    # independent struct path (as used in verify)
    assert [t[0] & 15 for t in struct.iter_unpack("<14xB15x", recs)] == [p[0] for p in pairs]
    # Selection on a synthetic VPC.
    with tempfile.TemporaryDirectory() as tmp:
        feats, links = [], []
        specs = []
        for i in range(60):
            specs.append((f"11TNK{i:08d}", 9_000_000 + i, (550_000.0, 4_900_000.0, 0, 550_749.99, 4_900_749.99, 1)))
        specs += [("11TLL00000000", 9_000_000, (380_000.0, 5_000_000.0, 0, 380_749.99, 5_000_749.99, 1)),
                  ("11TNK99999998", 7_999_999, (550_000.0, 4_900_000.0, 0, 550_749.99, 4_900_749.99, 1)),
                  ("11TNK99999999", 9_000_000, (550_000.0, 4_900_000.0, 0, 550_500.0, 4_900_749.99, 1))]
        for tid, count, bbox in specs:
            name = NAME_PREFIX + tid
            feats.append({"id": name, "properties": {"datetime": "2021-10-05T00:00:00Z", "pc:count": count,
                                                     "proj:bbox": list(bbox)},
                          "assets": {"data": {"href": f"./LAZ/{name}.laz"}}})
            links.append(URL_PREFIX + name + ".laz")
        vpc = Path(tmp) / "v.json"
        lst = Path(tmp) / "l.txt"
        vpc.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
        lst.write_text("\n".join(links) + "\n")
        global EXPECT_TILE_COUNT
        saved = EXPECT_TILE_COUNT
        EXPECT_TILE_COUNT = len(specs)
        try:
            rows, m = select(vpc, lst)
        finally:
            EXPECT_TILE_COUNT = saved
        assert m == 60, m
        assert [r["tile_id"] for r in rows] == [f"11TNK{(2 * i + 1) * 60 // 40:08d}" for i in range(K)]
    print("self-test=ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("select")
    p.add_argument("--vpc", required=True)
    p.add_argument("--links", required=True)
    p.set_defaults(func=cmd_select)
    p = sub.add_parser("make-sources")
    p.add_argument("--vpc", required=True)
    p.add_argument("--links", required=True)
    p.add_argument("--probe-dir", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_make_sources)
    p = sub.add_parser("check-selection")
    p.add_argument("--vpc", required=True)
    p.add_argument("--links", required=True)
    p.add_argument("--sources", required=True)
    p.set_defaults(func=cmd_check_selection)
    p = sub.add_parser("check-tile")
    p.add_argument("--sources", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_check_tile)
    p = sub.add_parser("check-all")
    p.add_argument("--sources", required=True)
    p.add_argument("--download-dir", required=True)
    p.set_defaults(func=cmd_check_all)
    p = sub.add_parser("self-test")
    p.set_defaults(func=cmd_self_test)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
