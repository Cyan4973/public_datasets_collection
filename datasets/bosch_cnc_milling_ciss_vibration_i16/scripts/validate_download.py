#!/usr/bin/env python3
"""Semantic check of the downloaded CNC_Machining HDF5 files (metadata only).

For every row of sources.tsv the file must be a supported HDF5 container whose
root group holds exactly one link, ``vibration_data``, a chunked dataset of
the pinned shape ``(rows, 3)`` and pinned container dtype, filtered only by
deflate (optionally shuffle), with a complete chunk grid.  Chunks are not
decompressed here; build.sh and verify.sh decode every value.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cnc_h5  # noqa: E402

DTYPE_TYPECODES = {"float32": "f", "float64": "d", "int64": "q"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--download-dir", type=Path, required=True)
    args = parser.parse_args()
    with args.sources.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    dtype_counts: collections.Counter = collections.Counter()
    filter_counts: collections.Counter = collections.Counter()
    failures: list[str] = []
    for row in rows:
        path = args.download_dir / row["path"]
        buf = path.read_bytes()
        try:
            reader = cnc_h5.Reader(buf)
            root_oh, btree, heap = reader.superblock()
            links = reader.root_links(btree, heap)
            if sorted(links) != ["vibration_data"]:
                raise cnc_h5.H5Error(f"root links {sorted(links)} != ['vibration_data']")
            ds = reader.dataset("vibration_data", links["vibration_data"])
            want_shape = (int(row["rows"]), int(row["cols"]))
            if ds.shape != want_shape or want_shape[1] != 3:
                raise cnc_h5.H5Error(f"shape {ds.shape} != pinned {want_shape}")
            if ds.typecode != DTYPE_TYPECODES[row["container_dtype"]]:
                raise cnc_h5.H5Error(f"typecode {ds.typecode} != pinned {row['container_dtype']}")
            if ds.layout_class != 2 or ds.chunk_shape is None or ds.btree_address is None:
                raise cnc_h5.H5Error("dataset is not chunked")
            ids = [f[0] for f in ds.filters]
            if cnc_h5.FILTER_DEFLATE not in ids:
                raise cnc_h5.H5Error(f"filter pipeline {ids} lacks deflate")
            entries = reader.chunk_entries(ds.btree_address, len(ds.chunk_shape))
            crows, ccols = ds.chunk_shape[0], ds.chunk_shape[1]
            want = {(r, c) for r in range(0, ds.shape[0], crows) for c in range(0, ds.shape[1], ccols)}
            got = [(o[0], o[1]) for _s, _m, o, _a in entries]
            if len(got) != len(set(got)) or set(got) != want:
                raise cnc_h5.H5Error("incomplete or duplicated chunk grid")
        except cnc_h5.H5Error as exc:
            failures.append(f"{row['path']}: {exc}")
            continue
        dtype_counts[row["container_dtype"]] += 1
        filter_counts["+".join(cnc_h5.SUPPORTED_FILTERS[i] for i in ids)] += 1
    if failures:
        for line in failures[:20]:
            print(f"FATAL: {line}", file=sys.stderr)
        raise SystemExit(f"{len(failures)} downloaded files failed HDF5 metadata validation")
    summary = {
        "files": len(rows),
        "container_dtypes": dict(sorted(dtype_counts.items())),
        "filter_pipelines": dict(sorted(filter_counts.items())),
        "total_rows": sum(int(r["rows"]) for r in rows),
        "total_values": sum(int(r["rows"]) * int(r["cols"]) for r in rows),
    }
    (args.download_dir / "download_validation.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("hdf5 metadata ok " + json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
