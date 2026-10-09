#!/usr/bin/env python3
"""Semantic validation of one downloaded normal_cam HDF5 member (download.sh).

  write <member.hdf5> <sidecar.json> <member_name> <zip_size> <zip_url>
        <cd_offset> <cd_size> <cd_entries> <local_header_offset> <size> <crc32>
      Fully decodes the member (every chunk) and requires the root group to
      hold exactly `dataset` = IEEE float16, little-endian, shape
      (768, 1024, 3); then writes the sidecar with provenance + sha256.

  check <member.hdf5> <sidecar.json> <member_name> <zip_size>
      Re-run fast path: exit 0 only if the sidecar matches the pins and the
      file's size and sha256 match the sidecar.
"""
from __future__ import annotations

import hashlib
import json
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hypersim_h5  # noqa: E402

SHAPE = (768, 1024, 3)


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "check" and len(argv) == 6:
        member, sidecar, name, zsize = Path(argv[2]), Path(argv[3]), argv[4], int(argv[5])
        try:
            meta = json.loads(sidecar.read_text())
        except (OSError, ValueError):
            return 1
        data = member.read_bytes()
        ok = (meta.get("member_name") == name and meta.get("zip_size_bytes") == zsize
              and meta.get("member_size_bytes") == len(data)
              and meta.get("member_sha256") == hashlib.sha256(data).hexdigest())
        return 0 if ok else 1
    if len(argv) >= 2 and argv[1] == "write" and len(argv) == 13:
        member, sidecar, name = Path(argv[2]), Path(argv[3]), argv[4]
        zsize, url = int(argv[5]), argv[6]
        cd_off, cd_size, n_entries, loc_off, size, crc = (int(v) for v in argv[7:13])
        data = member.read_bytes()
        if len(data) != size or (zlib.crc32(data) & 0xFFFFFFFF) != crc:
            print(f"FATAL: {name}: size/CRC differ from the central directory", file=sys.stderr)
            return 1
        try:
            dec = hypersim_h5.decode_file(data, "dataset")
        except hypersim_h5.H5Error as exc:
            print(f"FATAL: {name}: HDF5 decode failed: {exc}", file=sys.stderr)
            return 1
        ds = dec.dataset
        if dec.root_links != ["dataset"] or ds.shape != SHAPE or ds.typecode != "e":
            print(f"FATAL: {name}: links={dec.root_links} shape={ds.shape} type={ds.typecode}; "
                  f"want ['dataset'] {SHAPE} float16", file=sys.stderr)
            return 1
        meta = {
            "member_name": name,
            "zip_url": url,
            "zip_size_bytes": zsize,
            "central_directory_offset": cd_off,
            "central_directory_size": cd_size,
            "central_directory_entries": n_entries,
            "local_header_offset": loc_off,
            "member_size_bytes": size,
            "member_crc32": f"{crc:08x}",
            "member_sha256": hashlib.sha256(data).hexdigest(),
            "hdf5_shape": list(ds.shape),
            "hdf5_chunk_shape": list(ds.chunk_shape or ()),
            "hdf5_filters": [[f[0], list(f[2])] for f in ds.filters],
            "hdf5_chunks": dec.chunk_count,
        }
        sidecar.write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
