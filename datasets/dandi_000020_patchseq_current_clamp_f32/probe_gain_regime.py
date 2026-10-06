#!/usr/bin/env python3
"""Discovery aid (not part of download/build): survey the CurrentClampSeries gain
of selected donors with small HTTP range reads, to locate the gain-0.05 window.

Usage:
  python3 probe_gain_regime.py --assets-yaml <assets.yaml> DONOR_ID [DONOR_ID ...]

For each donor it opens the lexicographically first NWB asset over curl range
requests (16 KiB blocks, metadata only; never dereferences the HDF5 undefined
address and refuses reads above 512 KiB), lists /acquisition, counts series by
neurodata_type, reads every CurrentClampSeries `gain` scalar, and reports the
bytes fetched. It ran on 2026-10-05 (see README "Gain regime survey").
"""
from __future__ import annotations

import argparse
import collections
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
import nwb_hdf5 as H5  # noqa: E402
import patchseq_cc as P  # noqa: E402

BLOCK = 16_384
MAX_READ = 32 * BLOCK


class RangeBuffer:
    def __init__(self, url: str, size: int) -> None:
        self.url = url
        self.size = size
        self.blocks: dict[int, bytes] = {}
        self.fetched = 0

    def __len__(self) -> int:
        return self.size

    def _block(self, index: int) -> bytes:
        if index not in self.blocks:
            start = index * BLOCK
            end = min(self.size, start + BLOCK) - 1
            if start < 0 or start >= self.size:
                raise H5.H5Error("range outside file")
            data = subprocess.run(
                ["curl", "-sS", "-fL", "--max-time", "60", "-r", f"{start}-{end}", self.url],
                capture_output=True,
                check=True,
            ).stdout
            if len(data) != end - start + 1:
                raise H5.H5Error(f"short range response for {start}-{end}")
            self.blocks[index] = data
            self.fetched += len(data)
        return self.blocks[index]

    def __getitem__(self, key):
        if isinstance(key, int):
            if key < 0 or key >= self.size:
                raise IndexError(key)
            return self._block(key // BLOCK)[key % BLOCK]
        start = key.start or 0
        stop = self.size if key.stop is None else min(key.stop, self.size)
        if stop - start > MAX_READ:
            raise H5.H5Error(f"refusing {stop - start}-byte read in metadata probe")
        parts = []
        pos = start
        while pos < stop:
            block = self._block(pos // BLOCK)
            offset = pos % BLOCK
            take = min(stop - pos, BLOCK - offset)
            parts.append(block[offset : offset + take])
            pos += take
        return b"".join(parts)

    def find(self, sub: bytes, start: int, end: int) -> int:
        data = self[start : min(end, start + 4096)]
        at = data.find(sub)
        return -1 if at < 0 else start + at


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets-yaml", type=Path, required=True)
    parser.add_argument("donors", nargs="+", type=int)
    args = parser.parse_args()
    by_subject: dict[int, list[dict[str, object]]] = {}
    for asset in P.parse_assets_yaml(args.assets_yaml):
        by_subject.setdefault(int(str(asset["path"]).split("/")[0][4:]), []).append(asset)
    for donor in args.donors:
        asset = sorted(by_subject[donor], key=lambda a: str(a["path"]))[0]
        buf = RangeBuffer(str(asset["urls"][0]), int(asset["size"]))
        h5 = H5.H5File(buf)
        acquisition = h5.links(h5.links(h5.root_header)["acquisition"][1])
        types: collections.Counter = collections.Counter()
        gains: collections.Counter = collections.Counter()
        for name in sorted(acquisition):
            kind, addr = acquisition[name]
            if kind != "hard":
                continue
            neurodata_type = h5.attributes(addr).get("neurodata_type")
            types[neurodata_type] += 1
            if neurodata_type == "CurrentClampSeries":
                gain_bytes, _ = h5.read_1d(h5.dataset_info(h5.links(addr)["gain"][1]))
                gains[round(struct.unpack("<f", gain_bytes)[0], 6)] += 1
        print(
            f"donor={donor} asset={asset['path']} bytes={asset['size']} types={dict(types)} "
            f"cc_gains={dict(gains)} fetched={buf.fetched}",
            flush=True,
        )


if __name__ == "__main__":
    main()
