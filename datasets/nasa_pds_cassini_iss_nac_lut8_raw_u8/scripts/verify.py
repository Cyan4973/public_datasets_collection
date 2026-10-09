#!/usr/bin/env python3
"""Independent verification for nasa_pds_cassini_iss_nac_lut8_raw_u8.

Does not import coiss.py: it re-parses the volume indexes with csv (multi-item
columns expanded from the label's ITEMS), re-applies the selection rule,
re-reads each VICAR label with its own parser, re-derives every frame, and
byte-compares it with the emitted sample. It applies the same exclusion rule
(mode share > 0.5 or < 16 distinct DN) and checks index rows, counts, totals
and manifest agreement.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from pathlib import Path

DATASET_ID = "nasa_pds_cassini_iss_nac_lut8_raw_u8"
SERIES_ID = "cassini_issna_table8_full_dn_u8"
VOLUMES = ["COISS_2050", "COISS_2051", "COISS_2052"]
FRAME = 1024 * 1024
CAP = 10
INDEX_FIELDS = ("dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
                "element_size_bytes", "sample_size_bytes", "value_count")


def fail(msg: str) -> None:
    raise SystemExit(f"VERIFY FAILED: {msg}")


def label_fields(label: str) -> list[str]:
    names = []
    for block in label.split("OBJECT         = COLUMN")[1:]:
        name = re.search(r"NAME\s*=\s*(\S+)", block).group(1)
        items = re.search(r"ITEMS\s*=\s*(\d+)", block.split("END_OBJECT")[0])
        n = int(items.group(1)) if items else 1
        names += [name] if n == 1 else [f"{name}#{k}" for k in range(n)]
    return names


def csv_index(tab: Path, lbl: Path) -> list[dict]:
    names = label_fields(lbl.read_text(encoding="ascii"))
    rows = []
    for rec in csv.reader(io.StringIO(tab.read_text(encoding="ascii"), newline="")):
        if not rec:
            continue
        if len(rec) != len(names):
            fail(f"{tab.name}: CSV row has {len(rec)} fields, label implies {len(names)}")
        rows.append({k: v.strip() for k, v in zip(names, rec)})
    return rows


def selection(rows: list[dict]) -> list[dict]:
    pool = [r for r in rows if r["INSTRUMENT_ID"] == "ISSNA" and r["DATA_CONVERSION_TYPE"] == "TABLE"
            and r["INSTRUMENT_MODE_ID"] == "FULL" and r["INST_CMPRS_TYPE"] == "LOSSLESS"
            and int(r["MISSING_LINES"]) == 0 and r["MISSING_PACKET_FLAG"] == "NO"
            and r["GAIN_MODE_ID"] == "29 ELECTRONS PER DN" and r["IMAGE_OBSERVATION_TYPE"] == "SCIENCE"
            and r["PRODUCT_TYPE"] == "EDR" and r["TARGET_NAME"] != "SKY" and "SATELLORB" not in r["OBSERVATION_ID"]
            and r["OBSERVATION_ID"] not in ("", "N/A")]
    by_obs: dict[str, list[int]] = {}
    for i, r in enumerate(pool):
        by_obs.setdefault(r["OBSERVATION_ID"], []).append(i)
    chosen = []
    for idx in by_obs.values():
        m = min(len(idx), CAP)
        chosen += [idx[((2 * j + 1) * len(idx)) // (2 * m)] for j in range(m)]
    return [pool[i] for i in sorted(chosen)]


def vicar_int(text: str, key: str) -> int:
    m = re.search(r"(?:^|\s)" + key + r"=\s*(\d+)", text)
    if not m:
        fail(f"VICAR key {key} missing")
    return int(m.group(1))


def vicar_str(text: str, key: str) -> str:
    m = re.search(r"(?:^|\s)" + key + r"='([^']*)'", text)
    return m.group(1) if m else ""


def rederive(raw: bytes, number: str) -> bytes:
    lblsize = vicar_int(raw[:40].decode("ascii"), "LBLSIZE")
    text = raw[:lblsize].decode("ascii", errors="replace")
    for key, val in (("FORMAT", "BYTE"), ("DATA_CONVERSION_TYPE", "TABLE"), ("INSTRUMENT_MODE_ID", "FULL"),
                     ("INSTRUMENT_ID", "ISSNA"), ("INST_CMPRS_TYPE", "LOSSLESS")):
        if vicar_str(text, key) != val:
            fail(f"{number}: VICAR {key} != {val}")
    if str(vicar_int(text, "IMAGE_NUMBER")) != number:
        fail(f"{number}: IMAGE_NUMBER mismatch")
    rec, nl, ns = vicar_int(text, "RECSIZE"), vicar_int(text, "NL"), vicar_int(text, "NS")
    nbb, nlb = vicar_int(text, "NBB"), vicar_int(text, "NLB")
    if nl * ns != FRAME or rec - nbb != ns:
        fail(f"{number}: unexpected geometry NL={nl} NS={ns} RECSIZE={rec} NBB={nbb}")
    base = lblsize + nlb * rec
    if len(raw) != base + nl * rec:
        fail(f"{number}: file size disagrees with VICAR layout")
    if any(raw[base + i * rec] * 256 + raw[base + i * rec + 1] != i + 1 for i in range(nl)):
        fail(f"{number}: line prefixes do not start with the 1-based line number")
    out = b"".join(raw[base + i * rec + nbb:base + (i + 1) * rec] for i in range(nl))
    if len(out) != FRAME:
        fail(f"{number}: re-derived {len(out)} bytes")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--recipe-dir", type=Path, required=True)
    a = ap.parse_args()
    dl = a.data_dir / "downloads" / DATASET_ID

    rows = []
    for vol in VOLUMES:
        vrows = csv_index(dl / "index" / f"{vol}_index.tab", dl / "index" / f"{vol}_index.lbl")
        if any(r["VOLUME_ID"] != vol for r in vrows):
            fail(f"{vol}: VOLUME_ID mismatch in index")
        rows += vrows
    chosen = selection(rows)
    src_lines = (a.recipe_dir / "sources.tsv").read_text(encoding="utf-8").splitlines()
    head = src_lines[0].split("\t")
    sources = [dict(zip(head, ln.split("\t"))) for ln in src_lines[1:] if ln]
    if [(r["VOLUME_ID"], r["FILE_SPECIFICATION_NAME"], r["IMAGE_NUMBER"]) for r in chosen] != \
            [(s["volume"], s["file_specification_name"], s["image_number"]) for s in sources]:
        fail("CSV-parsed selection differs from sources.tsv")
    print(f"selection_ok index_rows={len(rows)} selected={len(chosen)}")

    index_path = a.data_dir / "index" / DATASET_ID / "samples.jsonl"
    entries = [json.loads(ln) for ln in index_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    by_path = {e["sample_path"]: e for e in entries}
    if len(by_path) != len(entries):
        fail("duplicate sample_path in index")

    expected_paths = []
    excluded = 0
    hist = [0] * 256
    hashes = set()
    for s in sources:
        raw = (dl / "raw" / f"{s['volume']}_{s['product']}.IMG").read_bytes()
        if hashlib.md5(raw).hexdigest() != s["img_md5"]:
            fail(f"{s['product']}: MD5 differs from pin")
        px = rederive(raw, s["image_number"])
        counts = [0] * 256
        for v in px:
            counts[v] += 1
        distinct = sum(1 for c in counts if c)
        if max(counts) / FRAME > 0.5 or distinct < 16:
            excluded += 1
            continue
        rel = f"samples/{DATASET_ID}/{SERIES_ID}/{s['product']}.u8"
        expected_paths.append(rel)
        sample = (a.data_dir / rel).read_bytes() if (a.data_dir / rel).is_file() else None
        if sample != px:
            fail(f"{rel}: emitted bytes differ from independent re-derivation")
        digest = hashlib.sha256(px).hexdigest()
        if digest in hashes:
            fail(f"{rel}: duplicate frame")
        hashes.add(digest)
        e = by_path.get(rel)
        if e is None:
            fail(f"{rel}: missing from samples.jsonl")
        want = {"dataset_id": DATASET_ID, "series_id": SERIES_ID, "sample_path": rel, "numeric_kind": "uint",
                "bit_width": 8, "endianness": "little", "element_size_bytes": 1, "sample_size_bytes": FRAME,
                "value_count": FRAME}
        for k in INDEX_FIELDS:
            if e.get(k) != want[k]:
                fail(f"{rel}: index field {k}={e.get(k)!r}, expected {want[k]!r}")
        if e.get("sha256") != digest or e.get("minimum") != min(px) or e.get("maximum") != max(px):
            fail(f"{rel}: index sha256/min/max disagree")
        if e["minimum"] == e["maximum"]:
            fail(f"{rel}: constant frame")
        for v in range(256):
            hist[v] += counts[v]

    if sorted(expected_paths) != sorted(by_path):
        fail(f"index has {len(by_path)} rows, re-derivation expects {len(expected_paths)}")
    on_disk = sorted(str(p.relative_to(a.data_dir)) for p in
                     (a.data_dir / "samples" / DATASET_ID / SERIES_ID).iterdir())
    if on_disk != sorted(expected_paths):
        fail("sample directory contents differ from expected sample set")
    total_px = sum(hist)
    levels = sum(1 for c in hist if c)
    if levels < 200 or max(hist) / total_px > 0.5:
        fail(f"aggregate histogram degenerate (levels={levels}, max share={max(hist) / total_px:.3f})")
    n = len(expected_paths)
    total = n * FRAME
    if n < 20 or total < 100_000:
        fail(f"below floor: samples={n} bytes={total}")

    manifest = (a.recipe_dir / "manifest.toml").read_text(encoding="utf-8")
    m_count = re.search(r"^sample_count\s*=\s*(\d+)", manifest, re.M)
    m_total = re.search(r"^total_size_bytes\s*=\s*(\d+)", manifest, re.M)
    if not m_count or int(m_count.group(1)) != n or not m_total or int(m_total.group(1)) != total:
        fail(f"manifest sample_count/total_size_bytes disagree with realized {n} / {total}")
    print(f"verify summary samples={n} excluded={excluded} bytes={total} dn_levels={levels} "
          f"max_dn_share={max(hist) / total_px:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
