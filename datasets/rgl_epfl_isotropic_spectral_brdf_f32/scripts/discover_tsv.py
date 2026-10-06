#!/usr/bin/env python3
"""Discovery helper for discover.sh (metadata only; not used by build/verify).

  list  <materials.html>           -> material<TAB>dl_spec URL<TAB>tags
  table <materials.html> <heads/>  -> isotropic materials in materials.tsv layout

`table` keeps every material whose spec tensor has phi_i of length 1
(isotropic); anisotropic files (17 incident azimuths, ~111 MB each) are
dropped. The sha256 column is left empty: it is filled from the realized
download plan after the first full download.
"""
from __future__ import annotations

import html
from pathlib import Path
import re
import struct
import sys

COLUMNS = "material outgoing_resolution size_bytes md5_etag sha256 last_modified spectra_offset pipeline_version tags description".split()


def page_entries(page: Path) -> list[dict]:
    text = page.read_text(encoding="utf-8", errors="replace")
    entries = []
    for chunk in re.split(r"\{\s*id:\s*\d+,", text)[1:]:
        name = re.search(r"name:\s*'([^']*)'", chunk)
        spec = re.search(r"dl_spec:\s*'([^']*)'", chunk)
        tags = re.search(r"tags:\s*'([^']*)'", chunk)
        comments = re.search(r"comments:\s*`([^`]*)`", chunk, re.S)
        if not (name and spec):
            continue
        pipeline = ""
        if comments:
            match = re.search(r"pipeline version:</b>\s*([^<]*)", html.unescape(comments.group(1)))
            pipeline = match.group(1).strip() if match else ""
        entries.append({"material": name.group(1), "url": spec.group(1), "tags": tags.group(1) if tags else "", "pipeline_version": pipeline})
    return entries


def parse_head(buf: bytes) -> dict:
    if buf[:12] != b"tensor_file\x00":
        raise ValueError("not a tensor_file")
    (count,) = struct.unpack_from("<I", buf, 14)
    position = 18
    fields = {}
    for _ in range(count):
        (length,) = struct.unpack_from("<H", buf, position)
        position += 2
        name = buf[position:position + length].decode("ascii")
        position += length
        ndim, dtype, offset = struct.unpack_from("<HBQ", buf, position)
        position += 11
        shape = struct.unpack_from("<" + "Q" * ndim, buf, position)
        position += 8 * ndim
        fields[name] = (dtype, offset, shape)
    return fields


def main() -> int:
    command = sys.argv[1]
    entries = page_entries(Path(sys.argv[2]))
    if command == "list":
        for entry in entries:
            print(f"{entry['material']}\t{entry['url']}\t{entry['tags']}")
        return 0
    heads = Path(sys.argv[3])
    rows = []
    for entry in entries:
        name = entry["material"]
        buf = (heads / f"{name}.bin").read_bytes()
        headers = (heads / f"{name}.headers").read_text(encoding="latin-1")
        total = int(re.search(r"content-range:\s*bytes \d+-\d+/(\d+)", headers, re.I).group(1))
        etag = re.search(r'etag:\s*"([0-9a-f]{32})"', headers, re.I).group(1)
        modified = re.search(r"last-modified:\s*(.+?)\r?$", headers, re.I | re.M).group(1)
        fields = parse_head(buf)
        dtype, offset, shape = fields["spectra"]
        if shape[0] != 1:
            continue
        _, description_offset, description_shape = fields["description"]
        description = buf[description_offset:description_offset + description_shape[0]].decode("utf-8")
        rows.append([name, str(shape[3]), str(total), etag, "", modified, str(offset), entry["pipeline_version"], entry["tags"], description])
    rows.sort()
    print("\t".join(COLUMNS))
    for row in rows:
        print("\t".join(row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
