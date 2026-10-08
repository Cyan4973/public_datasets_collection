#!/usr/bin/env python3
"""Regenerate sources.tsv from a GitHub tree listing plus 2 KB file heads.

Used by discover.sh only (documentation of how the pinned selection was
resolved); download/build/verify never call it.

  discover.py paths  <tree.json>                     -> selected .h5 paths, one per line
  discover.py tsv    <tree.json> <heads_dir> <out>   -> sources.tsv candidate

Head parsing: in these h5py-written files the root local heap's data segment
is immediately followed by the ``vibration_data`` object header (the SNOD that
links it lives near the end of the file, outside the head).  The head parse
reads the dataspace and datatype from that header only to pin the expected
shape and container dtype; download.sh later validates every complete file
through the regular symbol-table path.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cnc_h5  # noqa: E402

MACHINES = ("M01", "M02")
DTYPE_NAMES = {"f": "float32", "d": "float64", "q": "int64"}
HEADER = ["path", "size_bytes", "git_blob_sha1", "machine", "operation", "label",
          "timeframe", "run_index", "rows", "cols", "container_dtype"]


def selected(tree_path: Path) -> list[dict]:
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    if tree.get("truncated"):
        raise SystemExit("tree listing is truncated")
    blobs = [t for t in tree["tree"] if t["type"] == "blob" and t["path"].endswith(".h5")]
    if len(blobs) != 1702:
        raise SystemExit(f"expected 1,702 .h5 blobs at the pinned commit, found {len(blobs)}")
    return sorted((t for t in blobs if t["path"].split("/")[1] in MACHINES), key=lambda t: t["path"])


def head_info(buf: bytes, size: int) -> tuple[tuple[int, ...], str]:
    reader = cnc_h5.Reader(buf)
    head = reader.read(0, 96)
    if head[:8] != cnc_h5.SIGNATURE or struct.unpack_from("<Q", head, 40)[0] != size:
        raise SystemExit("head is not the expected HDF5 superblock")
    heap = struct.unpack_from("<Q", head, 88)[0]
    hh = reader.read(heap, 32)
    if hh[:4] != b"HEAP":
        raise SystemExit("root local heap not found in head")
    data_size, _free, data_addr = struct.unpack_from("<QQQ", hh, 8)
    if b"vibration_data\x00" not in reader.read(data_addr, data_size):
        raise SystemExit("root heap lacks the vibration_data link name")
    ds = reader.dataset("vibration_data", data_addr + data_size)
    return ds.shape, DTYPE_NAMES[ds.typecode]


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "paths":
        for t in selected(Path(sys.argv[2])):
            print(t["path"])
        return 0
    if len(sys.argv) == 5 and sys.argv[1] == "tsv":
        heads = Path(sys.argv[3])
        lines = ["\t".join(HEADER)]
        for t in selected(Path(sys.argv[2])):
            _data, machine, operation, label, name = t["path"].split("/")
            parts = name[:-3].split("_")
            if len(parts) != 5 or parts[0] != machine or parts[3] != operation:
                raise SystemExit(f"unexpected file name {t['path']}")
            buf = (heads / t["path"]).read_bytes()
            shape, dtype = head_info(buf, int(t["size"]))
            if len(shape) != 2 or shape[1] != 3:
                raise SystemExit(f"unexpected shape {shape} in {t['path']}")
            lines.append("\t".join(map(str, [
                t["path"], t["size"], t["sha"], machine, operation, label,
                f"{parts[1]}_{parts[2]}", parts[4], shape[0], shape[1], dtype,
            ])))
        Path(sys.argv[4]).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {len(lines) - 1} rows to {sys.argv[4]}")
        return 0
    raise SystemExit(__doc__)


if __name__ == "__main__":
    raise SystemExit(main())
