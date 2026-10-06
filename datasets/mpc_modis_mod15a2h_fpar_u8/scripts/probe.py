#!/usr/bin/env python3
"""Discovery probe for mpc_modis_mod15a2h_fpar_u8 (documentation; not run by build/verify).

Resolves exact MOD15A2H.061 Terra item IDs on the Microsoft Planetary Computer
STAC API (collection modis-15A2H-061) for candidate MODIS sinusoidal tiles and
2024 8-day composite periods. It then reads only the Fpar_500m COG header and
the single-tile 300x300 overview with HTTP range requests (about 90 KB per
item) and records: blob size, x-ms-blob-content-md5, primary-IFD structure,
embedded HDF-EOS metadata (QA percentages), and overview-based estimates of
the valid (0..100) fraction and of each fill class (248..255).

The STAC 'platform' property is empty for this collection, and Aqua
(MYD15A2H) and combined (MCD15A2H) items match the same query, so only IDs
starting with 'MOD15A2H.A2024<DOY>.hHHvVV.061.' are kept.

Overview pixels come from GDAL resampling, so they are only an estimate of
the class fractions; build.sh and verify.sh measure the real grid.

Network I/O goes through curl (subprocess) so the proxy settings in
~/.curlrc apply.

Usage: probe.py OUT.tsv DOY[,DOY...] h08v05 h09v05 ...
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import re
import struct
import subprocess
import sys
import zlib

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
SAS = "https://planetarycomputer.microsoft.com/api/sas/v1/token/modiseuwest/modis-061-cogs"
COLLECTION = "modis-15A2H-061"
ASSET = "Fpar_500m"
TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 16: 8}
TYPE_FMT = {1: "B", 3: "H", 4: "I", 8: "h", 9: "i", 12: "d", 16: "Q"}


def curl(args: list[str]) -> bytes:
    return subprocess.run(["curl", "-fsSL", "--retry", "6", "--retry-all-errors", "--retry-delay", "3",
                           "--max-time", "120", *args], check=True, capture_output=True).stdout


def ranged(url: str, start: int, end: int) -> tuple[bytes, dict[str, str]]:
    proc = subprocess.run(["curl", "-fsS", "--retry", "6", "--retry-all-errors", "--retry-delay", "3",
                           "--max-time", "120", "-r", f"{start}-{end}", "-D", "/dev/stderr", "-o", "-", url],
                          check=True, capture_output=True)
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


def main() -> None:
    out_path, doys, tiles = sys.argv[1], [int(x) for x in sys.argv[2].split(",")], sys.argv[3:]
    query = json.loads(curl([SAS]))["token"].lstrip("?")
    rows = []
    for tile in tiles:
        h, v = int(tile[1:3]), int(tile[4:6])
        for doy in doys:
            day = (dt.date(2024, 1, 1) + dt.timedelta(days=doy - 1)).isoformat()
            body = json.dumps({
                "collections": [COLLECTION],
                "datetime": f"{day}T00:00:00Z/{day}T23:59:59Z",
                "query": {"modis:horizontal-tile": {"eq": h}, "modis:vertical-tile": {"eq": v}},
                "limit": 50,
            })
            feats = json.loads(curl(["-H", "Content-Type: application/json", "-X", "POST", "-d", body, STAC]))["features"]
            prefix = f"MOD15A2H.A2024{doy:03d}.h{h:02d}v{v:02d}.061."
            hits = [f for f in feats if f["id"].startswith(prefix)]
            if len(hits) != 1:
                print(f"{tile} doy={doy}: {len(hits)} Terra items ({[f['id'] for f in feats]})", file=sys.stderr)
                continue
            item = hits[0]
            href = item["assets"][ASSET]["href"]
            head, headers = ranged(f"{href}?{query}", 0, 32767)
            total = int(headers["content-range"].rsplit("/", 1)[1])
            md5 = headers.get("x-ms-blob-content-md5", "")
            ifds = parse_ifds(head)
            p = ifds[0]
            struct_ok = (p[256] == [2400] and p[257] == [2400] and p[258] == [8] and p[259] == [8]
                         and p.get(317, [1]) == [1] and p[322] == [512] and p[323] == [512]
                         and p.get(339, [1]) == [1] and p.get(42113) == "255" and len(p[324]) == 25
                         and len(ifds) == 4)
            meta = str(p.get(42112, ""))

            def item_meta(name: str) -> str:
                m = re.search(rf'<Item name="{name}">([^<]*)</Item>', meta)
                return m.group(1) if m else ""

            ov = ifds[-1]
            assert ov[256] == [300] and len(ov[324]) == 1
            ov_off, ov_len = ov[324][0], ov[325][0]
            raw, _ = ranged(f"{href}?{query}", ov_off, ov_off + ov_len - 1)
            px = zlib.decompress(raw)
            vals = bytes(b for r in range(300) for b in px[r * 512:r * 512 + 300])
            hist = [0] * 256
            for b in vals:
                hist[b] += 1
            n = len(vals)
            valid = sum(hist[:101])
            row = {
                "tile": tile, "doy": f"{doy:03d}", "start_date": day, "item_id": item["id"],
                "start_datetime": item["properties"].get("start_datetime", ""),
                "end_datetime": item["properties"].get("end_datetime", ""),
                "href": href, "size": total, "md5_b64": md5,
                "md5_hex": base64.b64decode(md5).hex() if md5 else "",
                "struct_ok": int(struct_ok),
                "qa_good_fpar": item_meta("QAPERCENTGOODFPAR"),
                "qa_main_method": item_meta("QAPERCENTMAINMETHOD"),
                "qa_cloud": item_meta("QAPERCENTCLOUDCOVER.1"),
                "ov_valid_fraction": round(valid / n, 4),
                "ov_between_101_247": round(sum(hist[101:248]) / n, 4),
            }
            for code in range(248, 256):
                row[f"ov_{code}"] = round(hist[code] / n, 4)
            row["ov_valid_distinct"] = sum(1 for x in hist[:101] if x)
            rows.append(row)
            print("\t".join(str(x) for x in row.values()), file=sys.stderr)
    with open(out_path, "w", encoding="utf-8") as fh:
        keys = list(rows[0])
        fh.write("\t".join(keys) + "\n")
        for r in rows:
            fh.write("\t".join(str(r[k]) for k in keys) + "\n")


if __name__ == "__main__":
    main()
