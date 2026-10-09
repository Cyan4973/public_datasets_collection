#!/usr/bin/env python3
"""Helpers for discover.sh (documentation of how sources.tsv was resolved).

    listing  --html F                   -> "name<TAB>bytes" for every lolardr_*.dat, sorted by name
    order    --count N                  -> candidate positions in bisection order n/2, n/4, 3n/4, n/8, ...
    probe-config --url U --bytes B --chunks C --records R --out DIR
                                        -> curl -K config fetching C evenly spaced R-record chunks
    probe-stats --dir DIR --chunks C    -> kept-spot fraction over the probe chunks
    md5      --manifest F --path P      -> MD5 (lower case) of volume path P from the volume MD5 list
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lola_rdr  # noqa: E402


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("listing")
    p.add_argument("--html", type=Path, required=True)
    p = sub.add_parser("order")
    p.add_argument("--count", type=int, required=True)
    p = sub.add_parser("probe-config")
    p.add_argument("--url", required=True)
    p.add_argument("--bytes", type=int, required=True)
    p.add_argument("--chunks", type=int, required=True)
    p.add_argument("--records", type=int, required=True)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("probe-stats")
    p.add_argument("--dir", type=Path, required=True)
    p.add_argument("--chunks", type=int, required=True)
    p = sub.add_parser("md5")
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--path", required=True)
    args = ap.parse_args(argv)

    if args.cmd == "listing":
        text = args.html.read_text(encoding="utf-8", errors="replace").replace("<br>", "\n")
        rows = {}
        for line in text.splitlines():
            m = re.search(r"\s(\d+)\s+<A HREF=\"[^\"]*/(lolardr_\d{9}\.dat)\">", line, re.IGNORECASE)
            if m:
                rows[m.group(2).lower()] = int(m.group(1))
        for name in sorted(rows):
            print(f"{name}\t{rows[name]}")
    elif args.cmd == "order":
        # Bisection (van der Corput) order over the sorted orbit list:
        # n/2, n/4, 3n/4, n/8, 3n/8, 5n/8, 7n/8, ... (deduplicated), so that
        # successive candidates come from different days of the phase.
        n = args.count
        seq: list[int] = []
        seen: set[int] = set()
        den = 2
        while len(seq) < n and den <= 4 * n:
            for num in range(1, den, 2):
                pos = n * num // den
                if pos not in seen:
                    seen.add(pos)
                    seq.append(pos)
            den *= 2
        seq += [i for i in range(n) if i not in seen]
        print(" ".join(str(i) for i in seq))
    elif args.cmd == "probe-config":
        records = args.bytes // lola_rdr.RECORD_BYTES
        args.out.mkdir(parents=True, exist_ok=True)
        for c in range(args.chunks):
            start_rec = (records - args.records) * c // max(1, args.chunks - 1)
            start = start_rec * lola_rdr.RECORD_BYTES
            end = start + args.records * lola_rdr.RECORD_BYTES - 1
            print(f'url = "{args.url}"\nrange = "{start}-{end}"\noutput = "{args.out}/chunk_{c:03d}.bin"')
            if c != args.chunks - 1:
                print("next")
    elif args.cmd == "probe-stats":
        kept = spots = 0
        for c in range(args.chunks):
            data = (args.dir / f"chunk_{c:03d}.bin").read_bytes()
            r = lola_rdr.extract(data)
            kept += r["counts"]["kept"]
            spots += r["spots"]
        print(f"{kept / spots:.4f}" if spots else "0")
    elif args.cmd == "md5":
        want = args.path.replace("/", "\\").lower()
        with args.manifest.open("r", encoding="ascii", errors="replace") as fh:
            for line in fh:
                parts = line.strip().split(None, 1)
                if len(parts) == 2 and parts[1].lower() == want:
                    print(parts[0].lower())
                    return 0
        raise SystemExit(f"{args.path} not in {args.manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
