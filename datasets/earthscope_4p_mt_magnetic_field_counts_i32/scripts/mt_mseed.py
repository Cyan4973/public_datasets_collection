#!/usr/bin/env python3
"""EarthScope 4P MT-TA NIMS magnetic-field miniSEED (Steim2) -> raw int32 LE.

Subcommands
  selftest       Steim2 / miniSEED / segmentation self-test on synthetic records
  select         derive the pinned epoch selection from fdsnws station text files
  check-station  verify that every pinned epoch is still listed with the pinned gain
  inspect        validate one downloaded dataselect payload for one pinned epoch
  build          decode all pinned epochs into gap-split int32 samples + index
  verify         independently re-decode and check every output against the index

Pure standard library. All miniSEED headers are big-endian (SEED 2.4); the
Steim2 payload word order is taken from blockette 1000 and must be 1 (big).
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
import shutil
import struct
import sys
from array import array
from datetime import datetime, timedelta
from pathlib import Path

DATASET_ID = "earthscope_4p_mt_magnetic_field_counts_i32"
SERIES_BY_CHANNEL = {
    "LFN": "mt_nims_bfield_north_lfn_counts_i32",
    "LFE": "mt_nims_bfield_east_lfe_counts_i32",
    "LFZ": "mt_nims_bfield_vertical_lfz_counts_i32",
}
NETWORK = "4P"
CHANNELS = ("LFN", "LFE", "LFZ")
EXPECTED_SENSOR = "NIMS"
EXPECTED_SCALE = "100.9048"
EXPECTED_SCALE_UNITS = "nT"
EXPECTED_RATE = "1.0"
SAMPLE_PERIOD_S = 1.0
GAP_TOLERANCE_S = 0.5
MIN_SEGMENT_VALUES = 1000
MIN_EPOCH_FRACTION = 0.80
MAX_TOTAL_BYTES = 1_000_000_000
MAX_DOMINANT_FRACTION = 0.5
# UTC instants immediately after an inserted leap second within the 4P era
# (2006-2018). miniSEED start times skip 23:59:60, so naive arithmetic sees a
# -1 s step across these instants although the 1 sps sampling is continuous.
LEAP_SECOND_INSTANTS = (
    datetime(2009, 1, 1),
    datetime(2012, 7, 1),
    datetime(2015, 7, 1),
    datetime(2017, 1, 1),
)
SELECTION_FIELDS = (
    "station", "channel", "start", "end", "latitude", "longitude",
    "nominal_values", "expected_values", "mseed_sha256",
)
INT32_MIN, INT32_MAX = -(1 << 31), (1 << 31) - 1


# --------------------------------------------------------------------------
# Steim2
# --------------------------------------------------------------------------
def _sx(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return (value ^ sign) - sign


def steim2_decode(payload: bytes, nsamples: int, big_endian: bool = True) -> list[int]:
    """Decode nsamples from a Steim2 payload (whole 64-byte frames)."""
    nframes = len(payload) // 64
    if nframes == 0:
        raise ValueError("Steim2 payload has no frames")
    words = array("I")
    if words.itemsize != 4:
        raise SystemExit("host array('I') is not 32-bit")
    words.frombytes(payload[: nframes * 64])
    if big_endian == (sys.byteorder == "little"):
        words.byteswap()
    diffs: list[int] = []
    append = diffs.append
    x0 = xn = None
    for frame in range(nframes):
        base = frame * 16
        ctrl = words[base]
        for i in range(1, 16):
            code = (ctrl >> (30 - 2 * i)) & 3
            w = words[base + i]
            if code == 0:
                if frame == 0 and i == 1:
                    x0 = _sx(w, 32)
                elif frame == 0 and i == 2:
                    xn = _sx(w, 32)
                continue
            if code == 1:
                for sh in (24, 16, 8, 0):
                    append(_sx((w >> sh) & 0xFF, 8))
            elif code == 2:
                dnib = w >> 30
                if dnib == 1:
                    append(_sx(w & 0x3FFFFFFF, 30))
                elif dnib == 2:
                    append(_sx((w >> 15) & 0x7FFF, 15))
                    append(_sx(w & 0x7FFF, 15))
                elif dnib == 3:
                    append(_sx((w >> 20) & 0x3FF, 10))
                    append(_sx((w >> 10) & 0x3FF, 10))
                    append(_sx(w & 0x3FF, 10))
                else:
                    raise ValueError("invalid Steim2 dnib 00 for code 10")
            else:
                dnib = w >> 30
                if dnib == 0:
                    for sh in (24, 18, 12, 6, 0):
                        append(_sx((w >> sh) & 0x3F, 6))
                elif dnib == 1:
                    for sh in (25, 20, 15, 10, 5, 0):
                        append(_sx((w >> sh) & 0x1F, 5))
                elif dnib == 2:
                    for sh in (24, 20, 16, 12, 8, 4, 0):
                        append(_sx((w >> sh) & 0xF, 4))
                else:
                    raise ValueError("invalid Steim2 dnib 11 for code 11")
        if frame > 0 and len(diffs) >= nsamples:
            break
    if x0 is None or xn is None:
        raise ValueError("Steim2 frame 0 lacks integration constants")
    if len(diffs) < nsamples:
        raise ValueError(f"Steim2 payload holds {len(diffs)} differences < {nsamples} samples")
    out = [x0]
    x = x0
    for d in diffs[1:nsamples]:
        x += d
        out.append(x)
    if x != xn:
        raise ValueError(f"Steim2 reverse integration constant mismatch: last={x} Xn={xn}")
    if min(out) < INT32_MIN or max(out) > INT32_MAX:
        raise ValueError("Steim2 value outside int32")
    return out


# --------------------------------------------------------------------------
# miniSEED records
# --------------------------------------------------------------------------
def parse_records(raw: bytes, station: str, channel: str) -> list[tuple[datetime, list[int]]]:
    """Return [(record_start, values)] for one exact 4P.<station>..<channel> stream."""
    records: list[tuple[datetime, list[int]]] = []
    offset = 0
    while offset < len(raw):
        if offset + 64 > len(raw):
            raise ValueError(f"truncated record header at {offset}")
        h = raw[offset:offset + 48]
        if not all(48 <= b <= 57 or b == 32 for b in h[:6]) or h[6:7] not in (b"D", b"R", b"Q", b"M"):
            raise ValueError(f"not a SEED data record at {offset}")
        sta = h[8:13].decode("ascii").strip()
        loc = h[13:15].decode("ascii").strip()
        cha = h[15:18].decode("ascii").strip()
        net = h[18:20].decode("ascii").strip()
        if (net, sta, loc, cha) != (NETWORK, station, "", channel):
            raise ValueError(f"unexpected stream {net}.{sta}.{loc}.{cha} at {offset}")
        year, doy = struct.unpack_from(">HH", h, 20)
        hh, mm, ss = h[24], h[25], h[26]
        frac = struct.unpack_from(">H", h, 28)[0]
        nsamp, rfac, rmul = struct.unpack_from(">Hhh", h, 30)
        tcorr = struct.unpack_from(">i", h, 40)[0]
        data_off, blk_off = struct.unpack_from(">HH", h, 44)
        activity = h[36]
        if not (1990 <= year <= 2100 and 1 <= doy <= 366 and hh < 24 and mm < 60 and ss <= 60 and frac < 10000):
            raise ValueError(f"invalid start time at {offset}")
        if (rfac, rmul) != (1, 1):
            raise ValueError(f"unexpected sample-rate factor/multiplier {rfac}/{rmul} at {offset}")
        if tcorr != 0 and not (activity & 0x02):
            raise ValueError(f"unapplied time correction at {offset}")
        b1000 = None
        cur = blk_off
        seen: set[int] = set()
        while cur:
            if cur in seen or cur < 48 or offset + cur + 8 > len(raw):
                raise ValueError(f"bad blockette chain at {offset}")
            seen.add(cur)
            btype, nxt = struct.unpack_from(">HH", raw, offset + cur)
            if btype == 1000:
                b1000 = raw[offset + cur + 4], raw[offset + cur + 5], raw[offset + cur + 6]
            cur = nxt
        if b1000 is None:
            raise ValueError(f"missing blockette 1000 at {offset}")
        encoding, word_order, reclen_exp = b1000
        if encoding != 11:
            raise ValueError(f"expected Steim2 encoding 11, got {encoding} at {offset}")
        if word_order != 1:
            raise ValueError(f"unexpected word order {word_order} at {offset}")
        if not 8 <= reclen_exp <= 16:
            raise ValueError(f"bad record length exponent {reclen_exp} at {offset}")
        reclen = 1 << reclen_exp
        if offset + reclen > len(raw) or not 48 <= data_off < reclen or (reclen - data_off) % 64:
            raise ValueError(f"bad record geometry at {offset}")
        start = datetime(year, 1, 1) + timedelta(days=doy - 1, hours=hh, minutes=mm, seconds=ss, microseconds=frac * 100)
        if nsamp > 0:
            values = steim2_decode(raw[offset + data_off: offset + reclen], nsamp, True)
            records.append((start, values))
        offset += reclen
    if not records:
        raise ValueError("no data records")
    return records


def segment_records(records: list[tuple[datetime, list[int]]], min_values: int = MIN_SEGMENT_VALUES) -> tuple[list[tuple[datetime, array]], dict]:
    """Split a time-ordered record list into contiguous 1 sps segments."""
    stats = collections.Counter()
    gap_seconds = 0.0
    segments: list[tuple[datetime, array]] = []
    cur_start: datetime | None = None
    cur_vals: array | None = None
    expected_next: datetime | None = None
    prev_start: datetime | None = None
    for start, values in records:
        if prev_start is not None and start < prev_start:
            raise ValueError(f"records out of time order at {start.isoformat()}")
        contiguous = False
        if expected_next is not None:
            delta = (start - expected_next).total_seconds()
            if abs(delta) <= GAP_TOLERANCE_S:
                contiguous = True
            elif abs(delta + 1.0) <= GAP_TOLERANCE_S and any(prev_start < leap <= start for leap in LEAP_SECOND_INSTANTS):
                contiguous = True
                stats["leap_second_continuations"] += 1
            elif delta > 0:
                stats["gaps"] += 1
                gap_seconds += delta
            else:
                stats["overlaps"] += 1
        if not contiguous:
            if cur_vals is not None:
                segments.append((cur_start, cur_vals))
            cur_start, cur_vals = start, array("i")
        cur_vals.extend(values)
        expected_next = start + timedelta(seconds=len(values) * SAMPLE_PERIOD_S)
        prev_start = start
    if cur_vals is not None:
        segments.append((cur_start, cur_vals))
    kept = [(s, v) for s, v in segments if len(v) >= min_values]
    dropped = [len(v) for s, v in segments if len(v) < min_values]
    info = {
        "record_count": len(records),
        "decoded_values": sum(len(v) for _, v in records),
        "gaps": stats["gaps"],
        "gap_seconds": gap_seconds,
        "overlaps": stats["overlaps"],
        "leap_second_continuations": stats["leap_second_continuations"],
        "segments_total": len(segments),
        "segments_kept": len(kept),
        "short_fragments_dropped": len(dropped),
        "short_fragment_values_dropped": sum(dropped),
    }
    return kept, info


# --------------------------------------------------------------------------
# Selection and station metadata
# --------------------------------------------------------------------------
def read_station_text(path: Path) -> list[list[str]]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        header = fh.readline()
        if not header.startswith("#Network") or "Scale" not in header:
            raise ValueError(f"{path}: not an fdsnws station text channel listing")
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            fields = line.split("|")
            if len(fields) != 17:
                raise ValueError(f"{path}: malformed row {line!r}")
            rows.append(fields)
    if len(rows) < 1000:
        raise ValueError(f"{path}: only {len(rows)} channel epochs; expected the full 4P listing")
    return rows


def station_epochs(station_dir: Path) -> dict[tuple[str, str, str, str], list[str]]:
    epochs: dict[tuple[str, str, str, str], list[str]] = {}
    for cha in CHANNELS:
        for f in read_station_text(station_dir / f"station_4P_{cha}.txt"):
            if f[0] != NETWORK or f[3] != cha:
                raise ValueError(f"foreign row in station_4P_{cha}.txt: {f[:4]}")
            epochs[(f[1], f[2], cha, f[15])] = f
    return epochs


def epoch_is_standard(f: list[str]) -> bool:
    return (f[2] == "" and f[10] == EXPECTED_SENSOR and f[11] == EXPECTED_SCALE
            and f[13] == EXPECTED_SCALE_UNITS and f[14] == EXPECTED_RATE)


def parse_time(s: str) -> datetime:
    return datetime.fromisoformat(s)


def stamp(s: str) -> str:
    return s.split(".")[0].replace("-", "").replace(":", "")


def read_selection(path: Path) -> list[dict[str, str]]:
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln and not ln.startswith("#")]
    header = lines[0].split("\t")
    if tuple(header) != SELECTION_FIELDS:
        raise ValueError(f"{path}: unexpected header {header}")
    rows = [dict(zip(header, ln.split("\t"))) for ln in lines[1:]]
    for r in rows:
        if len(r) != len(SELECTION_FIELDS) or r["channel"] not in CHANNELS:
            raise ValueError(f"{path}: malformed row {r}")
        for key in ("expected_values", "mseed_sha256"):  # "-" = not pinned yet
            r[key] = "" if r[key] == "-" else r[key]
    keys = {(r["station"], r["channel"], r["start"]) for r in rows}
    if len(keys) != len(rows):
        raise ValueError(f"{path}: duplicate epochs")
    return rows


def mseed_name(r: dict[str, str]) -> str:
    return f"4P.{r['station']}..{r['channel']}.{stamp(r['start'])}.mseed"


def cmd_select(args: argparse.Namespace) -> None:
    epochs = station_epochs(args.station_dir)
    groups: dict[tuple[str, str, str], dict[str, list[str]]] = collections.defaultdict(dict)
    for (sta, loc, cha, start), f in epochs.items():
        groups[(sta, start, f[16])][cha] = f
    cands = []
    for (sta, start, end), d in groups.items():
        if len(d) == 3 and all(epoch_is_standard(f) for f in d.values()):
            days = (parse_time(end) - parse_time(start)).total_seconds() / 86400.0
            cands.append((start[:4], abs(days - 21.0), sta, start, end))
    by_year: dict[str, list] = collections.defaultdict(list)
    for c in cands:
        by_year[c[0]].append(c)
    picks = []
    for year in sorted(by_year):
        ranked = sorted(by_year[year], key=lambda c: (c[1], c[2], c[3]))
        take = 2 if year in args.double_years.split(",") else 1
        picks.extend(ranked[:take])
    out = ["\t".join(SELECTION_FIELDS)]
    for _, _, sta, start, end in sorted(picks, key=lambda c: (c[3], c[2])):
        for cha in CHANNELS:
            f = groups[(sta, start, end)][cha]
            nominal = int(round((parse_time(end) - parse_time(start)).total_seconds())) + 1
            out.append("\t".join([sta, cha, start, end, f[4], f[5], str(nominal), "-", "-"]))
    sys.stdout.write("\n".join(out) + "\n")
    print(f"selected {len(picks)} station epochs from {len(cands)} complete standard-gain triplets", file=sys.stderr)


def cmd_check_station(args: argparse.Namespace) -> None:
    epochs = station_epochs(args.station_dir)
    rows = read_selection(args.selection)
    for r in rows:
        f = epochs.get((r["station"], "", r["channel"], r["start"]))
        if f is None:
            raise SystemExit(f"pinned epoch no longer listed: {r['station']} {r['channel']} {r['start']}")
        if f[16] != r["end"] or not epoch_is_standard(f):
            raise SystemExit(f"pinned epoch changed end/gain/sensor: {f}")
    print(f"station check ok: {len(rows)} pinned epochs listed as {EXPECTED_SENSOR} {EXPECTED_SCALE} counts/{EXPECTED_SCALE_UNITS} at {EXPECTED_RATE} sps")


def decode_epoch(r: dict[str, str], raw: bytes) -> tuple[list[tuple[datetime, array]], dict]:
    records = parse_records(raw, r["station"], r["channel"])
    segments, info = segment_records(records)
    start, end = parse_time(r["start"]), parse_time(r["end"])
    first, last = records[0][0], records[-1][0]
    if (first - start).total_seconds() < -GAP_TOLERANCE_S - 4096 or (last - end).total_seconds() > GAP_TOLERANCE_S:
        raise ValueError(f"records fall outside the pinned epoch: {first} .. {last}")
    nominal = int(r["nominal_values"])
    decoded = info["decoded_values"]
    if decoded > nominal + 1 or decoded < MIN_EPOCH_FRACTION * nominal:
        raise ValueError(f"decoded {decoded} values vs nominal {nominal} for the epoch")
    if r["expected_values"] and decoded != int(r["expected_values"]):
        raise ValueError(f"decoded {decoded} values != pinned {r['expected_values']}")
    if not segments:
        raise ValueError("no contiguous segment of at least MIN_SEGMENT_VALUES")
    info["nominal_values"] = nominal
    return segments, info


def check_payload(path: Path, r: dict[str, str]) -> bytes:
    raw = path.read_bytes()
    if r["mseed_sha256"] and hashlib.sha256(raw).hexdigest() != r["mseed_sha256"]:
        raise ValueError(f"{path.name}: sha256 differs from the pinned value")
    return raw


def cmd_inspect(args: argparse.Namespace) -> None:
    rows = {mseed_name(r): r for r in read_selection(args.selection)}
    r = rows.get(args.mseed.name.removesuffix(".part"))
    if r is None:
        raise SystemExit(f"{args.mseed.name}: not a pinned epoch")
    try:
        segments, info = decode_epoch(r, check_payload(args.mseed, r))
    except ValueError as exc:
        raise SystemExit(f"{args.mseed.name}: invalid payload: {exc}")
    print(json.dumps({"file": args.mseed.name, "bytes": args.mseed.stat().st_size,
                      "sha256": hashlib.sha256(args.mseed.read_bytes()).hexdigest(), **info}, sort_keys=True))


def segment_rows(args: argparse.Namespace):
    epochs = station_epochs(args.station_dir)
    for r in read_selection(args.selection):
        f = epochs.get((r["station"], "", r["channel"], r["start"]))
        if f is None or f[16] != r["end"] or not epoch_is_standard(f):
            raise SystemExit(f"pinned epoch missing or not standard gain: {r}")
        path = args.downloads / mseed_name(r)
        if not path.is_file():
            raise SystemExit(f"missing download {path}")
        raw = check_payload(path, r)
        segments, info = decode_epoch(r, raw)
        yield r, path, hashlib.sha256(raw).hexdigest(), segments, info


def value_stats(values: array) -> dict:
    counts = collections.Counter(values)
    top_value, top_count = counts.most_common(1)[0]
    return {"min_value": min(values), "max_value": max(values), "distinct_values": len(counts),
            "dominant_value": top_value, "dominant_fraction": round(top_count / len(values), 6)}


def to_le_bytes(values: array) -> bytes:
    out = array("i", values)
    if out.itemsize != 4:
        raise SystemExit("host array('i') is not 32-bit")
    if sys.byteorder == "big":
        out.byteswap()
    return out.tobytes()


def cmd_build(args: argparse.Namespace) -> None:
    dataset_dir = args.data_root / "samples" / DATASET_ID
    if dataset_dir.exists():
        shutil.rmtree(dataset_dir)
    for series_id in SERIES_BY_CHANNEL.values():
        (dataset_dir / series_id).mkdir(parents=True)
    index_rows, epoch_rows = [], []
    total_bytes = total_values = 0
    for r, path, sha, segments, info in segment_rows(args):
        for k, (seg_start, values) in enumerate(segments):
            st = value_stats(values)
            if st["distinct_values"] < 2 or st["dominant_fraction"] > MAX_DOMINANT_FRACTION:
                raise SystemExit(f"degenerate segment {path.name} #{k}: {st}")
            data = to_le_bytes(values)
            name = f"4P_{r['station']}_{r['channel']}_{stamp(r['start'])}_seg{k:02d}.bin"
            out = dataset_dir / SERIES_BY_CHANNEL[r["channel"]] / name
            out.write_bytes(data)
            index_rows.append({
                "dataset_id": DATASET_ID, "series_id": SERIES_BY_CHANNEL[r["channel"]],
                "sample_path": out.relative_to(args.data_root).as_posix(),
                "numeric_kind": "int", "bit_width": 32, "endianness": "little",
                "element_size_bytes": 4, "sample_size_bytes": len(data), "value_count": len(values),
                "sample_sha256": hashlib.sha256(data).hexdigest(),
                "network": NETWORK, "station": r["station"], "channel": r["channel"],
                "epoch_start": r["start"], "epoch_end": r["end"], "segment_index": k,
                "segment_start_utc": seg_start.isoformat(),
                "latitude": r["latitude"], "longitude": r["longitude"],
                "scale_counts_per_nT": EXPECTED_SCALE, "sample_rate_hz": 1.0,
                "source_file": path.relative_to(args.data_root).as_posix(), "source_sha256": sha,
                **st,
            })
            total_bytes += len(data)
            total_values += len(values)
        epoch_rows.append({"station": r["station"], "channel": r["channel"], "start": r["start"],
                           "source_bytes": path.stat().st_size, "source_sha256": sha, **info})
    if total_bytes > MAX_TOTAL_BYTES:
        raise SystemExit(f"primary output {total_bytes} exceeds cap")
    index = args.data_root / "index" / DATASET_ID / "samples.jsonl"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text("".join(json.dumps(x, sort_keys=True) + "\n" for x in index_rows), encoding="utf-8")
    stats_path = args.data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    per_series = collections.Counter()
    per_series_bytes = collections.Counter()
    for x in index_rows:
        per_series[x["series_id"]] += 1
        per_series_bytes[x["series_id"]] += x["sample_size_bytes"]
    summary = {"dataset_id": DATASET_ID, "series_sample_counts": dict(per_series),
               "series_total_size_bytes": dict(per_series_bytes), "epochs": len(epoch_rows),
               "sample_count": len(index_rows), "value_count": total_values, "total_size_bytes": total_bytes,
               "gaps": sum(e["gaps"] for e in epoch_rows), "overlaps": sum(e["overlaps"] for e in epoch_rows),
               "leap_second_continuations": sum(e["leap_second_continuations"] for e in epoch_rows),
               "short_fragments_dropped": sum(e["short_fragments_dropped"] for e in epoch_rows),
               "short_fragment_values_dropped": sum(e["short_fragment_values_dropped"] for e in epoch_rows)}
    stats_path.write_text(json.dumps({**summary, "per_epoch": epoch_rows}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


def cmd_verify(args: argparse.Namespace) -> None:
    index = args.data_root / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(ln) for ln in index.read_text(encoding="utf-8").splitlines() if ln.strip()]
    by_path = {x["sample_path"]: x for x in rows}
    if len(by_path) != len(rows):
        raise SystemExit("duplicate sample paths in index")
    expected_paths = set()
    total_bytes = total_values = 0
    epochs = 0
    for r, path, sha, segments, info in segment_rows(args):
        epochs += 1
        for k, (seg_start, values) in enumerate(segments):
            series_id = SERIES_BY_CHANNEL[r["channel"]]
            rel = f"samples/{DATASET_ID}/{series_id}/4P_{r['station']}_{r['channel']}_{stamp(r['start'])}_seg{k:02d}.bin"
            x = by_path.get(rel)
            if x is None:
                raise SystemExit(f"segment missing from index: {rel}")
            data = to_le_bytes(values)
            disk = (args.data_root / rel).read_bytes()
            if disk != data:
                raise SystemExit(f"sample bytes differ from re-decoded source: {rel}")
            # independent read-back of the stored little-endian int32 words
            back = struct.unpack(f"<{len(disk) // 4}i", disk)
            st = value_stats(array("i", back))
            if st["distinct_values"] < 2 or st["dominant_fraction"] > MAX_DOMINANT_FRACTION:
                raise SystemExit(f"degenerate sample {rel}: {st}")
            want = {"dataset_id": DATASET_ID, "series_id": series_id, "numeric_kind": "int", "bit_width": 32,
                    "endianness": "little", "element_size_bytes": 4, "sample_size_bytes": len(disk),
                    "value_count": len(back), "sample_sha256": hashlib.sha256(disk).hexdigest(),
                    "source_sha256": sha, "station": r["station"], "channel": r["channel"],
                    "segment_start_utc": seg_start.isoformat(), **st}
            for key, val in want.items():
                if x.get(key) != val:
                    raise SystemExit(f"index field {key} mismatch for {rel}: {x.get(key)!r} != {val!r}")
            expected_paths.add(rel)
            total_bytes += len(disk)
            total_values += len(back)
    if expected_paths != set(by_path):
        raise SystemExit("index lists samples not derivable from the pinned sources")
    on_disk = {p.relative_to(args.data_root).as_posix()
               for p in (args.data_root / "samples" / DATASET_ID).glob("*/*")}
    if on_disk != expected_paths:
        raise SystemExit("sample directory contents differ from the index")
    if total_bytes > MAX_TOTAL_BYTES:
        raise SystemExit("primary output exceeds cap")
    if len({x["station"] for x in rows}) < 10:
        raise SystemExit("fewer than 10 stations realized")
    print(json.dumps({"dataset_id": DATASET_ID, "verified_epochs": epochs, "verified_samples": len(rows),
                      "verified_values": total_values, "verified_bytes": total_bytes}, sort_keys=True))


# --------------------------------------------------------------------------
# Self-test on synthetic Steim2 records
# --------------------------------------------------------------------------
_GROUPS = ((1, None, 4, 8), (2, 1, 1, 30), (2, 2, 2, 15), (2, 3, 3, 10), (3, 0, 5, 6), (3, 1, 6, 5), (3, 2, 7, 4))


def _pack_word(dnib, count, bits, vals):
    w = 0 if dnib is None else dnib << 30
    mask = (1 << bits) - 1
    for j, v in enumerate(vals):
        w |= (v & mask) << (bits * (count - 1 - j))
    return w


def _steim2_encode(samples: list[int], prev: int, rng: random.Random, nframes: int, used: set | None = None) -> bytes | None:
    d0 = samples[0] - prev  # ignored by decoders; zeroed when it does not fit 30 bits
    diffs = [d0 if -(1 << 29) <= d0 < (1 << 29) else 0] + [b - a for a, b in zip(samples, samples[1:])]
    words_ctrl = []  # (code, word)
    i = 0
    while i < len(diffs):
        fits = [g for g in _GROUPS if i + g[2] <= len(diffs)
                and all(-(1 << (g[3] - 1)) <= d < (1 << (g[3] - 1)) for d in diffs[i:i + g[2]])]
        if not fits:
            fits = [g for g in _GROUPS if g[2] == 1]
            if not all(-(1 << 29) <= d < (1 << 29) for d in diffs[i:i + 1]):
                raise ValueError("difference too large for synthetic encoder")
        code, dnib, count, bits = rng.choice(fits)
        if used is not None:
            used.add((code, dnib))
        words_ctrl.append((code, _pack_word(dnib, count, bits, diffs[i:i + count])))
        i += count
    capacity = nframes * 15 - 2
    if len(words_ctrl) > capacity:
        return None
    out = bytearray()
    k = 0
    for f in range(nframes):
        ctrl, ws = 0, []
        for wi in range(1, 16):
            if f == 0 and wi == 1:
                ws.append(samples[0] & 0xFFFFFFFF)
            elif f == 0 and wi == 2:
                ws.append(samples[-1] & 0xFFFFFFFF)
            elif k < len(words_ctrl):
                code, w = words_ctrl[k]
                ctrl |= code << (30 - 2 * wi)
                ws.append(w)
                k += 1
            else:
                ws.append(0)
        out += struct.pack(">16I", ctrl, *ws)
    return bytes(out)


def _record(seq: int, station: str, channel: str, start: datetime, samples: list[int], payload: bytes) -> bytes:
    tt = start.timetuple()
    hdr = bytearray(48)
    hdr[0:6] = f"{seq:06d}".encode()
    hdr[6:8] = b"D "
    hdr[8:13] = station.ljust(5).encode()
    hdr[13:15] = b"  "
    hdr[15:18] = channel.encode()
    hdr[18:20] = NETWORK.encode()
    struct.pack_into(">HHBBBBH", hdr, 20, start.year, tt.tm_yday, start.hour, start.minute, start.second, 0, 0)
    struct.pack_into(">Hhh", hdr, 30, len(samples), 1, 1)
    hdr[39] = 1
    struct.pack_into(">HH", hdr, 44, 64, 48)
    b1000 = struct.pack(">HHBBBB", 1000, 0, 11, 1, 9, 0) + b"\0" * 8
    rec = bytes(hdr) + b1000 + payload
    assert len(rec) == 512
    return rec


def cmd_selftest(_args: argparse.Namespace) -> None:
    rng = random.Random(20261008)
    station, channel = "TST01", "LFN"
    raw = bytearray()
    truth: list[list[int]] = [[]]
    t = datetime(2015, 6, 30, 23, 0, 0)
    value, prev, seq = 2_271_241, 0, 1
    starts = []
    used: set = set()
    for block in range(6):
        if block == 4:
            t += timedelta(seconds=600)  # data gap -> new segment
            value = -1_500_000_000      # negative X0 after the gap
            truth.append([])
        samples = []
        for k in range(rng.randint(60, 200)):
            if k % 8 == 0:  # runs of one difference regime so every packing fits somewhere
                lim = rng.choice([7, 15, 31, 127, 500, 16000, 500000])
            value += rng.randint(-lim, lim)
            samples.append(value)
        if block == 1:
            samples[1] = samples[0] - 400_000_000  # 30-bit differences
            samples[2] = samples[1] + 500_000_000
        payload = None
        while payload is None:
            payload = _steim2_encode(samples, prev, rng, 7, used)
            if payload is None:
                samples = samples[: len(samples) * 3 // 4]
        assert steim2_decode(payload, len(samples)) == samples, "Steim2 decode mismatch"
        raw += _record(seq, station, channel, t, samples, payload)
        starts.append(t)
        truth[-1].extend(samples)
        seq, prev = seq + 1, samples[-1]
        t += timedelta(seconds=len(samples))
    assert used == {(g[0], g[1]) for g in _GROUPS}, used
    records = parse_records(bytes(raw), station, channel)
    assert [s for s, _ in records] == starts
    segs, info = segment_records(records, min_values=1)
    assert [list(v) for _, v in segs] == truth and info["gaps"] == 1, info
    _, info_min = segment_records(records)
    assert info_min["segments_kept"] == 0 and info_min["short_fragments_dropped"] == 2, info_min
    # leap second: the second record starts at 2015-07-01T00:00:00 one naive second early
    r0, r1 = records[0], records[1]
    leap = datetime(2015, 7, 1)
    _, info_l = segment_records([(leap - timedelta(seconds=len(r0[1]) - 1), r0[1]), (leap, r1[1])], min_values=1)
    assert info_l["leap_second_continuations"] == 1 and info_l["segments_total"] == 1, info_l
    other = datetime(2015, 5, 1)
    _, info_o = segment_records([(other - timedelta(seconds=len(r0[1]) - 1), r0[1]), (other, r1[1])], min_values=1)
    assert info_o["overlaps"] == 1 and info_o["segments_total"] == 2, info_o
    # corruption of a difference word must trip the reverse integration constant
    bad = bytearray(raw)
    bad[64 + 64 + 4 * 5 + 3] ^= 0x01
    try:
        parse_records(bytes(bad), station, channel)
    except ValueError:
        pass
    else:
        raise AssertionError("corrupted Steim2 frame not detected")
    try:
        parse_records(bytes(raw), station, "LQN")
    except ValueError:
        pass
    else:
        raise AssertionError("foreign channel accepted")
    le = to_le_bytes(array("i", truth[1]))
    assert list(struct.unpack(f"<{len(le) // 4}i", le)) == truth[1]
    print(f"selftest ok: {len(records)} synthetic Steim2 records, {sum(len(v) for _, v in records)} values, "
          f"7 packing types, 30-bit jumps, negative X0, gap split, leap-second and overlap rules, corruption detected")


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("selftest")
    s = sub.add_parser("select")
    s.add_argument("--station-dir", type=Path, required=True)
    s.add_argument("--double-years", default="2012,2015,2016")
    s = sub.add_parser("check-station")
    s.add_argument("--station-dir", type=Path, required=True)
    s.add_argument("--selection", type=Path, required=True)
    s = sub.add_parser("inspect")
    s.add_argument("--selection", type=Path, required=True)
    s.add_argument("--mseed", type=Path, required=True)
    for name in ("build", "verify"):
        s = sub.add_parser(name)
        s.add_argument("--selection", type=Path, required=True)
        s.add_argument("--station-dir", type=Path, required=True)
        s.add_argument("--downloads", type=Path, required=True)
        s.add_argument("--data-root", type=Path, required=True)
    args = p.parse_args()
    {"selftest": cmd_selftest, "select": cmd_select, "check-station": cmd_check_station, "inspect": cmd_inspect,
     "build": cmd_build, "verify": cmd_verify}[args.cmd](args)


if __name__ == "__main__":
    main()
