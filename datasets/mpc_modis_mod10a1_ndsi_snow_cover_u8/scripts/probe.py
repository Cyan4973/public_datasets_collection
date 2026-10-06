#!/usr/bin/env python3
"""Discovery probe for mpc_modis_mod10a1_ndsi_snow_cover_u8.

Documentation of how sources.tsv was resolved; build.sh and verify.sh never
run it.

For each probe date it runs one STAC /search on collection modis-10A1-061
for every tile in MODIS sinusoidal rows v02-v05 (about 30-70 N; all such
tiles fit on one result page). It keeps only Terra items: the ID must start
with 'MOD10A1.A2024<DOY>.' and the platform property must be 'terra' (Aqua
MYD10A1 items match the same query). For each kept item it then reads only
the NDSI_Snow_Cover COG header plus the single-tile 300x300 overview, using
HTTP range requests (about 30-90 KB per item), and records:

  * blob size (Content-Range) and the Azure x-ms-blob-content-md5;
  * primary-IFD structure;
  * embedded HDF-EOS metadata (SNOWCOVERPERCENT, QAPERCENTCLOUDCOVER.1,
    PRODUCTIONDATETIME);
  * estimated class fractions from the 300x300 overview: valid 0..100,
    snow 1..100, cloud 250, night 211, ocean 239, inland water 237, fill 255.

Overview pixels come from GDAL averaging-style resampling. Where valid
pixels border flag codes this produces in-between values (101..249), which
count as "not valid". The valid fraction estimate is therefore conservative.
build.sh and verify.sh measure the real full-resolution grid.

Network I/O goes through curl (subprocess) so the proxy settings in
~/.curlrc apply. The SAS endpoint sometimes answers with non-JSON when it is
hit quickly, so the token request retries with backoff.

Usage: probe.py OUT_CANDIDATES.tsv YYYY-MM-DD [YYYY-MM-DD ...]
"""
from __future__ import annotations

import base64
import concurrent.futures as cf
import datetime as dt
import json
import re
import struct
import subprocess
import sys
import threading
import time
import zlib

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
SAS = "https://planetarycomputer.microsoft.com/api/sas/v1/token/modiseuwest/modis-061-cogs"
COLLECTION = "modis-10A1-061"
ASSET = "NDSI_Snow_Cover"
ROWS = (2, 5)
KEY = ("0-100=NDSI snow, 200=missing data, 201=no decision, 211=night, 237=inland water, "
       "239=ocean, 250=cloud, 254=detector saturated, 255=fill")
TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 16: 8}
TYPE_FMT = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 11: "f", 12: "d", 16: "Q"}

_sas_lock = threading.Lock()
_sas = {"token": "", "at": 0.0}


def curl(args: list[str]) -> bytes:
    return subprocess.run(["curl", "-fsSL", "--retry", "6", "--retry-all-errors", "--retry-delay", "3",
                           "--max-time", "120", *args], check=True, capture_output=True).stdout


def sas_token() -> str:
    with _sas_lock:
        if _sas["token"] and time.time() - _sas["at"] < 1200:
            return _sas["token"]
        for attempt in range(8):
            try:
                body = curl([SAS])
                token = str(json.loads(body)["token"]).lstrip("?")
                if token:
                    _sas.update(token=token, at=time.time())
                    return token
            except (subprocess.CalledProcessError, ValueError, KeyError):
                pass
            time.sleep(2 * 2 ** attempt)
        raise SystemExit("could not obtain a SAS token")


def ranged(url: str, start: int, end: int) -> tuple[bytes, dict[str, str]]:
    proc = subprocess.run(["curl", "-fsS", "--retry", "6", "--retry-all-errors", "--retry-delay", "3",
                           "--max-time", "120", "-r", f"{start}-{end}", "-D", "/dev/stderr", "-o", "-",
                           f"{url}?{sas_token()}"], check=True, capture_output=True)
    headers: dict[str, str] = {}
    for line in proc.stderr.decode("latin-1").split("\r\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return proc.stdout, headers


def parse_ifds(data: bytes) -> list[dict[int, object]]:
    assert data[:4] == b"II*\x00", "expected little-endian classic TIFF"
    off = struct.unpack_from("<I", data, 4)[0]
    ifds = []
    while off:
        n = struct.unpack_from("<H", data, off)[0]
        tags: dict[int, object] = {}
        for i in range(n):
            p = off + 2 + 12 * i
            tag, ft, cnt = struct.unpack_from("<HHI", data, p)
            size = TYPE_SIZE[ft] * cnt
            if size <= 4:
                raw = data[p + 8:p + 8 + size]
            else:
                vo = struct.unpack_from("<I", data, p + 8)[0]
                raw = data[vo:vo + size]
                assert len(raw) == size, "IFD value outside probed header range"
            if ft == 2:
                tags[tag] = raw.rstrip(b"\0").decode("latin-1")
            elif ft in TYPE_FMT:
                tags[tag] = list(struct.unpack("<" + TYPE_FMT[ft] * cnt, raw))
        ifds.append(tags)
        off = struct.unpack_from("<I", data, off + 2 + 12 * n)[0]
    return ifds


def search(day: str) -> list[dict]:
    body = json.dumps({
        "collections": [COLLECTION],
        "datetime": f"{day}T00:00:00Z/{day}T23:59:59Z",
        "query": {"modis:vertical-tile": {"gte": ROWS[0], "lte": ROWS[1]}},
        "limit": 1000,
    })
    page = json.loads(curl(["-H", "Content-Type: application/json", "-X", "POST", "-d", body, STAC]))
    if any(link.get("rel") == "next" for link in page.get("links", [])):
        raise SystemExit(f"{day}: STAC result is paged; extend the probe")
    doy = dt.date.fromisoformat(day).timetuple().tm_yday
    prefix = f"MOD10A1.A{day[:4]}{doy:03d}."
    items = [f for f in page["features"]
             if f["id"].startswith(prefix) and f["properties"].get("platform") == "terra"]
    tiles = [f["id"].split(".")[2] for f in items]
    if len(tiles) != len(set(tiles)):
        raise SystemExit(f"{day}: more than one Terra item for a tile")
    return items


def probe_item(day: str, item: dict) -> dict[str, object]:
    href = item["assets"][ASSET]["href"]
    head, headers = ranged(href, 0, 65535)
    total = int(headers["content-range"].rsplit("/", 1)[1])
    md5 = headers.get("x-ms-blob-content-md5", "")
    ifds = parse_ifds(head)
    p = ifds[0]
    struct_ok = (p[256] == [2400] and p[257] == [2400] and p[258] == [8] and p[259] == [8]
                 and p.get(317, [1]) == [1] and p[322] == [512] and p[323] == [512]
                 and p.get(42113) == "255" and len(p[324]) == 25 and len(ifds) == 4)
    meta = str(p.get(42112, ""))

    def item_meta(name: str) -> str:
        m = re.search(rf'<Item name="{re.escape(name)}"[^>]*>([^<]*)</Item>', meta)
        return m.group(1) if m else ""

    tile = item["id"].split(".")[2]
    doy = dt.date.fromisoformat(day).timetuple().tm_yday
    # The same stable metadata fields that scripts/mod10a1_cog.py enforces.
    expected_meta = {
        "SHORTNAME": "MOD10A1", "VERSIONID": "61", "ASSOCIATEDPLATFORMSHORTNAME.1": "Terra",
        "LOCALGRANULEID": f"{item['id']}.hdf", "HORIZONTALTILENUMBER": str(int(tile[1:3])),
        "VERTICALTILENUMBER": str(int(tile[4:6])), "RANGEBEGINNINGDATE": day, "RANGEENDINGDATE": day,
        "Key": KEY, "long_name": "NDSI snow cover from best observation of the day",
        "_FillValue": "255", "missing_value": "200", "valid_range": "0, 100",
        "identifier_product_doi": "10.5067/MODIS/MOD10A1.061", "DATACOLUMNS": "2400", "DATAROWS": "2400",
    }
    meta_wrong = {k: item_meta(k) for k, v in expected_meta.items() if item_meta(k) != v}

    ov = ifds[-1]
    assert ov[256] == [300] and len(ov[324]) == 1, "unexpected smallest overview"
    ov_off, ov_len = ov[324][0], ov[325][0]
    if ov_off + ov_len <= len(head):
        raw = head[ov_off:ov_off + ov_len]
    else:
        raw, _ = ranged(href, ov_off, ov_off + ov_len - 1)
    px = zlib.decompress(raw)
    vals = [px[r * 512 + c] for r in range(300) for c in range(300)]
    n = len(vals)
    counts = [0] * 256
    for x in vals:
        counts[x] += 1
    return {
        "date": day, "doy": f"{doy:03d}", "tile": tile, "item_id": item["id"],
        "platform": item["properties"].get("platform", ""), "href": href, "size_bytes": total,
        "md5_b64": md5, "md5_hex": base64.b64decode(md5).hex() if md5 else "",
        "struct_ok": int(struct_ok), "meta_ok": int(not meta_wrong),
        "meta_mismatch": ";".join(f"{k}={v}" for k, v in sorted(meta_wrong.items())) or "-",
        "production_datetime": item_meta("PRODUCTIONDATETIME"),
        "hdr_snowcoverpercent": item_meta("SNOWCOVERPERCENT"),
        "hdr_cloudpercent": item_meta("QAPERCENTCLOUDCOVER.1"),
        "ov_valid": round(sum(counts[0:101]) / n, 4),
        "ov_snow": round(sum(counts[1:101]) / n, 4),
        "ov_cloud": round(counts[250] / n, 4),
        "ov_night": round(counts[211] / n, 4),
        "ov_ocean": round(counts[239] / n, 4),
        "ov_inland_water": round(counts[237] / n, 4),
        "ov_fill": round(counts[255] / n, 4),
    }


def main() -> None:
    out_path, days = sys.argv[1], sys.argv[2:]
    jobs = []
    for day in days:
        items = search(day)
        print(f"{day}: {len(items)} Terra items in rows v{ROWS[0]:02d}-v{ROWS[1]:02d}", file=sys.stderr)
        jobs.extend((day, item) for item in items)
    sas_token()
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(lambda job: probe_item(*job), jobs))
    rows.sort(key=lambda r: (r["date"], r["tile"]))
    keys = list(rows[0])
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\t".join(keys) + "\n")
        for r in rows:
            fh.write("\t".join(str(r[k]) for k in keys) + "\n")
    print(f"wrote {len(rows)} candidate rows to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
