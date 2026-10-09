#!/usr/bin/env python3
"""Helpers for the musopen_chopin_solo_piano_pcm_i16 recipe (standard library only).

Subcommands
  selftest                      synthetic tests of the FLAC metadata parser
  check-meta                    validate the two Internet Archive metadata JSONs
                                against the pinned file table and the CC0 claim
  plan                          list pinned FLACs still missing (tab-separated:
                                sample_id, url, local path)
  check-flac SAMPLE_ID PATH     validate one downloaded FLAC (size, IA md5,
                                fLaC magic, STREAMINFO == pinned)
  build                         decode every pinned FLAC with ffmpeg into one raw
                                little-endian int16 sample per piece and write the
                                sample index and ingest stats

Network I/O is done by download.sh with curl; this module only parses local files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.parse
from array import array
from pathlib import Path

DATASET_ID = "musopen_chopin_solo_piano_pcm_i16"
SERIES_ID = "chopin_solo_piano_pcm_s16_stereo"
FLAC_ITEM = "musopen-chopin-complete-works-flac"
CC0_ITEM = "musopen-chopin"
CC0_URL_TAIL = "creativecommons.org/publicdomain/zero/1.0/"
DOWNLOAD_BASE = f"https://archive.org/download/{FLAC_ITEM}/"
EXPECTED_FORMAT = (44100, 2, 16)
RECIPE_DIR = Path(__file__).resolve().parents[1]
PINNED_TSV = RECIPE_DIR / "scripts" / "pinned_files.tsv"
MAX_ZERO_FRACTION = 0.5
# Pieces that pass the STREAMINFO filter but are excluded after a spectral audit
# (ffmpeg highpass + astats, see README): a brick-wall cutoff (-116 dB above
# 15 kHz, digital zero above 18 kHz) marks a lossy or low-passed master, unlike
# the smooth -90..-100 dB noise floor of every other selected piece.
EXCLUDED = {
    "etude_b130_trois_nouvelles_no2": "spectral brick-wall above ~16 kHz (lossy/low-passed master; sole Donald Betts track)",
}
MAX_EDGE_SILENCE_FRACTION = 0.5


# ---------------------------------------------------------------- FLAC metadata
def parse_flac_header(head: bytes) -> dict:
    """Parse the fLaC marker, STREAMINFO and (if present in `head`) VORBIS_COMMENT."""
    if head[:4] != b"fLaC":
        raise ValueError("missing fLaC stream marker")
    if len(head) < 42:
        raise ValueError("header too short for STREAMINFO")
    if head[4] & 0x7F != 0:
        raise ValueError("first metadata block is not STREAMINFO")
    if int.from_bytes(head[5:8], "big") != 34:
        raise ValueError("STREAMINFO length is not 34")
    s = head[8:42]
    sample_rate = (s[10] << 12) | (s[11] << 4) | (s[12] >> 4)
    channels = ((s[12] >> 1) & 0x7) + 1
    bits = (((s[12] & 0x1) << 4) | (s[13] >> 4)) + 1
    total = ((s[13] & 0x0F) << 32) | int.from_bytes(s[14:18], "big")
    info = {
        "min_block": int.from_bytes(s[0:2], "big"),
        "max_block": int.from_bytes(s[2:4], "big"),
        "sample_rate": sample_rate,
        "channels": channels,
        "bits_per_sample": bits,
        "total_samples": total,
        "md5": s[18:34].hex(),
        "comments": {},
    }
    pos = 4
    while pos + 4 <= len(head):
        flag = head[pos]
        btype = flag & 0x7F
        length = int.from_bytes(head[pos + 1 : pos + 4], "big")
        data = head[pos + 4 : pos + 4 + length]
        if btype == 4 and len(data) == length:
            vlen = int.from_bytes(data[0:4], "little")
            q = 4 + vlen
            count = int.from_bytes(data[q : q + 4], "little")
            q += 4
            for _ in range(count):
                clen = int.from_bytes(data[q : q + 4], "little")
                text = data[q + 4 : q + 4 + clen].decode("utf-8", "replace")
                q += 4 + clen
                if "=" in text:
                    key, value = text.split("=", 1)
                    info["comments"].setdefault(key.upper(), value)
        pos += 4 + length
        if flag & 0x80:
            break
    return info


def _synthetic_header(sr: int, ch: int, bps: int, total: int, md5: bytes, comments: list[str], last_flag_on_comment: bool) -> bytes:
    b10_13 = (sr << 44) | ((ch - 1) << 41) | ((bps - 1) << 36) | total
    streaminfo = (4096).to_bytes(2, "big") + (4096).to_bytes(2, "big") + (14).to_bytes(3, "big") + (9000).to_bytes(3, "big")
    streaminfo += b10_13.to_bytes(8, "big") + md5
    assert len(streaminfo) == 34
    vendor = b"synthetic"
    body = len(vendor).to_bytes(4, "little") + vendor + len(comments).to_bytes(4, "little")
    for c in comments:
        enc = c.encode()
        body += len(enc).to_bytes(4, "little") + enc
    out = b"fLaC" + bytes([0]) + (34).to_bytes(3, "big") + streaminfo
    out += bytes([0x04 | (0x80 if last_flag_on_comment else 0)]) + len(body).to_bytes(3, "big") + body
    if not last_flag_on_comment:
        pic = b"\x00" * 50000  # large PICTURE block, truncated in a short header read
        out += bytes([0x86]) + len(pic).to_bytes(3, "big") + pic
    return out


def cmd_selftest(_: argparse.Namespace) -> None:
    md5 = bytes(range(16))
    for sr, ch, bps, total in [(44100, 2, 16, 7036294), (48000, 2, 16, 5323005), (96000, 2, 24, 2**35 + 17), (8000, 1, 8, 1)]:
        hdr = _synthetic_header(sr, ch, bps, total, md5, ["ARTIST=Test Pianist", "TITLE=x=y"], True)
        info = parse_flac_header(hdr)
        got = (info["sample_rate"], info["channels"], info["bits_per_sample"], info["total_samples"], info["md5"])
        if got != (sr, ch, bps, total, md5.hex()):
            raise SystemExit(f"selftest STREAMINFO mismatch: {got}")
        if info["comments"] != {"ARTIST": "Test Pianist", "TITLE": "x=y"}:
            raise SystemExit(f"selftest comment mismatch: {info['comments']}")
    hdr = _synthetic_header(44100, 2, 16, 123, md5, ["ARTIST=A"], False)
    info = parse_flac_header(hdr[:8192])  # truncated PICTURE must not crash
    if info["total_samples"] != 123 or info["comments"].get("ARTIST") != "A":
        raise SystemExit("selftest truncated-header case failed")
    for bad in (b"RIFF" + hdr[4:], hdr[:30]):
        try:
            parse_flac_header(bad)
        except ValueError:
            continue
        raise SystemExit("selftest accepted an invalid header")
    # stats helpers on a synthetic PCM buffer
    pcm = array("h", [0, 0, 0, 0, 5, -3, 7, 7, 0, 0]).tobytes()
    lead, trail = edge_silence_frames(pcm)
    if (lead, trail) != (2, 1):
        raise SystemExit(f"selftest edge silence mismatch: {lead} {trail}")
    pcm = array("h", [0, 0, 0, 256, 0, 0]).tobytes()  # right-channel sample with zero low byte
    if edge_silence_frames(pcm) != (1, 1):
        raise SystemExit(f"selftest edge silence (zero low byte) mismatch: {edge_silence_frames(pcm)}")
    print("selftest ok")


# ---------------------------------------------------------------- pinned table
def load_pinned() -> list[dict]:
    lines = PINNED_TSV.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        row = dict(zip(header, line.split("\t")))
        for key in ("size_bytes", "sample_rate_hz", "channels", "bits_per_sample", "total_samples"):
            row[key] = int(row[key])
        rows.append(row)
    ids = [r["sample_id"] for r in rows]
    if len(set(ids)) != len(ids) or ids != sorted(ids):
        raise SystemExit("pinned_files.tsv sample ids must be unique and sorted")
    for r in rows:
        if (r["sample_rate_hz"], r["channels"], r["bits_per_sample"]) != EXPECTED_FORMAT:
            raise SystemExit(f"pinned row outside the 44.1 kHz/stereo/16-bit regime: {r['sample_id']}")
        name = r["ia_name"]
        if r["sample_id"] in EXCLUDED:
            raise SystemExit(f"pinned row is on the exclusion list: {r['sample_id']}")
        if "Cello Sonata" in name or not ("Prelude" in name or "tude" in name):
            raise SystemExit(f"pinned row is not a solo Prelude/Etude: {name}")
    return rows


def file_url(name: str) -> str:
    return DOWNLOAD_BASE + urllib.parse.quote(name)


def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- download helpers
def cmd_check_meta(args: argparse.Namespace) -> None:
    meta_dir = Path(args.meta_dir)
    flac_meta = json.loads((meta_dir / f"{FLAC_ITEM}.metadata.json").read_text(encoding="utf-8"))
    cc0_meta = json.loads((meta_dir / f"{CC0_ITEM}.metadata.json").read_text(encoding="utf-8"))
    m = flac_meta.get("metadata", {})
    if m.get("identifier") != FLAC_ITEM or not str(m.get("licenseurl", "")).endswith(CC0_URL_TAIL):
        raise SystemExit(f"FATAL: {FLAC_ITEM} metadata identifier/licenseurl unexpected: {m.get('identifier')} {m.get('licenseurl')}")
    if m.get("publisher") != "Musopen":
        raise SystemExit(f"FATAL: {FLAC_ITEM} publisher is not Musopen: {m.get('publisher')}")
    c = cc0_meta.get("metadata", {})
    if c.get("identifier") != CC0_ITEM or c.get("uploader") != "aaron@musopen.org" or not str(c.get("licenseurl", "")).endswith(CC0_URL_TAIL):
        raise SystemExit(f"FATAL: first-party {CC0_ITEM} metadata no longer shows Musopen uploader + CC0: {c.get('uploader')} {c.get('licenseurl')}")
    files = {f["name"]: f for f in flac_meta.get("files", [])}
    flac_counts = {"Flac": 0, "24bit Flac": 0}
    for f in files.values():
        if f.get("format") in flac_counts:
            flac_counts[f["format"]] += 1
    for row in load_pinned():
        f = files.get(row["ia_name"])
        if f is None:
            raise SystemExit(f"FATAL: pinned file missing from IA item: {row['ia_name']}")
        if f.get("format") != "Flac" or f.get("md5") != row["ia_md5"] or int(f.get("size", -1)) != row["size_bytes"]:
            raise SystemExit(f"FATAL: IA metadata changed for {row['ia_name']}: format={f.get('format')} md5={f.get('md5')} size={f.get('size')}")
    print(f"metadata_ok flac_item_licenseurl={m.get('licenseurl')} cc0_item_uploader={c.get('uploader')} flac_counts={flac_counts}")


def discover_candidates(flac_meta: dict) -> list[dict]:
    """Every FLAC in the item whose name marks it as a Prelude or Etude."""
    out = []
    for f in sorted(flac_meta.get("files", []), key=lambda x: x["name"]):
        name = f["name"]
        if name.endswith(".flac") and ("Prelude" in name or "tude" in name) and "Cello Sonata" not in name:
            out.append(f)
    return out


def sample_id_for(name: str) -> str:
    import re
    import unicodedata

    name = unicodedata.normalize("NFC", name).replace("\u00c9tude", "Etude")
    m = re.match(r"Preludes, Op\. 28 - No\. (\d+)", name)
    if m:
        return "prelude_op28_no%02d" % int(m.group(1))
    m = re.match(r"Etude Op\. 25 no\. (\d+)", name)
    if m:
        return "etude_op25_no%02d" % int(m.group(1))
    m = re.match(r"Etude Op\. 10, no\. (\d+)", name)
    if m:
        return "etude_op10_no%02d" % int(m.group(1))
    fixed = {
        "Etude no.26 - B.130": "etude_b130_trois_nouvelles_no2",
        "Prelude in A flat major, B. 86": "prelude_b86",
        "Prelude in C sharp minor, Op. 45": "prelude_op45",
        "Prelude no. 27": "prelude_no27_devils_trill",
    }
    for prefix, sid in fixed.items():
        if name.startswith(prefix):
            return sid
    raise SystemExit(f"no sample id rule for {name!r}")


def cmd_discover(args: argparse.Namespace) -> None:
    """Print the candidate URL list (--list-urls) or the pinned table from fetched headers."""
    flac_meta = json.loads(Path(args.meta).read_text(encoding="utf-8"))
    cands = discover_candidates(flac_meta)
    if args.list_urls:
        for f in cands:
            print(f"{f['md5']}\t{file_url(f['name'])}")
        return
    print("sample_id\tia_name\tsize_bytes\tia_md5\tsample_rate_hz\tchannels\tbits_per_sample\ttotal_samples\tstreaminfo_md5\tartist_tag")
    rows, skipped = [], []
    for f in cands:
        info = parse_flac_header((Path(args.headers_dir) / f"{f['md5']}.bin").read_bytes())
        fmt = (info["sample_rate"], info["channels"], info["bits_per_sample"])
        if fmt != EXPECTED_FORMAT:
            skipped.append((f["name"], fmt))
            continue
        sid = sample_id_for(f["name"])
        if sid in EXCLUDED:
            skipped.append((f["name"], f"excluded: {EXCLUDED[sid]}"))
            continue
        rows.append((sid, f["name"], f["size"], f["md5"], *fmt, info["total_samples"], info["md5"], info["comments"].get("ARTIST", "")))
    for r in sorted(rows):
        print("\t".join(map(str, r)))
    print(f"candidates={len(cands)} kept={len(rows)} skipped={len(skipped)} {sorted(set(str(s[1]) for s in skipped))}", file=sys.stderr)


def cmd_plan(args: argparse.Namespace) -> None:
    flac_dir = Path(args.flac_dir)
    for row in load_pinned():
        out = flac_dir / f"{row['sample_id']}.flac"
        if out.is_file() and out.stat().st_size == row["size_bytes"]:
            continue
        print(f"{row['sample_id']}\t{file_url(row['ia_name'])}\t{out}")


def check_flac(row: dict, path: Path, check_md5: bool = True) -> dict:
    size = path.stat().st_size
    if size != row["size_bytes"]:
        raise ValueError(f"size {size} != pinned {row['size_bytes']}")
    with path.open("rb") as fh:
        head = fh.read(8192)
    info = parse_flac_header(head)
    got = (info["sample_rate"], info["channels"], info["bits_per_sample"])
    if got != EXPECTED_FORMAT:
        raise ValueError(f"STREAMINFO format {got} != {EXPECTED_FORMAT}")
    if info["total_samples"] != row["total_samples"] or info["md5"] != row["streaminfo_md5"]:
        raise ValueError("STREAMINFO total_samples/md5 differ from pinned values")
    if check_md5:
        digest = md5_file(path)
        if digest != row["ia_md5"]:
            raise ValueError(f"md5 {digest} != pinned IA md5 {row['ia_md5']}")
    return info


def cmd_check_flac(args: argparse.Namespace) -> None:
    rows = {r["sample_id"]: r for r in load_pinned()}
    row = rows[args.sample_id]
    try:
        info = check_flac(row, Path(args.path))
    except ValueError as exc:
        print(f"INVALID {args.sample_id}: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print(f"flac_ok {args.sample_id} total_samples={info['total_samples']} artist={info['comments'].get('ARTIST', '')}")


# ---------------------------------------------------------------- build
def edge_silence_frames(pcm: bytes) -> tuple[int, int]:
    """Leading/trailing all-zero stereo frames (4 bytes per frame)."""
    lead = (len(pcm) - len(pcm.lstrip(b"\x00"))) // 4
    trail = (len(pcm) - len(pcm.rstrip(b"\x00"))) // 4
    total = len(pcm) // 4
    if lead >= total:
        return total, total
    return lead, trail


def decode_flac(path: Path, out_part: Path) -> None:
    cmd = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", str(path), "-map", "0:a:0", "-vn",
        "-f", "s16le", "-acodec", "pcm_s16le", "-y", str(out_part),
    ]
    subprocess.run(cmd, check=True)


def pcm_stats(pcm: bytes) -> dict:
    if sys.byteorder != "little":
        raise SystemExit("this build assumes a little-endian host")
    arr = array("h")
    arr.frombytes(pcm)
    n = len(arr)
    left = arr[0::2]
    right = arr[1::2]
    lead, trail = edge_silence_frames(pcm)
    low_bytes = pcm[0::2]
    odd = n - low_bytes.translate(bytes([0, 1] * 128)).count(b"\x00")  # count odd-valued samples
    return {
        "min": min(arr),
        "max": max(arr),
        "zero_values": arr.count(0),
        "clipped_values": arr.count(32767) + arr.count(-32768),
        "distinct_values": len(set(arr)),
        "odd_values": odd,
        "channels_identical": left == right,
        "leading_silence_frames": lead,
        "trailing_silence_frames": trail,
        "frames": n // 2,
    }


def cmd_build(args: argparse.Namespace) -> None:
    data_root = Path(args.data_root)
    flac_dir = data_root / "downloads" / DATASET_ID / "flac"
    out_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_dir = data_root / "index" / DATASET_ID
    filtered_dir = data_root / "filtered" / DATASET_ID
    for d in (out_dir, index_dir, filtered_dir):
        d.mkdir(parents=True, exist_ok=True)
    pinned = load_pinned()
    keep = {f"{r['sample_id']}.bin" for r in pinned}
    for stale in out_dir.iterdir():
        if stale.name not in keep:
            stale.unlink()
    rows, records = [], []
    for r in pinned:
        src = flac_dir / f"{r['sample_id']}.flac"
        if not src.is_file():
            raise SystemExit(f"FATAL: missing local FLAC {src}; run download.sh")
        info = check_flac(r, src, check_md5=True)
        out = out_dir / f"{r['sample_id']}.bin"
        part = out.with_suffix(".bin.part")
        decode_flac(src, part)
        pcm = part.read_bytes()
        expected_bytes = info["total_samples"] * 2 * 2
        if len(pcm) != expected_bytes:
            raise SystemExit(f"FATAL: {r['sample_id']} decoded {len(pcm)} bytes != total_samples*2ch*2B {expected_bytes}")
        if hashlib.md5(pcm).hexdigest() != info["md5"]:
            raise SystemExit(f"FATAL: {r['sample_id']} decoded PCM md5 != FLAC STREAMINFO MD5 signature (not a lossless decode)")
        st = pcm_stats(pcm)
        value_count = len(pcm) // 2
        frames = st["frames"]
        zero_fraction = st["zero_values"] / value_count
        edge_fraction = (st["leading_silence_frames"] + st["trailing_silence_frames"]) / frames
        problems = []
        if st["min"] == st["max"]:
            problems.append("constant")
        if zero_fraction > MAX_ZERO_FRACTION:
            problems.append(f"zero-dominated ({zero_fraction:.3f})")
        if edge_fraction > MAX_EDGE_SILENCE_FRACTION:
            problems.append(f"edge silence {edge_fraction:.3f}")
        if st["odd_values"] == 0:
            problems.append("no odd sample values (padded below 16-bit)")
        if st["distinct_values"] < 1024:
            problems.append(f"only {st['distinct_values']} distinct values")
        if st["channels_identical"]:
            problems.append("left and right channels identical (dual mono)")
        if problems:
            part.unlink()
            raise SystemExit(f"FATAL: {r['sample_id']} degenerate: {'; '.join(problems)}")
        part.replace(out)
        row = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_id": r["sample_id"],
            "sample_path": str(out.relative_to(data_root)),
            "numeric_kind": "int",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "sample_size_bytes": len(pcm),
            "value_count": value_count,
            "sample_format": "raw interleaved little-endian int16 stereo PCM (L,R,L,R,...)",
            "sample_geometry": "interleaved_stereo_waveform",
            "sample_rank": 2,
            "sample_shape": [frames, 2],
            "sample_axes": ["time_frame_44100hz", "channel_left_right"],
            "sample_rate_hz": 44100,
            "channels": 2,
            "natural_record_kind": "complete_recorded_piece_flac_track",
            "source_file": r["ia_name"],
            "source_ia_md5": r["ia_md5"],
            "flac_streaminfo_md5": info["md5"],
            "performer_tag": r["artist_tag"],
            "duration_s": round(frames / 44100, 3),
            "min": st["min"],
            "max": st["max"],
            "zero_fraction": round(zero_fraction, 6),
            "clipped_values": st["clipped_values"],
            "distinct_values": st["distinct_values"],
            "leading_silence_s": round(st["leading_silence_frames"] / 44100, 4),
            "trailing_silence_s": round(st["trailing_silence_frames"] / 44100, 4),
        }
        rows.append(row)
        records.append({k: row[k] for k in ("sample_id", "duration_s", "min", "max", "zero_fraction", "clipped_values", "distinct_values", "leading_silence_s", "trailing_silence_s", "performer_tag")})
        print(f"built {r['sample_id']} frames={frames} range={st['min']}..{st['max']} zero_frac={zero_fraction:.4f} "
              f"lead={row['leading_silence_s']}s trail={row['trailing_silence_s']}s clipped={st['clipped_values']} distinct={st['distinct_values']}", flush=True)
    total_bytes = sum(r["sample_size_bytes"] for r in rows)
    if total_bytes > 1_000_000_000:
        raise SystemExit(f"FATAL: primary bytes {total_bytes} exceed 1 GB cap")
    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    values = sorted(r["value_count"] for r in rows)
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(rows),
        "primary_values": sum(values),
        "primary_bytes": total_bytes,
        "median_values": values[len(values) // 2] if len(values) % 2 else (values[len(values) // 2 - 1] + values[len(values) // 2]) / 2,
        "total_duration_s": round(sum(r["duration_s"] for r in rows), 3),
        "records": records,
    }
    (filtered_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"build_summary samples={len(rows)} primary_values={stats['primary_values']} primary_bytes={total_bytes} duration_s={stats['total_duration_s']}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("selftest").set_defaults(fn=cmd_selftest)
    s = sub.add_parser("check-meta")
    s.add_argument("--meta-dir", required=True)
    s.set_defaults(fn=cmd_check_meta)
    s = sub.add_parser("discover")
    s.add_argument("--meta", required=True)
    s.add_argument("--headers-dir")
    s.add_argument("--list-urls", action="store_true")
    s.set_defaults(fn=cmd_discover)
    s = sub.add_parser("plan")
    s.add_argument("--flac-dir", required=True)
    s.set_defaults(fn=cmd_plan)
    s = sub.add_parser("check-flac")
    s.add_argument("sample_id")
    s.add_argument("path")
    s.set_defaults(fn=cmd_check_flac)
    s = sub.add_parser("build")
    s.add_argument("--data-root", required=True)
    s.set_defaults(fn=cmd_build)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
