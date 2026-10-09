#!/usr/bin/env python3
"""Tile selection and payload validation for usgs_3dep_nc_geiger_laz_x_i32.

Subcommands
  select          print the deterministic tile selection derived from the
                  project VPC (STAC FeatureCollection) and the link list
  check-selection compare that selection with the pinned sources.tsv
  check-tile      validate one downloaded LAZ tile (size, sha256 when pinned,
                  LAS header, LASzip VLR, CRS EVLR) and print its sha256
  check-all       run check-tile over every pinned tile (used by build.sh)
  self-test       exercise the header checks and the X extraction on
                  synthetic bytes

Selection rule (also documented in README.md): every VPC feature whose
properties.datetime is 2016-08-10 (a copy of the LAS header file-creation
date 2016/223, not a flight date; every selected tile must also carry the
LAS system identifier 'IntelliEarthGmAPDSensorS/N003', which other creation
dates use too, mixed with other identifiers) and whose pc:count is
below 9,000,000, sorted by tile id. This deliberately favours partial tiles
(project edges, water bodies) because full interior tiles hold 17-31 million
points each.

Only the Python standard library is used. LAZ decoding is not needed here;
the header, VLRs and EVLRs are plain LAS structures read with struct.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import struct
import sys
import tempfile
from pathlib import Path

DATASET_ID = "usgs_3dep_nc_geiger_laz_x_i32"
URL_PREFIX = (
    "https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/"
    "NC_Phase_4_CentralWestNC_GEIGER_A16/NC_Phase4_Anson_2016/LAZ/"
)
NAME_PREFIX = "USGS_LPC_NC_Phase_4_CentralWestNC_GEIGER_A16_"
SELECT_DATETIME = "2016-08-10"
SELECT_MAX_COUNT = 9_000_000  # exclusive

EXPECT_SYSTEM_ID = "IntelliEarthGmAPDSensorS/N003"
EXPECT_SOFTWARE = "ESP ANALYST"
EXPECT_CREATION = (2016, 223)
EXPECT_POINT_FORMAT = 6
EXPECT_RECORD_LENGTH = 30
EXPECT_SCALE = (0.01, 0.01, 0.01)
EXPECT_OFFSET = (0.0, 0.0, 0.0)
EXPECT_CRS_SUBSTRING = b"NAD83(2011) / North Carolina (ftUS)"
LASZIP_USER_ID = b"laszip encoded"
LASZIP_RECORD_ID = 22204

SOURCES_FIELDS = [
    "tile_id", "pc_count", "vpc_datetime", "file_name", "size_bytes", "etag",
    "last_modified", "header_x_min_ft", "header_x_max_ft", "sha256", "url",
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
    return rows


def select(vpc_path: Path, links_path: Path) -> list[dict]:
    with vpc_path.open(encoding="utf-8") as handle:
        vpc = json.load(handle)
    if vpc.get("type") != "FeatureCollection" or not vpc.get("features"):
        raise SystemExit("VPC is not a non-empty STAC FeatureCollection")
    links = set()
    for line in links_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            links.add(line)
    if not all(link.startswith(URL_PREFIX) and link.endswith(".laz") for link in links):
        raise SystemExit("link list contains URLs outside the expected rockyweb LAZ directory")
    chosen = []
    for feature in vpc["features"]:
        props = feature["properties"]
        tile_id = feature["id"]
        if not tile_id.startswith(NAME_PREFIX):
            raise SystemExit(f"unexpected VPC feature id {tile_id}")
        if not props.get("datetime", "").startswith(SELECT_DATETIME):
            continue
        count = int(props["pc:count"])
        if count >= SELECT_MAX_COUNT:
            continue
        href = feature["assets"]["data"]["href"]
        file_name = tile_id + ".laz"
        if href != "./LAZ/" + file_name:
            raise SystemExit(f"unexpected asset href {href} for {tile_id}")
        url = URL_PREFIX + file_name
        if url not in links:
            raise SystemExit(f"selected tile {file_name} is missing from 0_file_download_links.txt")
        chosen.append({
            "tile_id": tile_id[len(NAME_PREFIX):],
            "pc_count": count,
            "vpc_datetime": props["datetime"],
            "file_name": file_name,
            "url": url,
        })
    chosen.sort(key=lambda row: row["tile_id"])
    return chosen


def parse_las_header(raw: bytes) -> dict:
    if len(raw) < 375 or raw[:4] != b"LASF":
        raise ValueError("missing LASF signature or short header")
    vmaj, vmin = raw[24], raw[25]
    system_id = cstr(raw[26:58])
    software = cstr(raw[58:90])
    day, year, header_size, offset_points, num_vlrs, fmt_raw, rec_len = struct.unpack_from("<HHHIIBH", raw, 90)
    scale = struct.unpack_from("<3d", raw, 131)
    offset = struct.unpack_from("<3d", raw, 155)
    max_x, min_x, max_y, min_y, max_z, min_z = struct.unpack_from("<6d", raw, 179)
    start_evlr, num_evlrs, count64 = struct.unpack_from("<QIQ", raw, 235)
    return {
        "version": (vmaj, vmin), "system_id": system_id, "software": software,
        "creation": (year, day), "header_size": header_size, "offset_to_points": offset_points,
        "num_vlrs": num_vlrs, "point_format_raw": fmt_raw, "record_length": rec_len,
        "scale": scale, "offset": offset, "min_x": min_x, "max_x": max_x,
        "start_evlr": start_evlr, "num_evlrs": num_evlrs, "point_count": count64,
        "legacy_count": struct.unpack_from("<I", raw, 107)[0],
    }


def check_header(raw: bytes, expected_count: int, file_size: int) -> dict:
    hdr = parse_las_header(raw)
    problems = []
    if hdr["version"] != (1, 4):
        problems.append(f"LAS version {hdr['version']}")
    if hdr["system_id"] != EXPECT_SYSTEM_ID:
        problems.append(f"system identifier {hdr['system_id']!r}")
    if hdr["software"] != EXPECT_SOFTWARE:
        problems.append(f"generating software {hdr['software']!r}")
    if hdr["creation"] != EXPECT_CREATION:
        problems.append(f"creation year/day {hdr['creation']}")
    if hdr["point_format_raw"] & 0x3F != EXPECT_POINT_FORMAT or not hdr["point_format_raw"] & 0x80:
        problems.append(f"point format byte {hdr['point_format_raw']} (want compressed format 6)")
    if hdr["record_length"] != EXPECT_RECORD_LENGTH:
        problems.append(f"record length {hdr['record_length']}")
    if hdr["scale"] != EXPECT_SCALE:
        problems.append(f"scale {hdr['scale']}")
    if any(value != 0.0 for value in hdr["offset"]):
        problems.append(f"offset {hdr['offset']}")
    if hdr["point_count"] != expected_count:
        problems.append(f"point count {hdr['point_count']} != pinned pc:count {expected_count}")
    if hdr["header_size"] != 375 or hdr["num_vlrs"] < 1 or hdr["num_evlrs"] < 1:
        problems.append(f"header size {hdr['header_size']}, VLRs {hdr['num_vlrs']}, EVLRs {hdr['num_evlrs']}")
    if not (hdr["offset_to_points"] < hdr["start_evlr"] < file_size):
        problems.append(f"EVLR start {hdr['start_evlr']} outside the file")
    if not (1_500_000.0 < hdr["min_x"] < hdr["max_x"] < 1_800_000.0):
        problems.append(f"X bounds {hdr['min_x']}..{hdr['max_x']} ft outside the Anson County State Plane window")
    if problems:
        raise ValueError("; ".join(problems))
    return hdr


def check_vlrs_evlrs(fh, hdr: dict) -> None:
    fh.seek(hdr["header_size"])
    prefix = fh.read(hdr["offset_to_points"] - hdr["header_size"])
    pos = 0
    laszip = None
    for _ in range(hdr["num_vlrs"]):
        user_id = prefix[pos + 2:pos + 18].split(b"\0", 1)[0]
        record_id, length = struct.unpack_from("<HH", prefix, pos + 18)
        data = prefix[pos + 54:pos + 54 + length]
        if user_id == LASZIP_USER_ID and record_id == LASZIP_RECORD_ID:
            laszip = data
        pos += 54 + length
    if laszip is None or len(laszip) < 34:
        raise ValueError("LASzip VLR missing")
    compressor, coder = struct.unpack_from("<HH", laszip, 0)
    chunk_size = struct.unpack_from("<I", laszip, 12)[0]
    num_items = struct.unpack_from("<H", laszip, 32)[0]
    items = [struct.unpack_from("<HHH", laszip, 34 + 6 * i) for i in range(num_items)]
    if (compressor, coder) != (3, 0) or items != [(10, 30, 3)] or chunk_size != 50000:
        raise ValueError(f"LASzip VLR compressor={compressor} coder={coder} chunk={chunk_size} items={items}")
    # Chunk table pointer: first 8 bytes of the point data.
    fh.seek(hdr["offset_to_points"])
    (table_offset,) = struct.unpack("<q", fh.read(8))
    if not (hdr["offset_to_points"] < table_offset < hdr["start_evlr"]):
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
        raise ValueError("OGC WKT EVLR with NAD83(2011) / North Carolina (ftUS) not found")


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
        hdr = check_header(raw, row["pc_count"], size)
        if f"{hdr['min_x']:.4f}" != row["header_x_min_ft"] or f"{hdr['max_x']:.4f}" != row["header_x_max_ft"]:
            raise ValueError("header X bounds differ from the pinned probe values")
        check_vlrs_evlrs(fh, hdr)
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
    writer = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    writer.writerow(["tile_id", "pc_count", "vpc_datetime", "file_name", "url"])
    for row in select(Path(args.vpc), Path(args.links)):
        writer.writerow([row[k] for k in ("tile_id", "pc_count", "vpc_datetime", "file_name", "url")])
    return 0


def cmd_make_sources(args) -> int:
    """Join the selection with per-tile 469-byte header probes (discover.sh)."""
    import re
    probe_dir = Path(args.probe_dir)
    writer = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    writer.writerow(SOURCES_FIELDS)
    for row in select(Path(args.vpc), Path(args.links)):
        headers = (probe_dir / (row["tile_id"] + ".headers")).read_text(encoding="latin-1")
        # Keep only the final response block (the proxy CONNECT block comes first).
        block = re.split(r"\r?\n\r?\n(?=HTTP/)", headers.strip())[-1]
        size = int(re.search(r"^content-range: bytes 0-468/(\d+)", block, re.I | re.M).group(1))
        etag = re.search(r"^etag: (\S+)", block, re.I | re.M).group(1).strip('"')
        modified = re.search(r"^last-modified: ([^\r\n]+)", block, re.I | re.M).group(1).strip()
        raw = (probe_dir / (row["tile_id"] + ".bin")).read_bytes()
        hdr = check_header(raw, row["pc_count"], size)
        writer.writerow([row["tile_id"], row["pc_count"], row["vpc_datetime"], row["file_name"],
                         size, etag, modified, f"{hdr['min_x']:.4f}", f"{hdr['max_x']:.4f}", "", row["url"]])
    return 0


def cmd_check_selection(args) -> int:
    derived = select(Path(args.vpc), Path(args.links))
    pinned = load_sources(Path(args.sources))
    key = lambda r: (r["tile_id"], int(r["pc_count"]), r["vpc_datetime"], r["file_name"], r["url"])
    if [key(r) for r in derived] != [key(r) for r in pinned]:
        print("FATAL: selection re-derived from the live VPC/link list differs from sources.tsv", file=sys.stderr)
        print("derived:", [r["tile_id"] for r in derived], file=sys.stderr)
        print("pinned: ", [r["tile_id"] for r in pinned], file=sys.stderr)
        return 1
    print(f"selection=ok tiles={len(pinned)} points={sum(r['pc_count'] for r in pinned)}")
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


def synthetic_header(count: int, system_id: str = EXPECT_SYSTEM_ID) -> bytes:
    raw = bytearray(375)
    raw[0:4] = b"LASF"
    raw[24], raw[25] = 1, 4
    raw[26:26 + len(system_id)] = system_id.encode()
    raw[58:58 + len(EXPECT_SOFTWARE)] = EXPECT_SOFTWARE.encode()
    struct.pack_into("<HHHIIBH", raw, 90, 223, 2016, 375, 469, 1, 0x86, 30)
    struct.pack_into("<3d", raw, 131, 0.01, 0.01, 0.01)
    struct.pack_into("<3d", raw, 155, 0.0, 0.0, 0.0)
    struct.pack_into("<6d", raw, 179, 1_732_500.5, 1_730_000.25, 0, 0, 0, 0)
    struct.pack_into("<QIQ", raw, 235, 10_000, 1, count)
    return bytes(raw)


def extract_x_strided(records: bytes, n: int) -> bytes:
    """Byte-lane copy of the first int32 of every 30-byte record (build.sh path)."""
    out = bytearray(4 * n)
    span = records[:30 * n]
    for lane in range(4):
        out[lane::4] = span[lane::30]
    return bytes(out)


def cmd_self_test(_args) -> int:
    hdr = check_header(synthetic_header(1234), 1234, 20_000)
    assert hdr["point_count"] == 1234 and hdr["system_id"] == EXPECT_SYSTEM_ID
    for bad in (synthetic_header(1234, "IntelliEarth GmAPD Sensors #2&3"), synthetic_header(1233)):
        try:
            check_header(bad, 1234, 20_000)
        except ValueError:
            pass
        else:
            raise AssertionError("bad header accepted")
    # X extraction on synthetic POINT14 records with extreme and negative values.
    xs = [163_000_000, -5, 0, 2**31 - 1, -(2**31), 173_499_524, 1]
    recs = b"".join(struct.pack("<iiiHBBBBhHd", x, 7, -9, 65535, 17, 0, 2, 0, 0, 0, 1.5) for x in xs)
    assert len(recs) == 30 * len(xs)
    got = extract_x_strided(recs, len(xs))
    assert got == struct.pack(f"<{len(xs)}i", *xs), "strided X extraction mismatch"
    assert [t[0] for t in struct.iter_unpack("<i26x", recs)] == xs
    # Selection on a synthetic VPC.
    with tempfile.TemporaryDirectory() as tmp:
        feats = []
        links = []
        for tid, count, dt in (("2", 100, "2016-08-10T00:00:00Z"), ("1", 8_999_999, "2016-08-10T00:00:00Z"),
                               ("3", 9_000_000, "2016-08-10T00:00:00Z"), ("4", 5, "2016-08-28T00:00:00Z")):
            name = NAME_PREFIX + tid
            feats.append({"id": name, "properties": {"datetime": dt, "pc:count": count},
                          "assets": {"data": {"href": f"./LAZ/{name}.laz"}}})
            links.append(URL_PREFIX + name + ".laz")
        vpc = Path(tmp) / "v.json"
        lst = Path(tmp) / "l.txt"
        vpc.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
        lst.write_text("\n".join(links) + "\n")
        assert [r["tile_id"] for r in select(vpc, lst)] == ["1", "2"]
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
