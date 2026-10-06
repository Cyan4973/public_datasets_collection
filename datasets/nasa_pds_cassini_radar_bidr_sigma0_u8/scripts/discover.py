#!/usr/bin/env python3
"""Resolve and pin the BIBQH Titan product selection (metadata only).

Used by discover.sh, which fetches with curl:
  select: S3 ListObjectsV2 XML pages (one per CORADR volume, prefix
          DATA/BIDR/BIBQH) -> selected.tsv (volume, product, sizes, ETags)
  pin:    detached .LBL labels and 1024-byte ZIP tails -> sources.tsv
"""
from __future__ import annotations

import argparse
import collections
import csv
import html
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bidr  # noqa: E402

FIRST_FLYBY = "00A"
LAST_FLYBY = "019"


def parse_listing(text: str) -> list[dict]:
    if "<IsTruncated>false</IsTruncated>" not in text:
        raise SystemExit("listing truncated or malformed")
    rows = []
    for block in re.findall(r"<Contents>(.*?)</Contents>", text, re.S):
        key = re.search(r"<Key>([^<]*)</Key>", block).group(1)
        etag = html.unescape(re.search(r"<ETag>([^<]*)</ETag>", block).group(1)).strip('"')
        size = int(re.search(r"<Size>(\d+)</Size>", block).group(1))
        rows.append({"key": key, "etag": etag, "size": size})
    return rows


def cmd_select(args: argparse.Namespace) -> None:
    objects = []
    for page in sorted(Path(args.listings).glob("CORADR_*.xml")):
        objects += parse_listing(page.read_text(encoding="utf-8"))
    key_re = re.compile(r"^RADAR/(CORADR_\d{4})/DATA/BIDR/(BIBQH[^/]+)\.(IMG|ZIP|LBL|xml)$")
    products: dict[tuple[str, str], dict] = {}
    for obj in objects:
        match = key_re.match(obj["key"])
        if match is None:
            raise SystemExit(f"unexpected key in BIBQH listing: {obj['key']}")
        volume, product, ext = match.groups()
        entry = products.setdefault((volume, product), {"volume": volume, "product_id": product})
        entry[ext] = obj
    population = collections.Counter()
    selected = []
    for (volume, product), entry in sorted(products.items()):
        if not all(ext in entry for ext in ("IMG", "ZIP", "LBL")):
            raise SystemExit(f"incomplete product file set: {volume}/{product}")
        match = bidr.PRODUCT_RE.match(product)
        if match is None:
            # The only non-Titan BIBQH product is the Enceladus E016 swath.
            if not re.fullmatch(r"BIBQH\d\d[NS]\d{3}_D\d{3}_E\d{3}S\d\d_V\d\d", product):
                raise SystemExit(f"unexpected BIBQH product name: {product}")
            population["non_titan_flyby"] += 1
            continue
        population["titan_flyby"] += 1
        flyby = match.group("flyby")
        for ext in ("IMG", "ZIP"):
            if "-" in entry[ext]["etag"] or not re.fullmatch(r"[0-9a-f]{32}", entry[ext]["etag"]):
                raise SystemExit(f"ETag is not a single-part MD5: {product}.{ext}")
        if bidr.flyby_order(FIRST_FLYBY) <= bidr.flyby_order(flyby) <= bidr.flyby_order(LAST_FLYBY):
            selected.append({
                "volume": volume,
                "product_id": product,
                "flyby": "T" + flyby,
                "segment": "S" + match.group("segment"),
                "datatake": "D" + match.group("datatake"),
                "zip_bytes": entry["ZIP"]["size"],
                "zip_md5": entry["ZIP"]["etag"],
                "img_bytes": entry["IMG"]["size"],
                "img_md5": entry["IMG"]["etag"],
            })
    bases = collections.Counter(row["product_id"][:-4] for row in selected)
    if any(count > 1 for count in bases.values()):
        raise SystemExit("multiple versions of one product base in selection")
    selected.sort(key=lambda row: (bidr.flyby_order(row["flyby"][1:]), row["segment"], row["product_id"]))
    columns = list(selected[0].keys())
    with open(args.out, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(selected)
    print(
        f"bibqh_products={sum(population.values())} titan={population['titan_flyby']} "
        f"non_titan={population['non_titan_flyby']} selected={len(selected)} "
        f"zip_bytes={sum(r['zip_bytes'] for r in selected)} img_bytes={sum(r['img_bytes'] for r in selected)}"
    )


def parse_zip_tail(tail: bytes, row: dict) -> dict:
    pid = row["product_id"]
    eocd = tail.rfind(b"PK\x05\x06")
    if eocd < 0 or len(tail) - eocd < 22:
        raise SystemExit(f"{pid}: ZIP end-of-central-directory not found in tail")
    (_, disk, cd_disk, entries_disk, entries, cd_size, cd_offset, comment_len) = struct.unpack_from(
        "<IHHHHIIH", tail, eocd
    )
    if disk or cd_disk or entries_disk != 1 or entries != 1:
        raise SystemExit(f"{pid}: ZIP must hold exactly one member")
    if cd_offset + cd_size + 22 + comment_len != row["zip_bytes"]:
        raise SystemExit(f"{pid}: ZIP central directory geometry inconsistent with object size")
    cd = eocd - cd_size
    if cd < 0 or tail[cd : cd + 4] != b"PK\x01\x02":
        raise SystemExit(f"{pid}: central directory header not found")
    (_, _, _, flags, method, _, _, crc, csize, usize, name_len, extra_len, cmt_len, _, _, _, lho) = struct.unpack_from(
        "<IHHHHHHIIIHHHHHII", tail, cd
    )
    name = tail[cd + 46 : cd + 46 + name_len].decode("ascii")
    if name != pid + ".IMG":
        raise SystemExit(f"{pid}: ZIP member name {name!r} != {pid}.IMG")
    if method != 8 or flags & 0x1:
        raise SystemExit(f"{pid}: ZIP member must be unencrypted DEFLATE")
    if usize != row["img_bytes"] or lho != 0:
        raise SystemExit(f"{pid}: ZIP member size/offset mismatch")
    return {"zip_member_crc32": f"{crc:08x}", "zip_member_compressed_bytes": csize}


def cmd_pin(args: argparse.Namespace) -> None:
    selected = list(csv.DictReader(open(args.selected, encoding="utf-8"), delimiter="\t"))
    meta_dir = Path(args.meta)
    rows = []
    for ordinal, sel in enumerate(selected, 1):
        sel = {k: (int(v) if k in ("zip_bytes", "img_bytes") else v) for k, v in sel.items()}
        pid = sel["product_id"]
        label = bidr.parse_pds3((meta_dir / f"{pid}.LBL").read_text(encoding="ascii"))
        ctx = f"{pid} detached label"
        bidr.require(label, "PRODUCT_ID", pid, ctx)
        bidr.require(label, "DATA_SET_ID", bidr.DATA_SET_ID, ctx)
        bidr.require(label, "TARGET_NAME", bidr.TARGET_NAME, ctx)
        bidr.require(label, "PRODUCER_INSTITUTION_NAME", bidr.PRODUCER_INSTITUTION_NAME, ctx)
        bidr.require(label, "COMPRESSED_FILE.FILE_NAME", pid + ".ZIP", ctx)
        bidr.require(label, "COMPRESSED_FILE.ENCODING_TYPE", "ZIP", ctx)
        bidr.require(label, "COMPRESSED_FILE.UNCOMPRESSED_FILE_NAME", pid + ".IMG", ctx)
        bidr.require(label, "COMPRESSED_FILE.REQUIRED_STORAGE_BYTES", str(sel["img_bytes"]), ctx)
        bidr.require(label, "UNCOMPRESSED_FILE.FILE_NAME", pid + ".IMG", ctx)
        bidr.require(label, "UNCOMPRESSED_FILE.RECORD_TYPE", "FIXED_LENGTH", ctx)
        img = "UNCOMPRESSED_FILE.IMAGE."
        bidr.require(label, img + "SAMPLE_TYPE", bidr.SAMPLE_TYPE, ctx)
        bidr.require(label, img + "SAMPLE_BITS", bidr.SAMPLE_BITS, ctx)
        bidr.require(label, img + "SCALING_FACTOR", bidr.SCALING_FACTOR, ctx)
        bidr.require(label, img + "OFFSET", bidr.OFFSET, ctx)
        bidr.require(label, img + "MISSING_CONSTANT", bidr.MISSING_CONSTANT, ctx)
        proj = "UNCOMPRESSED_FILE.IMAGE_MAP_PROJECTION."
        bidr.require(label, proj + "MAP_RESOLUTION", bidr.MAP_RESOLUTION, ctx)
        bidr.require(label, proj + "MAP_PROJECTION_TYPE", bidr.MAP_PROJECTION_TYPE, ctx)
        pointer = re.fullmatch(r'\("([^"]+)",\s*(\d+)\)', label["UNCOMPRESSED_FILE.^IMAGE"])
        if pointer is None or pointer.group(1) != pid + ".IMG":
            raise SystemExit(f"{ctx}: unexpected ^IMAGE pointer {label['UNCOMPRESSED_FILE.^IMAGE']}")
        geometry = {
            "record_bytes": int(label["UNCOMPRESSED_FILE.RECORD_BYTES"]),
            "file_records": int(label["UNCOMPRESSED_FILE.FILE_RECORDS"]),
            "label_records": int(label["UNCOMPRESSED_FILE.LABEL_RECORDS"]),
            "image_start_record": int(pointer.group(2)),
            "lines": int(label[img + "LINES"]),
            "line_samples": int(label[img + "LINE_SAMPLES"]),
            "image_checksum": int(label[img + "CHECKSUM"]),
        }
        bidr.check_geometry(geometry, sel["img_bytes"], pid)
        zip_info = parse_zip_tail((meta_dir / f"{pid}.ZIP.tail").read_bytes(), sel)
        rows.append({
            "ordinal": ordinal,
            "volume": sel["volume"],
            "product_id": pid,
            "flyby": sel["flyby"],
            "segment": sel["segment"],
            "datatake": sel["datatake"],
            "zip_bytes": sel["zip_bytes"],
            "zip_md5": sel["zip_md5"],
            **zip_info,
            "img_bytes": sel["img_bytes"],
            "img_md5": sel["img_md5"],
            **geometry,
            "start_time": label["START_TIME"],
            "stop_time": label["STOP_TIME"],
        })
    with open(args.out, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=bidr.PLAN_COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(
        f"pinned={len(rows)} zip_bytes={sum(r['zip_bytes'] for r in rows)} "
        f"img_bytes={sum(r['img_bytes'] for r in rows)} "
        f"pixel_bytes={sum(r['lines'] * r['line_samples'] for r in rows)} "
        f"record_bytes={sorted({r['record_bytes'] for r in rows})} "
        f"label_records={sorted({r['label_records'] for r in rows})}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sel = sub.add_parser("select")
    sel.add_argument("--listings", required=True)
    sel.add_argument("--out", required=True)
    pin = sub.add_parser("pin")
    pin.add_argument("--selected", required=True)
    pin.add_argument("--meta", required=True)
    pin.add_argument("--out", required=True)
    args = parser.parse_args()
    {"select": cmd_select, "pin": cmd_pin}[args.cmd](args)


if __name__ == "__main__":
    main()
