#!/usr/bin/env python3
"""Pure-stdlib GRIB2 reader for the ECMWF open-data 0p4-beta vo/500 hPa message.

Subcommands
  pick-index <index_file> <yyyymmdd>
      Validate an ECMWF open-data JSON-lines .index file and print
      "<offset> <length>" for the single param=vo, levelist=500, step=24 line.
  check <grib_file> <yyyymmdd>
      Fully parse one GRIB2 message and assert the pinned layout (used by
      download.sh to reject semantically invalid payloads).
  build <data_dir> <dataset_id>
      Decode every downloaded message into little-endian uint16 code samples
      and write the sample index.

The parser walks sections 0-8 and asserts every structural property the recipe
depends on; any deviation is fatal.
"""
from __future__ import annotations

import array
import hashlib
import json
import struct
import sys
from pathlib import Path

DATASET_ID = "ecmwf_opendata_ifs_vo500_grib_u16"
SERIES_ID = "vo500_packed_codes_u16"
NI, NJ = 900, 451
NPTS = NI * NJ  # 405900
MSG_LEN = 811996
BITS = 16


def sm16(raw: int) -> int:
    """GRIB2 sign-magnitude 16-bit integer."""
    return -(raw & 0x7FFF) if raw & 0x8000 else raw


def sm32(raw: int) -> int:
    """GRIB2 sign-magnitude 32-bit integer."""
    return -(raw & 0x7FFFFFFF) if raw & 0x80000000 else raw


class GribError(ValueError):
    pass


def need(cond: bool, msg: str) -> None:
    if not cond:
        raise GribError(msg)


def parse_message(buf: bytes, date: str) -> dict:
    need(len(buf) == MSG_LEN, f"message length {len(buf)} != {MSG_LEN}")
    need(buf[:4] == b"GRIB", "missing GRIB magic")
    need(buf[-4:] == b"7777", "missing 7777 end marker")
    discipline, edition = buf[6], buf[7]
    total = struct.unpack(">Q", buf[8:16])[0]
    need(edition == 2, f"edition {edition} != 2")
    need(discipline == 0, f"discipline {discipline} != 0")
    need(total == MSG_LEN, f"section0 total length {total} != {MSG_LEN}")

    sections: dict[int, bytes] = {}
    order: list[int] = []
    pos = 16
    while pos < len(buf) - 4:
        need(pos + 5 <= len(buf) - 4, "truncated section header")
        length, num = struct.unpack(">IB", buf[pos:pos + 5])
        need(length >= 5 and pos + length <= len(buf) - 4, f"bad section {num} length {length}")
        need(num not in sections, f"repeated section {num} (multi-field message)")
        sections[num] = buf[pos:pos + length]
        order.append(num)
        pos += length
    need(pos == len(buf) - 4, "sections do not end at 7777")
    need(order in ([1, 2, 3, 4, 5, 6, 7], [1, 3, 4, 5, 6, 7]), f"unexpected section order {order}")

    s1 = sections[1]
    centre = struct.unpack(">H", s1[5:7])[0]
    year = struct.unpack(">H", s1[12:14])[0]
    month, day, hour, minute, second = s1[14], s1[15], s1[16], s1[17], s1[18]
    need(centre == 98, f"originating centre {centre} != 98 (ECMWF)")
    need(s1[11] == 1, f"significance of reference time {s1[11]} != 1 (start of forecast)")
    ref = f"{year:04d}{month:02d}{day:02d}"
    need(ref == date, f"reference date {ref} != {date}")
    need((hour, minute, second) == (0, 0, 0), f"reference time {hour:02d}{minute:02d}{second:02d} != 000000")
    need(s1[20] == 1, f"type of data {s1[20]} != 1 (forecast)")

    s3 = sections[3]
    need(s3[5] == 0, "grid definition source != 0")
    npts3 = struct.unpack(">I", s3[6:10])[0]
    tmpl3 = struct.unpack(">H", s3[12:14])[0]
    need(npts3 == NPTS, f"section3 points {npts3} != {NPTS}")
    need(tmpl3 == 0, f"grid template {tmpl3} != 0 (regular lat/lon)")
    need(len(s3) == 72, f"section3 length {len(s3)} != 72")
    ni, nj = struct.unpack(">II", s3[30:38])
    la1, lo1 = (sm32(v) for v in struct.unpack(">II", s3[46:54]))
    la2, lo2, di, dj = struct.unpack(">IIII", s3[55:71])
    la2, lo2 = sm32(la2), sm32(lo2)
    scan = s3[71]
    need((ni, nj) == (NI, NJ), f"grid {ni}x{nj} != {NI}x{NJ}")
    need((la1, lo1, la2, lo2) == (90000000, 180000000, -90000000, 179600000),
         f"grid corners {(la1, lo1, la2, lo2)} differ")
    need((di, dj) == (400000, 400000), f"increments {(di, dj)} != 0.4 deg")
    need(scan == 0, f"scanning mode {scan} != 0")

    s4 = sections[4]
    ncoord, tmpl4 = struct.unpack(">HH", s4[5:9])
    need(ncoord == 0 and tmpl4 == 0, f"product template {tmpl4} (ncoord {ncoord}) != 4.0")
    cat, num = s4[9], s4[10]
    need((cat, num) == (2, 12), f"parameter {cat}/{num} != 2/12 (relative vorticity)")
    unit = s4[17]
    fstep = struct.unpack(">I", s4[18:22])[0]
    need(unit == 1 and fstep == 24, f"forecast time unit {unit} value {fstep} != 24 h")
    surf, sscale = s4[22], s4[23]
    sval = struct.unpack(">I", s4[24:28])[0]
    need((surf, sscale, sval) == (100, 0, 50000), f"surface {(surf, sscale, sval)} != isobaric 50000 Pa")

    s5 = sections[5]
    npts5, tmpl5 = struct.unpack(">IH", s5[5:11])
    need(npts5 == NPTS, f"section5 points {npts5} != {NPTS}")
    need(tmpl5 == 0, f"data representation template {tmpl5} != 0 (simple packing)")
    ref_value = struct.unpack(">f", s5[11:15])[0]
    bin_scale = sm16(struct.unpack(">H", s5[15:17])[0])
    dec_scale = sm16(struct.unpack(">H", s5[17:19])[0])
    nbits = s5[19]
    need(nbits == BITS, f"bits per value {nbits} != {BITS}")
    need(s5[20] == 0, f"type of original values {s5[20]} != 0 (floating point)")

    s6 = sections[6]
    need(len(s6) == 6 and s6[5] == 255, f"bitmap indicator {s6[5] if len(s6) > 5 else None} != 255")

    s7 = sections[7]
    need(len(s7) == 5 + 2 * NPTS, f"section7 length {len(s7)} != {5 + 2 * NPTS}")
    codes = array.array("H")
    need(codes.itemsize == 2, "platform uint16 array item size != 2")
    codes.frombytes(s7[5:])
    if sys.byteorder == "little":
        codes.byteswap()  # GRIB stores big-endian; now native == little-endian
    return {
        "reference_value_R": ref_value,
        "binary_scale_E": bin_scale,
        "decimal_scale_D": dec_scale,
        "bits_per_value": nbits,
        "codes": codes,
        "has_section2": 2 in sections,
    }


def le_bytes(codes: array.array) -> bytes:
    if sys.byteorder == "little":
        return codes.tobytes()
    swapped = array.array("H", codes)
    swapped.byteswap()
    return swapped.tobytes()


def pick_index(index_file: str, date: str) -> None:
    hits = []
    lines = 0
    for raw in Path(index_file).read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        lines += 1
        rec = json.loads(raw)  # malformed JSON (e.g. an XML error page) is fatal
        need(isinstance(rec, dict) and "_offset" in rec and "_length" in rec, "index line lacks _offset/_length")
        if rec.get("param") == "vo" and rec.get("levelist") == "500":
            hits.append(rec)
    need(lines >= 50, f"index has only {lines} lines")
    need(len(hits) == 1, f"expected exactly one vo/500 line, found {len(hits)}")
    rec = hits[0]
    expect = {"domain": "g", "date": date, "time": "0000", "class": "od", "type": "fc",
              "stream": "oper", "step": "24", "levtype": "pl", "expver": "0001"}
    for key, val in expect.items():
        need(rec.get(key) == val, f"index {key}={rec.get(key)!r} != {val!r}")
    need(int(rec["_length"]) == MSG_LEN, f"index _length {rec['_length']} != {MSG_LEN}")
    print(int(rec["_offset"]), int(rec["_length"]))


def check(grib_file: str, date: str) -> None:
    info = parse_message(Path(grib_file).read_bytes(), date)
    codes = info["codes"]
    print(f"ok date={date} R={info['reference_value_R']!r} E={info['binary_scale_E']} "
          f"D={info['decimal_scale_D']} code_min={min(codes)} code_max={max(codes)}")


def build(data_dir: str, dataset_id: str) -> None:
    root = Path(data_dir)
    dl = root / "downloads" / dataset_id
    plan_path = dl / "messages.tsv"
    need(plan_path.is_file(), f"missing {plan_path}; run download.sh")
    rows = []
    for line in plan_path.read_text().splitlines()[1:]:
        date, offset, length, sha256, url = line.split("\t")
        rows.append((date, int(offset), int(length), sha256, url))
    need(rows == sorted(rows), "messages.tsv not sorted by date")
    out_dir = root / "samples" / dataset_id / SERIES_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.bin"):
        stale.unlink()
    idx_dir = root / "index" / dataset_id
    idx_dir.mkdir(parents=True, exist_ok=True)
    filt_dir = root / "filtered" / dataset_id
    filt_dir.mkdir(parents=True, exist_ok=True)
    index_rows = []
    seen = set()
    for date, offset, length, sha256, url in rows:
        src = dl / "grib" / f"{date}.grib2"
        buf = src.read_bytes()
        need(hashlib.sha256(buf).hexdigest() == sha256, f"{date}: source sha256 mismatch")
        info = parse_message(buf, date)
        codes = info["codes"]
        cmin, cmax = min(codes), max(codes)
        need(cmax > cmin, f"{date}: constant field")
        need(cmax >= 256, f"{date}: code_max {cmax} does not use the upper byte")
        data = le_bytes(codes)
        digest = hashlib.sha256(data).hexdigest()
        need(digest not in seen, f"{date}: duplicate sample")
        seen.add(digest)
        rel = f"samples/{dataset_id}/{SERIES_ID}/{date}.bin"
        (root / rel).write_bytes(data)
        R, E, D = info["reference_value_R"], info["binary_scale_E"], info["decimal_scale_D"]
        index_rows.append({
            "dataset_id": dataset_id,
            "series_id": SERIES_ID,
            "sample_path": rel,
            "numeric_kind": "uint",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "sample_size_bytes": len(data),
            "value_count": len(codes),
            "sample_shape": [NJ, NI],
            "sample_axes": ["latitude_north_to_south", "longitude_eastward_from_180"],
            "run_date": date,
            "run_time_utc": "00:00",
            "forecast_step_hours": 24,
            "grib_reference_value_R": R,
            "grib_binary_scale_E": E,
            "grib_decimal_scale_D": D,
            "grib_bits_per_value": info["bits_per_value"],
            "physical_value_formula": "vo_s-1 = (R + X * 2**E) / 10**D",
            "code_min": cmin,
            "code_max": cmax,
            "distinct_codes": len(set(codes)),
            "vo_min_s-1": (R + cmin * 2.0 ** E) / 10.0 ** D,
            "vo_max_s-1": (R + cmax * 2.0 ** E) / 10.0 ** D,
            "source_url": url,
            "source_byte_offset": offset,
            "source_byte_length": length,
            "source_message_sha256": sha256,
            "sample_sha256": digest,
        })
    with open(idx_dir / "samples.jsonl", "w") as fh:
        for row in index_rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    with open(filt_dir / "packing_params.tsv", "w") as fh:
        fh.write("run_date\tR\tE\tD\tcode_min\tcode_max\n")
        for row in index_rows:
            fh.write(f"{row['run_date']}\t{row['grib_reference_value_R']!r}\t{row['grib_binary_scale_E']}\t"
                     f"{row['grib_decimal_scale_D']}\t{row['code_min']}\t{row['code_max']}\n")
    total = sum(r["sample_size_bytes"] for r in index_rows)
    es = sorted({r["grib_binary_scale_E"] for r in index_rows})
    print(f"built samples={len(index_rows)} bytes={total} values={sum(r['value_count'] for r in index_rows)} "
          f"E_values={es}")


def main(argv: list[str]) -> int:
    if len(argv) == 4 and argv[1] == "pick-index":
        pick_index(argv[2], argv[3])
    elif len(argv) == 4 and argv[1] == "check":
        check(argv[2], argv[3])
    elif len(argv) == 4 and argv[1] == "build":
        build(argv[2], argv[3])
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except (GribError, json.JSONDecodeError, KeyError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
