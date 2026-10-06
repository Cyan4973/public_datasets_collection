#!/usr/bin/env python3
"""Discovery probe for mpc_modis_mod13a1_ndvi_i16 (documentation; not run by build/verify).

Resolves exact MOD13A1.061 Terra item IDs on the Microsoft Planetary Computer
STAC API for candidate MODIS sinusoidal tiles and two 2024 composite periods,
then reads only the COG header and the single-tile 300x300 overview with HTTP
range requests to record: blob size, x-ms-blob-content-md5, primary-IFD
structure, GDAL metadata (PERCENTLAND, QA percentages), and an overview-based
fill (-3000) fraction estimate. Network I/O goes through curl (subprocess) so
the proxy configuration in ~/.curlrc applies.

Usage: probe.py OUT.tsv h08v05 h09v05 ...
"""
from __future__ import annotations

import base64
import json
import re
import struct
import subprocess
import sys
import zlib

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
SAS = "https://planetarycomputer.microsoft.com/api/sas/v1/token/modiseuwest/modis-061-cogs"
COLLECTION = "modis-13A1-061"
ASSET = "500m_16_days_NDVI"
PERIODS = {17: "2024-01-17", 193: "2024-07-11"}
TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 16: 8}
TYPE_FMT = {1: "B", 3: "H", 4: "I", 8: "h", 9: "i", 12: "d", 16: "Q"}


def curl(args: list[str]) -> bytes:
    return subprocess.run(["curl", "-fsSL", "--retry", "6", "--retry-all-errors", "--retry-delay", "3", "--max-time", "120", *args],
                          check=True, capture_output=True).stdout


def ranged(url: str, start: int, end: int) -> tuple[bytes, dict[str, str]]:
    out = subprocess.run(["curl", "-fsS", "--retry", "6", "--retry-all-errors", "--retry-delay", "3", "--max-time", "120", "-r", f"{start}-{end}",
                          "-D", "-", "-o", "/dev/stdout", url], check=True, capture_output=True).stdout
    # last header block precedes the body
    split = out.rfind(b"\r\n\r\n", 0, out.find(b"HTTP/1.1 206") + 4096) + 4
    head, body = out[:split].decode("latin1"), out[split:]
    headers = {}
    for line in head.split("\r\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return body, headers


def parse_ifds(data: bytes) -> list[dict[int, object]]:
    e = "<"
    assert data[:4] == b"II*\x00", "expected little-endian classic TIFF"
    off = struct.unpack_from("<I", data, 4)[0]
    ifds = []
    while off:
        n = struct.unpack_from(e + "H", data, off)[0]
        tags: dict[int, object] = {}
        for i in range(n):
            p = off + 2 + 12 * i
            tag, ft, cnt = struct.unpack_from(e + "HHI", data, p)
            size = TYPE_SIZE[ft] * cnt
            if size <= 4:
                raw = data[p + 8:p + 8 + size]
            else:
                vo = struct.unpack_from(e + "I", data, p + 8)[0]
                raw = data[vo:vo + size]
                assert len(raw) == size, "IFD value outside probed header range"
            if ft == 2:
                tags[tag] = raw.rstrip(b"\0").decode("latin1")
            elif ft in TYPE_FMT:
                tags[tag] = list(struct.unpack(e + TYPE_FMT[ft] * cnt, raw))
        ifds.append(tags)
        off = struct.unpack_from(e + "I", data, off + 2 + 12 * n)[0]
    return ifds


def main() -> None:
    out_path, tiles = sys.argv[1], sys.argv[2:]
    query = json.loads(curl([SAS]))["token"].lstrip("?")
    rows = []
    for tile in tiles:
        h, v = int(tile[1:3]), int(tile[4:6])
        for doy, day in PERIODS.items():
            body = json.dumps({
                "collections": [COLLECTION],
                "datetime": f"{day}T00:00:00Z/{day}T23:59:59Z",
                "query": {"modis:horizontal-tile": {"eq": h}, "modis:vertical-tile": {"eq": v}},
                "limit": 50,
            })
            feats = json.loads(curl(["-H", "Content-Type: application/json", "-X", "POST", "-d", body, STAC]))["features"]
            prefix = f"MOD13A1.A2024{doy:03d}.h{h:02d}v{v:02d}.061."
            hits = [f for f in feats if f["id"].startswith(prefix)]
            if len(hits) != 1:
                print(f"{tile} doy={doy}: {len(hits)} Terra items", file=sys.stderr)
                continue
            item = hits[0]
            href = item["assets"][ASSET]["href"]
            head, headers = ranged(f"{href}?{query}", 0, 32767)
            total = int(headers["content-range"].rsplit("/", 1)[1])
            md5 = headers.get("x-ms-blob-content-md5", "")
            ifds = parse_ifds(head)
            p = ifds[0]
            struct_ok = (p[256] == [2400] and p[257] == [2400] and p[258] == [16] and p[259] == [8]
                         and p.get(317, [1]) == [1] and p[322] == [512] and p[323] == [512]
                         and p[339] == [2] and p.get(42113) == "-3000" and len(p[324]) == 25)
            meta = str(p.get(42112, ""))
            def item_meta(name: str) -> str:
                m = re.search(rf'<Item name="{name}">([^<]*)</Item>', meta)
                return m.group(1) if m else ""
            ov = ifds[-1]
            assert ov[256] == [300] and len(ov[324]) == 1
            ov_off, ov_len = ov[324][0], ov[325][0]
            raw, _ = ranged(f"{href}?{query}", ov_off, ov_off + ov_len - 1)
            px = struct.unpack("<" + "h" * (512 * 512), zlib.decompress(raw))
            vals = [px[r * 512 + c] for r in range(300) for c in range(300)]
            fill = sum(1 for x in vals if x == -3000) / len(vals)
            valid = [x for x in vals if x != -3000]
            rows.append({
                "tile": tile, "doy": f"{doy:03d}", "start_date": day, "item_id": item["id"],
                "start_datetime": item["properties"].get("start_datetime", ""),
                "end_datetime": item["properties"].get("end_datetime", ""),
                "href": href, "size": total, "md5_b64": md5,
                "md5_hex": base64.b64decode(md5).hex() if md5 else "",
                "struct_ok": int(struct_ok), "percent_land": item_meta("PERCENTLAND"),
                "qa_notproduced_other": item_meta("QAPERCENTNOTPRODUCEDOTHER"),
                "qa_notproduced_cloud": item_meta("QAPERCENTNOTPRODUCEDCLOUD"),
                "ov_fill_fraction": round(fill, 4),
                "ov_min": min(valid) if valid else "", "ov_max": max(valid) if valid else "",
                "ov_distinct": len(set(valid)),
            })
            print("\t".join(str(x) for x in rows[-1].values()), file=sys.stderr)
    with open(out_path, "w", encoding="utf-8") as fh:
        keys = list(rows[0])
        fh.write("\t".join(keys) + "\n")
        for r in rows:
            fh.write("\t".join(str(r[k]) for k in keys) + "\n")


if __name__ == "__main__":
    main()
