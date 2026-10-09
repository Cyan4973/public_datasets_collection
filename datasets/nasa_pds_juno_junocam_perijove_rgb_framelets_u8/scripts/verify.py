#!/usr/bin/env python3
"""Independent verification for the JunoCam perijove lossless colour EDR recipe.

Does not import junocam.py: re-implements the INDEX.TAB splitter, the PDS3 keyword
lookup, the candidate/selection rule and the exclusion rule, then byte-compares
every emitted sample with its source IMG and checks the index and manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path

DATASET_ID = "nasa_pds_juno_junocam_perijove_rgb_framelets_u8"
SERIES_ID = "junocam_perijove_rgb_lossless_dn_u8"
WIDTH = 1648


def fail(message: str) -> None:
    print(f"VERIFY FAIL {message}", file=sys.stderr)
    raise SystemExit(1)


def split_row(line: str) -> list[str]:
    """Quote-aware comma split for one INDEX.TAB record (no csv module)."""
    fields, buf, quoted = [], [], False
    for ch in line.rstrip("\r\n"):
        if ch == '"':
            quoted = not quoted
        elif ch == "," and not quoted:
            fields.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    fields.append("".join(buf).strip())
    return fields


def keyword(text: str, name: str, start: int = 0) -> str | None:
    match = re.compile(r"^\s*" + re.escape(name) + r"\s*=\s*(.+?)\s*$", re.M).search(text, start)
    return match.group(1).strip().strip('"') if match else None


def rationale_of(text: str) -> str:
    match = re.search(r'^\s*RATIONALE_DESC\s*=\s*"(.*?)"', text, re.M | re.S)
    return " ".join(match.group(1).split()) if match else ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--recipe-dir", type=Path, required=True)
    args = parser.parse_args()
    root, recipe = args.data_dir, args.recipe_dir
    dl = root / "downloads" / DATASET_ID

    def tsv(name: str) -> list[dict]:
        lines = (recipe / name).read_text(encoding="utf-8").splitlines()
        head = lines[0].split("\t")
        return [dict(zip(head, ln.split("\t"))) for ln in lines[1:] if ln.strip()]

    volumes, pinned_cands, sources = tsv("volumes.tsv"), tsv("candidates.tsv"), tsv("sources.tsv")
    if len(volumes) != 35:
        fail(f"volumes.tsv has {len(volumes)} rows")

    # 1. Index tables: pinned MD5, then highest version of every EDR product id.
    best: dict[str, tuple] = {}
    for vol in volumes:
        path = dl / "index" / f"{vol['volume']}_INDEX.TAB"
        raw = path.read_bytes()
        if hashlib.md5(raw).hexdigest() != vol["index_md5"]:
            fail(f"{path.name} MD5 differs from volumes.tsv")
        for line in raw.decode("latin-1").splitlines():
            f = split_row(line)
            if len(f) != 16:
                fail(f"{path.name}: {len(f)} columns")
            if f[1] != "JUNOCAM-EDR":
                continue
            m = re.fullmatch(r"(JNCE_\d{7}_(\d\d)([A-Z])\d{5})_V(\d\d)", f[3])
            if not m:
                fail(f"bad product id {f[3]}")
            rank = (int(m.group(4)), vol["volume"])
            if m.group(1) not in best or rank > best[m.group(1)][0]:
                best[m.group(1)] = (rank, f, int(m.group(2)), m.group(3))
    derived = []
    for base, (rank, f, orbit, ptype) in best.items():
        if ptype != "C" or f[12] != "JUPITER" or not f[13].startswith("DATA/EDR/JUPITER/") or orbit == 0 or orbit % 3:
            continue
        rat = " ".join(f[7].split())
        m = re.search(r"PJ(\d+)([+-])(\d{3})T(\d\d):(\d\d)", rat)
        if not m or int(m.group(1)) != orbit or re.search(r"invalid|partial", rat, re.I):
            continue
        minutes = int(m.group(3)) * 1440 + int(m.group(4)) * 60 + int(m.group(5))
        if minutes > 60:
            continue
        derived.append((f[3], rank[1], str(orbit), str(-minutes if m.group(2) == "-" else minutes), f[15].lower()))
    derived.sort(key=lambda t: (int(t[2]), t[0]))
    if derived != [(c["product_id"], c["volume"], c["orbit"], c["rel_minutes"], c["label_md5"]) for c in pinned_cands]:
        fail("independently re-derived candidate list differs from candidates.tsv")

    # 2. Labels: MD5 from the index, then per perijove the HUFFMAN product closest to perijove.
    pick: dict[int, tuple] = {}
    for pid, _vol, orbit, rel, md5 in derived:
        raw = (dl / "labels" / f"{pid}.LBL").read_bytes()
        if hashlib.md5(raw).hexdigest() != md5:
            fail(f"label MD5 mismatch {pid}")
        text = raw.decode("latin-1")
        if keyword(text, "COMPRESSION_TYPE") != "HUFFMAN" or re.search(r"invalid|partial", rationale_of(text), re.I):
            continue
        rank = (abs(int(rel)), pid)
        if int(orbit) not in pick or rank < pick[int(orbit)][0]:
            pick[int(orbit)] = (rank, pid)
    if [pick[o][1] for o in sorted(pick)] != [s["product_id"] for s in sources]:
        fail("independently re-derived selection differs from sources.tsv")

    # 3. Images, exclusion rule, samples.
    index_rows = [json.loads(ln) for ln in (root / "index" / DATASET_ID / "samples.jsonl").read_text().splitlines() if ln.strip()]
    by_pid = {row["product_id"]: row for row in index_rows}
    if len(by_pid) != len(index_rows):
        fail("duplicate product rows in index")
    histogram = [0] * 256
    emitted = total = 0
    for src in sources:
        pid = src["product_id"]
        text = (dl / "labels" / f"{pid}.LBL").read_text(encoding="latin-1")
        obj = re.search(r"^\s*OBJECT\s*=\s*IMAGE\s*$", text, re.M)
        if not obj:
            fail(f"{pid}: no IMAGE object in label")
        img_at = obj.start()
        checks = {
            "TARGET_NAME": "JUPITER", "SAMPLE_BIT_MODE_ID": "SQROOT", "SAMPLING_FACTOR": "1", "RECORD_BYTES": "1648",
            "INSTRUMENT_ID": "JNC", "ORBIT_NUMBER": src["orbit"], "PRODUCT_ID": pid,
        }
        for name, want in checks.items():
            if keyword(text, name) != want:
                fail(f"{pid}: {name}={keyword(text, name)!r}")
        if keyword(text, "FILTER_NAME") != "('BLUE', 'GREEN', 'RED')":
            fail(f"{pid}: FILTER_NAME {keyword(text, 'FILTER_NAME')}")
        lines = int(keyword(text, "LINES", img_at))
        for name, want in {"LINE_SAMPLES": "1648", "SAMPLE_BITS": "8", "SAMPLE_TYPE": "UNSIGNED_INTEGER",
                           "LINE_PREFIX_BYTES": "0", "LINE_SUFFIX_BYTES": "0"}.items():
            if keyword(text, name, img_at) != want:
                fail(f"{pid}: IMAGE {name}={keyword(text, name, img_at)!r}")
        if lines % 384:
            fail(f"{pid}: LINES {lines} not a multiple of 3 x 128")
        data = (dl / "img" / f"{pid}.IMG").read_bytes()
        if len(data) != lines * WIDTH or hashlib.md5(data).hexdigest() != src["img_md5"]:
            fail(f"{pid}: IMG size/MD5 mismatch")
        counts = [0] * 256
        for value in range(256):
            counts[value] = data.count(bytes([value]))
        zero_line = bytes(WIDTH)
        zero_lines = sum(1 for i in range(0, len(data), WIDTH) if data[i:i + WIDTH] == zero_line)
        mode_share = max(counts) / len(data)
        distinct = sum(1 for c in counts if c)
        drop = zero_lines / lines > 0.02 or mode_share > 0.50 or distinct < 32
        row = by_pid.get(pid)
        if drop:
            if row is not None:
                fail(f"{pid}: should have been excluded (zero_lines={zero_lines}, mode_share={mode_share:.3f}, distinct={distinct})")
            print(f"excluded_ok product={pid}")
            continue
        if row is None:
            fail(f"{pid}: missing from index")
        sample = root / row["sample_path"]
        if row["sample_path"] != f"samples/{DATASET_ID}/{SERIES_ID}/{pid}.u8":
            fail(f"{pid}: unexpected sample_path {row['sample_path']}")
        if sample.read_bytes() != data:
            fail(f"{pid}: sample bytes differ from IMAGE raster")
        expect = {"dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "uint", "bit_width": 8,
                  "endianness": "little", "element_size_bytes": 1, "sample_size_bytes": len(data), "value_count": len(data),
                  "shape": [lines, WIDTH], "zero_lines": zero_lines, "distinct": distinct,
                  "min": min(v for v in range(256) if counts[v]), "max": max(v for v in range(256) if counts[v])}
        for key, want in expect.items():
            if row.get(key) != want:
                fail(f"{pid}: index {key}={row.get(key)!r} want {want!r}")
        if distinct < 2:
            fail(f"{pid}: constant sample")
        for v in range(256):
            histogram[v] += counts[v]
        emitted += 1
        total += len(data)
        print(f"sample_ok product={pid} lines={lines} zero_lines={zero_lines} mode_share={mode_share:.3f} distinct={distinct}")
    if emitted != len(index_rows):
        fail(f"index has {len(index_rows)} rows, verified {emitted}")
    stray = {p.name for p in (root / "samples" / DATASET_ID / SERIES_ID).iterdir()} - {f"{pid}.u8" for pid in by_pid}
    if stray:
        fail(f"stray sample files {sorted(stray)[:5]}")
    levels = sum(1 for c in histogram if c)
    if levels < 200 or max(histogram) > total / 2:
        fail(f"degenerate aggregate histogram levels={levels} max_share={max(histogram) / total:.3f}")
    if len({src['orbit'] for src in sources if src['product_id'] in by_pid}) < 8:
        fail("fewer than 8 perijoves realized")

    manifest = tomllib.loads((recipe / "manifest.toml").read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID][0]
    if series["sample_count"] != emitted or series["total_size_bytes"] != total:
        fail(f"manifest sample_count/total_size_bytes {series['sample_count']}/{series['total_size_bytes']} != realized {emitted}/{total}")
    print(f"verify summary samples={emitted} total_bytes={total} levels={levels} perijoves={sorted(int(r['orbit']) for r in index_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
