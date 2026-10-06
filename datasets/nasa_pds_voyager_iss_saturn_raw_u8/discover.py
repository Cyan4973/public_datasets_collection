#!/usr/bin/env python3
"""Resolve the pinned frame list (sources.tsv) for nasa_pds_voyager_iss_saturn_raw_u8.

Author-time tool, not part of download/build/verify. Network I/O goes through
curl (the recipe never uses urllib). Steps:

1. Fetch VGISS_0005/INDEX/INDEX.TAB + INDEX.LBL from the public
   asc-pds-voyager bucket and apply the selection rule in scripts/vgiss.py
   (Voyager 2, narrow-angle camera, scan 3:1, edit 1:1, low gain, target
   SATURN or S RINGS, shutter not BODARK, not under CALIB/, no anomaly).
2. List the bucket prefix VGISS_0005/ with ListObjectsV2 continuation-token
   pagination (1000 keys per page) to get size, ETag (= MD5 for these
   single-part objects) and Last-Modified for every selected *_RAW.IMG and
   *_RAW.LBL, plus the pinned INDEX/AAREADME objects.
3. Fetch every selected detached label (about 3.7 KB) and range-probe the
   first 3,328 bytes of every image (VICAR label, two binary-label records,
   first line prefix) to confirm the label/VICAR keywords before pinning.
4. Write sources.tsv sorted by FDS image number, and print pins for the
   manifest/download.sh.

Usage: python3 discover.py [--work /tmp/autocollect/voyager/discover]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "scripts"))
import vgiss  # noqa: E402

UA = "openzl-public-datasets-voyager-iss-discover/1.0"
PINNED_FILES = ["INDEX/INDEX.TAB", "INDEX/INDEX.LBL", "AAREADME.TXT"]


def curl(args: list[str]) -> bytes:
    cmd = ["curl", "--fail", "--silent", "--show-error", "--location", "--retry", "5", "--retry-delay", "3",
           "--max-time", "600", "--user-agent", UA] + args
    return subprocess.run(cmd, check=True, capture_output=True).stdout


def list_prefix(prefix: str) -> dict[str, dict]:
    objects: dict[str, dict] = {}
    token = None
    pages = 0
    while True:
        query = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        if token:
            query["continuation-token"] = token
        xml = curl([f"{vgiss.BUCKET}/?{urllib.parse.urlencode(query)}"]).decode("utf-8")
        pages += 1
        for block in re.findall(r"<Contents>(.*?)</Contents>", xml, flags=re.S):
            key = re.search(r"<Key>([^<]*)</Key>", block).group(1)
            objects[key] = {
                "size": int(re.search(r"<Size>(\d+)</Size>", block).group(1)),
                "etag": re.search(r"<ETag>([^<]*)</ETag>", block).group(1).replace("&quot;", "").strip('"'),
                "last_modified": re.search(r"<LastModified>([^<]*)</LastModified>", block).group(1),
            }
        if "<IsTruncated>true</IsTruncated>" not in xml:
            break
        token = re.search(r"<NextContinuationToken>([^<]*)</NextContinuationToken>", xml).group(1)
        token = token.replace("&amp;", "&")
    print(f"listed {len(objects)} keys under {prefix} in {pages} pages")
    return objects


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, default=Path("/tmp/autocollect/voyager/discover"))
    args = parser.parse_args()
    work = args.work
    (work / "lbl").mkdir(parents=True, exist_ok=True)
    (work / "head").mkdir(parents=True, exist_ok=True)
    base = f"{vgiss.BUCKET}/{vgiss.VOLUME}"

    objects = list_prefix(f"{vgiss.VOLUME}/")
    for rel in PINNED_FILES:
        meta = objects[f"{vgiss.VOLUME}/{rel}"]
        target = work / rel.replace("/", "_")
        target.write_bytes(curl([f"{base}/{rel}"]))
        md5, _ = vgiss.digests(target.read_bytes())
        if target.stat().st_size != meta["size"] or md5 != meta["etag"]:
            raise SystemExit(f"{rel}: size/MD5 disagree with listing")
        print(f"pin {rel} size={meta['size']} md5={md5} last_modified={meta['last_modified']}")

    rows = vgiss.parse_index(work / "INDEX_INDEX.TAB")
    selected = vgiss.select(rows)
    print(f"index rows={len(rows)} selected={len(selected)}")

    records = []
    for row in selected:
        spec = row["file_specification_name"]
        if not spec.endswith("_RAW.LBL"):
            raise SystemExit(f"unexpected label path {spec}")
        product = vgiss.product_name(row["image_number"])
        if Path(spec).name != f"{product}_RAW.LBL" or row["product_id"] != f"{product}_RAW.IMG.V1":
            raise SystemExit(f"{spec}: product name does not match image number {row['image_number']}")
        stem = spec[: -len(".LBL")]
        img_key, lbl_key = f"{vgiss.VOLUME}/{stem}.IMG", f"{vgiss.VOLUME}/{stem}.LBL"
        img, lbl = objects.get(img_key), objects.get(lbl_key)
        if img is None or lbl is None:
            raise SystemExit(f"{stem}: missing from bucket listing")
        if img["size"] != vgiss.FILE_BYTES or not re.fullmatch(r"[0-9a-f]{32}", img["etag"]):
            raise SystemExit(f"{img_key}: size {img['size']} / ETag {img['etag']} not a single-part 823,296-byte object")
        records.append((row, product, stem, img, lbl))

    # Batch-fetch labels and image-head ranges, 50 URLs per curl call (connection reuse).
    for start in range(0, len(records), 50):
        chunk = records[start:start + 50]
        lbl_args: list[str] = []
        head_args: list[str] = ["--range", "0-3327"]
        for _row, product, stem, _img, _lbl in chunk:
            lbl_args += ["--output", str(work / "lbl" / f"{product}_RAW.LBL"), f"{base}/{stem}.LBL"]
            head_args += ["--output", str(work / "head" / f"{product}.head"), f"{base}/{stem}.IMG"]
        curl(lbl_args)
        curl(head_args)

    out_rows = []
    for row, product, stem, img, lbl in records:
        lbl_path = work / "lbl" / f"{product}_RAW.LBL"
        blob = lbl_path.read_bytes()
        md5, _ = vgiss.digests(blob)
        if len(blob) != lbl["size"] or md5 != lbl["etag"]:
            raise SystemExit(f"{product}: label size/MD5 disagree with listing")
        top = vgiss.check_label(blob.decode("ascii"), row["image_number"], product)
        for key, col in (("TARGET_NAME", "target_name"), ("FILTER_NAME", "filter_name"),
                         ("SHUTTER_MODE_ID", "shutter_mode"), ("IMAGE_ID", "image_id")):
            if top.get(key) != row[col]:
                raise SystemExit(f"{product}: label {key}={top.get(key)!r} != index {row[col]!r}")
        if float(top["EXPOSURE_DURATION"]) != float(row["exposure_duration"]):
            raise SystemExit(f"{product}: exposure mismatch label/index")
        head = (work / "head" / f"{product}.head").read_bytes()
        if len(head) != 3328:
            raise SystemExit(f"{product}: range probe returned {len(head)} bytes")
        vicar = vgiss.parse_vicar_label(head[:vgiss.LBLSIZE])
        for key, value in vgiss.VICAR_REQUIRED.items():
            if vicar.get(key) != value:
                raise SystemExit(f"{product}: VICAR {key}={vicar.get(key)!r}")
        if "SCAN RATE  3:1" not in vicar.get("LAB03", "") or not vicar.get("LAB03", "").startswith("NA CAMERA"):
            raise SystemExit(f"{product}: VICAR LAB03 {vicar.get('LAB03')!r}")
        prefix = head[vgiss.IMAGE_OFFSET:]
        major, minor = (int(p) for p in row["image_number"].split("."))
        if (prefix[22] | (prefix[23] << 8), prefix[24]) != (major, minor):
            raise SystemExit(f"{product}: first line prefix FDS mismatch")
        out_rows.append({
            "image_number": row["image_number"],
            "product": product,
            "volume_path": stem,
            "img_url": f"{base}/{stem}.IMG",
            "img_size": str(img["size"]),
            "img_md5": img["etag"],
            "img_last_modified": img["last_modified"],
            "lbl_url": f"{base}/{stem}.LBL",
            "lbl_size": str(lbl["size"]),
            "lbl_md5": lbl["etag"],
            "target_name": row["target_name"],
            "filter_name": row["filter_name"],
            "filter_number": row["filter_number"],
            "exposure_s": row["exposure_duration"],
            "shutter_mode": row["shutter_mode"],
            "image_time": row["image_time"],
            "image_id": row["image_id"],
        })

    columns = list(out_rows[0].keys())
    with (HERE / "sources.tsv").open("w", encoding="utf-8", newline="") as handle:
        handle.write("\t".join(columns) + "\n")
        for out in out_rows:
            handle.write("\t".join(out[c] for c in columns) + "\n")
    total = sum(int(r["img_size"]) + int(r["lbl_size"]) for r in out_rows)
    print(f"wrote sources.tsv rows={len(out_rows)} frame+label bytes={total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
