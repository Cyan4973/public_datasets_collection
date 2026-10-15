#!/usr/bin/env python3
"""Regenerate selected_files.tsv (documentation of how the pinned ranges were resolved).

Not part of download/build. Network I/O goes through curl. For each focal group of the pinned
revision, picks PER_GROUP scenes evenly spaced through the lexicographically sorted file list
(index floor((i + 0.5) * n / PER_GROUP)), then reads ~8 KB per file with two range requests
(archive head and tail) to pin the central-directory offset, the head range, the target storage
member range, and the member CRC-32s.

Usage: python3 discover.py <work_dir> > selected_files.tsv
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import anycam_latents as al  # noqa: E402

BASE = f"https://huggingface.co/datasets/{al.CACHE_REPO}"
PROBE = 8192


def curl(url: str, byte_range: str | None = None) -> bytes:
    cmd = ["curl", "-fsSL", "--retry", "5", "--max-time", "120"]
    if byte_range:
        cmd += ["-r", byte_range]
    return subprocess.run(cmd + [url], check=True, capture_output=True).stdout


def main() -> None:
    work = Path(sys.argv[1])
    work.mkdir(parents=True, exist_ok=True)
    info = json.loads(curl(f"https://huggingface.co/api/datasets/{al.CACHE_REPO}/revision/{al.CACHE_REVISION}?blobs=true"))
    if info["sha"] != al.CACHE_REVISION:
        raise SystemExit("revision mismatch")
    files = {s["rfilename"]: s for s in info["siblings"] if s["rfilename"].endswith(".pt")}
    print(al.SELECTION_HEADER)
    for group in al.FOCAL_GROUPS:
        names = sorted(n for n in files if n.startswith(f"mcv_{group}_"))
        picks = [names[((2 * i + 1) * len(names)) // (2 * al.PER_GROUP)] for i in range(al.PER_GROUP)]
        for name in picks:
            scene = name[: -len(".pt")]
            size = files[name]["lfs"]["size"]
            sha = files[name]["lfs"]["sha256"]
            url = f"{BASE}/resolve/{al.CACHE_REVISION}/{name}"
            tail_start = size - PROBE
            tail = curl(url, f"{tail_start}-{size - 1}")
            cd = al.central_directory(tail, tail_start, size)
            members = cd["entries"]
            tail = tail[cd["cd_start"] - tail_start :]
            prefix = f"{scene}.pt/"
            head_stop = min(m["lho"] for n, m in members.items() if n.startswith(prefix + "data/"))
            head = curl(url, f"0-{head_stop - 1}")
            if len(head) != head_stop:
                raise SystemExit(f"{scene}: short head read")
            pkl_entry = members[prefix + "data.pkl"]
            tensor, _meta = al.parse_record(al.member_bytes(head, 0, pkl_entry, prefix + "data.pkl"), scene)
            target = members[prefix + "data/" + tensor.storage.key]
            target_stop = min(m["lho"] for m in members.values() if m["lho"] > target["lho"])
            print(
                f"{scene}\t{size}\t{sha}\t{cd['cd_start']}\t{head_stop}\t{tensor.storage.key}\t"
                f"{target['lho']}\t{target_stop}\t{target['crc32']:08x}\t{pkl_entry['crc32']:08x}",
                flush=True,
            )
            (work / f"{scene}.head").write_bytes(head)
            (work / f"{scene}.tail").write_bytes(tail)


if __name__ == "__main__":
    main()
