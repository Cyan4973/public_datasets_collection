#!/usr/bin/env python3
"""TUM-VIE left-camera event-window helper (planner, validator, builder).

Never touches the network: download.sh / discover.sh fetch byte ranges with
curl, this helper only parses what is cached under
``downloads/<id>/<seq>/meta/`` (metadata ranges) and ``.../data/`` (chunk spans).

Subcommands
  check-license  normalise the dataset HTML page and require the CC BY 4.0 sentence
  plan           resolve superblock -> groups -> events/x, events/y -> chunk B-trees for
                 the pinned window; print "NEED <offset> <length>" for the next missing
                 metadata range, or write plan.json and print "DONE"
  discover-row   print the sequences.tsv row for a resolved plan (used by discover.sh)
  check-plan     compare plan.json with the pinned sequences.tsv row
  spans          print coalesced chunk byte spans "<offset> <length>" to fetch
  check-headers  validate a curl header dump (206, Content-Range, ETag)
  check-seq      decode every window chunk of one sequence and validate it
  build          decode all sequences, write samples, index and ingest stats
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tumvie_h5 as T  # noqa: E402

DATASET_ID = "tumvie_prophesee_gen4_events_xy_u16"
BASE_URL = "https://tumevent-vi.vision.in.tum.de"
SERIES = {"x": "tumvie_left_event_x_u16", "y": "tumvie_left_event_y_u16"}
LIMITS = {"x": 1279, "y": 719}  # Prophesee Gen4 CD sensor: 1280 x 720
SPAN_GAP = 65536  # coalesce chunks whose file gap is at most this many bytes
LICENSE_SENTENCE = ("All data in the TUM-VIE Dataset is licensed under a Creative Commons 4.0 "
                    "Attribution License (CC BY 4.0)")
SEQ_COLUMNS = ["sequence", "file_size", "etag", "last_modified", "n_events", "window_start_chunk",
               "x_stored_bytes", "y_stored_bytes", "x_table_sha256", "y_table_sha256"]


def die(msg: str) -> None:
    print(f"FATAL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def seq_url(seq: str) -> str:
    return f"{BASE_URL}/{seq}/{seq}-events_left.h5"


def load_sequences(recipe_dir: Path) -> list[dict]:
    rows = []
    with open(recipe_dir / "sequences.tsv", encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        if header != SEQ_COLUMNS:
            die(f"sequences.tsv header {header} != {SEQ_COLUMNS}")
        for line in fh:
            if not line.strip():
                continue
            vals = line.rstrip("\n").split("\t")
            row = dict(zip(header, vals))
            for k in ("file_size", "n_events", "window_start_chunk", "x_stored_bytes", "y_stored_bytes"):
                row[k] = int(row[k])
            rows.append(row)
    if len(rows) != 21 or len({r["sequence"] for r in rows}) != 21:
        die(f"sequences.tsv must list 21 distinct sequences, found {len(rows)}")
    return rows


def seq_row(recipe_dir: Path, seq: str) -> dict:
    for r in load_sequences(recipe_dir):
        if r["sequence"] == seq:
            return r
    die(f"sequence {seq} not pinned in sequences.tsv")
    return {}


def seq_dir(data_root: Path, seq: str) -> Path:
    return data_root / "downloads" / DATASET_ID / seq


def table_sha(refs: list[list[int]]) -> str:
    text = "".join(f"{i}\t{a}\t{s}\n" for i, a, s in refs)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


# --------------------------------------------------------------------------- license
def cmd_check_license(args: argparse.Namespace) -> None:
    raw = Path(args.page).read_text(encoding="utf-8", errors="replace")
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    text = re.sub(r"\s+", " ", text)
    if LICENSE_SENTENCE not in text:
        die("TUM-VIE license sentence (CC BY 4.0) not found on the dataset page")
    for seq in [r["sequence"] for r in load_sequences(Path(args.recipe_dir))]:
        if seq_url(seq) not in raw:
            die(f"dataset page no longer links {seq_url(seq)}")
    print(f"license_ok '{LICENSE_SENTENCE}' and all 21 left-event URLs linked")


# --------------------------------------------------------------------------- plan
def resolve_plan(meta_dir: Path, file_size: int) -> dict:
    seg = T.Segments(file_size, str(meta_dir))
    ef = T.parse_event_file(seg)  # raises NeedBytes
    n_events = ef.datasets["x"].shape[0]
    start = T.window_start(n_events)
    plan = {
        "file_size": file_size,
        "n_events": n_events,
        "window_start_chunk": start,
        "window_chunks": T.WINDOW_CHUNKS,
        "event_index_start": start * T.CHUNK_ELEMS,
        "event_index_end": (start + T.WINDOW_CHUNKS) * T.CHUNK_ELEMS,
        "ms_to_idx_length": ef.ms_to_idx.shape[0],
        "datasets": {},
    }
    for k in ("x", "y"):
        ds = ef.datasets[k]
        refs = T.chunk_refs(seg, ds, start, T.WINDOW_CHUNKS)
        table = [[r.index, r.address, r.size] for r in refs]
        plan["datasets"][k] = {
            "object_header": ds.object_header,
            "btree_address": ds.btree_address,
            "blosc_cd_values": list(ds.filters[0][1]),
            "chunks": table,
            "stored_bytes": sum(r.size for r in refs),
            "table_sha256": table_sha(table),
        }
    return plan


def cmd_plan(args: argparse.Namespace) -> None:
    data_root, seq = Path(args.data_root), args.seq
    if args.size is not None:
        file_size = args.size
    else:
        file_size = seq_row(Path(args.recipe_dir), seq)["file_size"]
    meta = seq_dir(data_root, seq) / "meta" if args.cache is None else Path(args.cache)
    meta.mkdir(parents=True, exist_ok=True)
    try:
        plan = resolve_plan(meta, file_size)
    except T.NeedBytes as need:
        off, length = T.fetch_window(need, file_size)
        print(f"NEED {off} {length}")
        return
    except T.LayoutError as exc:
        die(f"{seq}: {exc}")
    plan["sequence"] = seq
    out = meta.parent / "plan.json"
    out.write_text(json.dumps(plan, indent=1) + "\n", encoding="utf-8")
    print("DONE")


def load_plan(data_root: Path, seq: str) -> dict:
    p = seq_dir(data_root, seq) / "plan.json"
    if not p.is_file():
        die(f"{seq}: plan.json missing; run download.sh")
    return json.loads(p.read_text(encoding="utf-8"))


def cmd_discover_row(args: argparse.Namespace) -> None:
    plan = load_plan(Path(args.data_root), args.seq)
    vals = [args.seq, plan["file_size"], args.etag, args.last_modified, plan["n_events"], plan["window_start_chunk"],
            plan["datasets"]["x"]["stored_bytes"], plan["datasets"]["y"]["stored_bytes"],
            plan["datasets"]["x"]["table_sha256"], plan["datasets"]["y"]["table_sha256"]]
    print("\t".join(str(v) for v in vals))


def check_plan(recipe_dir: Path, data_root: Path, seq: str) -> dict:
    row = seq_row(recipe_dir, seq)
    # re-derive from cached metadata instead of trusting plan.json
    try:
        plan = resolve_plan(seq_dir(data_root, seq) / "meta", row["file_size"])
    except T.NeedBytes as need:
        die(f"{seq}: metadata incomplete ({need})")
    except T.LayoutError as exc:
        die(f"{seq}: {exc}")
    checks = {
        "n_events": (plan["n_events"], row["n_events"]),
        "window_start_chunk": (plan["window_start_chunk"], row["window_start_chunk"]),
        "x_stored_bytes": (plan["datasets"]["x"]["stored_bytes"], row["x_stored_bytes"]),
        "y_stored_bytes": (plan["datasets"]["y"]["stored_bytes"], row["y_stored_bytes"]),
        "x_table_sha256": (plan["datasets"]["x"]["table_sha256"], row["x_table_sha256"]),
        "y_table_sha256": (plan["datasets"]["y"]["table_sha256"], row["y_table_sha256"]),
    }
    for name, (got, want) in checks.items():
        if got != want:
            die(f"{seq}: {name} {got} != pinned {want}")
    if [c[0] for c in plan["datasets"]["x"]["chunks"]] != [c[0] for c in plan["datasets"]["y"]["chunks"]]:
        die(f"{seq}: x and y windows cover different chunk indices")
    return plan


def cmd_check_plan(args: argparse.Namespace) -> None:
    plan = check_plan(Path(args.recipe_dir), Path(args.data_root), args.seq)
    print(f"plan_ok {args.seq} n_events={plan['n_events']} window_chunks="
          f"[{plan['window_start_chunk']}, {plan['window_start_chunk'] + T.WINDOW_CHUNKS})")


def spans_of(plan: dict) -> list[tuple[int, int]]:
    refs = sorted((a, s) for k in ("x", "y") for _i, a, s in plan["datasets"][k]["chunks"])
    spans: list[list[int]] = []
    for a, s in refs:
        if spans and a - (spans[-1][0] + spans[-1][1]) <= SPAN_GAP and a >= spans[-1][0] + spans[-1][1]:
            spans[-1][1] = a + s - spans[-1][0]
        elif spans and a < spans[-1][0] + spans[-1][1]:
            die("overlapping chunk extents")
        else:
            spans.append([a, s])
    return [(a, s) for a, s in spans]


def cmd_spans(args: argparse.Namespace) -> None:
    for off, length in spans_of(load_plan(Path(args.data_root), args.seq)):
        print(off, length)


# --------------------------------------------------------------------------- headers
def cmd_check_headers(args: argparse.Namespace) -> None:
    text = Path(args.header_file).read_text(encoding="latin-1")
    blocks = [b for b in re.split(r"\r?\n\r?\n", text) if b.strip()]
    final = [b for b in blocks if not b.startswith("HTTP/1.1 200 Connection established")]
    if not final:
        die("empty header dump")
    last = final[-1].splitlines()
    status = last[0].split()
    if len(status) < 2 or status[1] != "206":
        die(f"expected HTTP 206, got {last[0]!r}")
    hdrs = {}
    for line in last[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            hdrs[k.strip().lower()] = v.strip()
    want_cr = f"bytes {args.start}-{args.end}/{args.size}"
    if hdrs.get("content-range") != want_cr:
        die(f"Content-Range {hdrs.get('content-range')!r} != {want_cr!r}")
    if hdrs.get("etag") != f'"{args.etag}"' and hdrs.get("etag") != args.etag:
        die(f"ETag {hdrs.get('etag')!r} != pinned {args.etag!r}")


# --------------------------------------------------------------------------- decode
def load_spans(data_root: Path, seq: str, plan: dict) -> T.Segments:
    seg = T.Segments(plan["file_size"])
    ddir = seq_dir(data_root, seq) / "data"
    for off, length in spans_of(plan):
        p = ddir / f"{off}-{length}.bin"
        if not p.is_file() or p.stat().st_size != length:
            die(f"{seq}: chunk span {p.name} missing or wrong size")
        seg.add(off, p.read_bytes())
    return seg


def decode_window(data_root: Path, seq: str, plan: dict) -> dict[str, bytes]:
    seg = load_spans(data_root, seq, plan)
    out = {}
    for k in ("x", "y"):
        cd = plan["datasets"][k]["blosc_cd_values"]
        if cd[2] != T.ELEM_SIZE or cd[3] != T.CHUNK_BYTES:
            die(f"{seq}: unexpected Blosc cd_values {cd}")
        parts = []
        for idx, addr, size in plan["datasets"][k]["chunks"]:
            try:
                raw = T.blosc_decode(seg.read(addr, size))
            except (T.LayoutError, T.NeedBytes) as exc:
                die(f"{seq}: events/{k} chunk {idx}: {exc}")
            lo, hi, n = T.u16_stats(raw)
            if n != T.CHUNK_ELEMS or hi > LIMITS[k]:
                die(f"{seq}: events/{k} chunk {idx} has max {hi} > {LIMITS[k]} or {n} values")
            parts.append(raw)
        out[k] = b"".join(parts)
    return out


def series_stats(raw: bytes) -> dict:
    vals = memoryview(raw).cast("H")
    hist = [0] * 65536
    for v in vals:
        hist[v] += 1
    distinct = sum(1 for c in hist if c)
    top = max(hist)
    return {"min": min(vals), "max": max(vals), "distinct": distinct, "top_value_fraction": top / len(vals),
            "value_count": len(vals), "sha256": hashlib.sha256(raw).hexdigest()}


def check_series(seq: str, k: str, st: dict) -> None:
    if st["value_count"] != T.WINDOW_CHUNKS * T.CHUNK_ELEMS:
        die(f"{seq}/{k}: value count {st['value_count']}")
    if st["max"] > LIMITS[k]:
        die(f"{seq}/{k}: max {st['max']} > {LIMITS[k]}")
    floor = 256 if k == "x" else 128
    if st["distinct"] < floor:
        die(f"{seq}/{k}: only {st['distinct']} distinct coordinates (degenerate window)")
    if st["top_value_fraction"] > 0.25:
        die(f"{seq}/{k}: one coordinate holds {st['top_value_fraction']:.3f} of the window (degenerate)")


def cmd_check_seq(args: argparse.Namespace) -> None:
    data_root = Path(args.data_root)
    plan = check_plan(Path(args.recipe_dir), data_root, args.seq)
    dec = decode_window(data_root, args.seq, plan)
    msg = []
    for k in ("x", "y"):
        st = series_stats(dec[k])
        check_series(args.seq, k, st)
        msg.append(f"{k}:min={st['min']},max={st['max']},distinct={st['distinct']}")
    print(f"seq_ok {args.seq} " + " ".join(msg))


def cmd_build(args: argparse.Namespace) -> None:
    recipe_dir, data_root = Path(args.recipe_dir), Path(args.data_root)
    samples_root = data_root / "samples" / DATASET_ID
    index_dir = data_root / "index" / DATASET_ID
    filtered_dir = data_root / "filtered" / DATASET_ID
    for d in (index_dir, filtered_dir):
        d.mkdir(parents=True, exist_ok=True)
    for sid in SERIES.values():
        sdir = samples_root / sid
        sdir.mkdir(parents=True, exist_ok=True)
        for old in sdir.glob("*.u16"):
            old.unlink()
    rows, stats = [], {}
    for row in load_sequences(recipe_dir):
        seq = row["sequence"]
        plan = check_plan(recipe_dir, data_root, seq)
        dec = decode_window(data_root, seq, plan)
        stats[seq] = {}
        for k in ("x", "y"):
            st = series_stats(dec[k])
            check_series(seq, k, st)
            sid = SERIES[k]
            rel = f"samples/{DATASET_ID}/{sid}/{seq}.u16"
            tmp = data_root / (rel + ".tmp")
            tmp.write_bytes(dec[k])
            os.replace(tmp, data_root / rel)
            rows.append({
                "dataset_id": DATASET_ID, "series_id": sid, "sample_path": rel,
                "numeric_kind": "uint", "bit_width": 16, "endianness": "little",
                "element_size_bytes": 2, "sample_size_bytes": len(dec[k]), "value_count": st["value_count"],
                "sequence": seq, "camera": "left", "source_url": seq_url(seq), "source_field": f"events/{k}",
                "event_index_start": plan["event_index_start"], "event_index_end": plan["event_index_end"],
                "window_start_chunk": plan["window_start_chunk"], "window_chunks": T.WINDOW_CHUNKS,
                "stream_event_count": plan["n_events"],
                "min": st["min"], "max": st["max"], "distinct_values": st["distinct"],
                "top_value_fraction": round(st["top_value_fraction"], 6), "sha256": st["sha256"],
            })
            stats[seq][k] = st
        print(f"built {seq} events=[{plan['event_index_start']}, {plan['event_index_end']}) of {plan['n_events']}",
              flush=True)
    with open(index_dir / "samples.jsonl.tmp", "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=False) + "\n")
    os.replace(index_dir / "samples.jsonl.tmp", index_dir / "samples.jsonl")
    agg = hashlib.sha256()
    for r in rows:
        agg.update(bytes.fromhex(r["sha256"]))
    summary = {"samples": len(rows), "total_bytes": sum(r["sample_size_bytes"] for r in rows),
               "total_values": sum(r["value_count"] for r in rows),
               "sha256_of_sample_sha256s_in_index_order": agg.hexdigest(), "per_sequence": stats}
    (filtered_dir / "ingest_stats.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(f"build_ok samples={summary['samples']} bytes={summary['total_bytes']} values={summary['total_values']} "
          f"agg={summary['sha256_of_sample_sha256s_in_index_order']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command")
    ap.add_argument("--recipe-dir", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--data-root", default=".data")
    ap.add_argument("--seq")
    ap.add_argument("--size", type=int)
    ap.add_argument("--cache")
    ap.add_argument("--etag")
    ap.add_argument("--last-modified")
    ap.add_argument("--page")
    ap.add_argument("--header-file")
    ap.add_argument("--start", type=int)
    ap.add_argument("--end", type=int)
    args = ap.parse_args()
    cmds = {"check-license": cmd_check_license, "plan": cmd_plan, "discover-row": cmd_discover_row,
            "check-plan": cmd_check_plan, "spans": cmd_spans, "check-headers": cmd_check_headers,
            "check-seq": cmd_check_seq, "build": cmd_build}
    if args.command not in cmds:
        die(f"unknown command {args.command}")
    cmds[args.command](args)


if __name__ == "__main__":
    main()
