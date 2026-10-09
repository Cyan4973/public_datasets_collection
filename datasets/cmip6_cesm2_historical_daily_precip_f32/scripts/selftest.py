#!/usr/bin/env python3
"""Synthetic self-test for h5lite.py and cesm2_pr.py (no network, no real data).

* lookup3 against Bob Jenkins' reference vectors;
* 4-byte HDF5 shuffle / unshuffle vectors, round trip, and agreement between
  h5lite.unshuffle and the independent per-element verify_unshuffle4;
* noleap calendar vectors for both date implementations;
* an end-to-end synthetic NetCDF4-like file mirroring the real CESM2 layout at
  a small size: superblock v0 with root symbol-table entry pointing at a
  version-2 object header, compact links, compact attributes (string, f32 and
  f64), pr (time, lat, lon) float32 LE chunked one time step per chunk with
  shuffle(4)+deflate (filter pipeline v1 with names), chunks stored out of
  order, a time axis chunked 4 steps per chunk with a padded final chunk,
  time_bnds chunked (1, 2), lat/lon coordinates; build() must reproduce every
  field byte for byte, and verify() must pass;
* corruption cases must be rejected: big-endian datatype, a fletcher32 filter,
  a nonzero chunk filter mask, a missing chunk, a NaN, the 1e20 fill value,
  a constant field, a time gap, a wrong variant_label, a damaged metadata
  checksum, a tampered sample, and an orphan sample file.
"""
from __future__ import annotations

import json
import random
import shutil
import struct
import sys
import tempfile
import zlib
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cesm2_pr as cp  # noqa: E402
import h5lite  # noqa: E402
from h5lite import UNDEF, H5Error, lookup3  # noqa: E402

T, Y, X = 5, 4, 8
TIME_CHUNK = 4
F32_BE = bytes.fromhex("11211f000400000000002000170800177f000000")
GLOBAL_ATTRS = dict(cp.SPEC["global_attrs"])
LICENSE = ("CMIP6 model data produced by <The National Center for Atmospheric Research> is licensed under a "
           "Creative Commons Attribution-[]ShareAlike 4.0 International License (https://creativecommons.org/licenses/).")
SPEC = dict(cp.SPEC, file_size=None, n_time=T, n_lat=Y, n_lon=X, date_first="19400101", date_last="19400105",
            min_distinct_values=10, check_coords=True)


def check(condition: bool, what: str) -> None:
    if not condition:
        raise SystemExit(f"selftest FAILED: {what}")


def expect_error(fn, what: str) -> None:
    try:
        fn()
    except (cp.RecipeError, H5Error):
        return
    raise SystemExit(f"selftest FAILED: {what} was not rejected")


def test_units() -> None:
    check(lookup3(b"") == 0xDEADBEEF, "lookup3 empty")
    check(lookup3(b"Four score and seven years ago") == 0x17770551, "lookup3 vector 1")
    check(lookup3(b"Four score and seven years ago", 1) == 0xCD628161, "lookup3 vector 2")
    data = bytes(range(12))
    shuffled = bytes([0, 4, 8, 1, 5, 9, 2, 6, 10, 3, 7, 11])
    check(h5lite.shuffle(data, 4) == shuffled, "forward shuffle vector")
    check(h5lite.unshuffle(shuffled, 4) == data, "unshuffle vector")
    check(cp.verify_unshuffle4(shuffled) == data, "independent unshuffle vector")
    blob = bytes((i * 37 + 11) & 0xFF for i in range(4099))  # odd tail bytes
    check(h5lite.unshuffle(h5lite.shuffle(blob, 4), 4) == blob, "shuffle round trip with tail")
    check(cp.verify_unshuffle4(h5lite.shuffle(blob, 4)) == blob, "independent unshuffle with tail")
    for days, want in ((0, "00010101"), (707735, "19400101"), (707735 + 58, "19400228"), (707735 + 59, "19400301"),
                       (707735 + 364, "19401231"), (711384, "19491231"), (711385, "19500101")):
        check(cp.noleap_date(days) == want, f"noleap_date({days})")
        check(cp.verify_date(days) == want, f"verify_date({days})")
    expect_error(lambda: cp.noleap_date(707735.5), "fractional time")
    vals = [0.0, -0.0, -1e-12, 3.5e-5] + [1e-6 * (i + 1) for i in range(20)]
    raw = struct.pack(f"<{len(vals)}f", *vals)
    a = cp.field_stats(raw, SPEC)
    b = cp.verify_stats(raw, SPEC)
    check(a == b, f"stats paths disagree: {a} vs {b}")
    check(a["zero_values"] == 2 and a["negative_values"] == 1 and a["distinct_values"] == 23, f"stats {a}")


# --------------------------------------------------- synthetic HDF5 writer
def checksummed(body: bytes) -> bytes:
    return body + struct.pack("<I", lookup3(body))


def message(mtype: int, payload: bytes) -> bytes:
    return struct.pack("<BHB", mtype, len(payload), 0) + payload


def ohdr(messages: list[tuple[int, bytes]]) -> bytes:
    body = b"".join(message(t, p) for t, p in messages)
    return checksummed(b"OHDR" + bytes([2, 0x02]) + struct.pack("<I", len(body)) + body)


def dataspace(dims: tuple[int, ...]) -> bytes:
    return bytes([2, len(dims), 0, 1]) + struct.pack(f"<{len(dims)}Q", *dims)


def attr(name: str, datatype: bytes, space: bytes, data: bytes) -> bytes:
    raw_name = name.encode() + b"\x00"
    return (bytes([3, 0]) + struct.pack("<HHH", len(raw_name), len(datatype), len(space)) + b"\x00"
            + raw_name + datatype + space + data)


def str_attr(name: str, value: str) -> bytes:
    raw = value.encode()
    return attr(name, bytes([0x13, 0, 0, 0]) + struct.pack("<I", len(raw)), bytes([2, 0, 0, 0]), raw)


def f32_attr(name: str, value: float) -> bytes:
    return attr(name, cp.F32LE, dataspace((1,)), struct.pack("<f", value))


def f64_attr(name: str, value: float) -> bytes:
    return attr(name, cp.F64LE, dataspace((1,)), struct.pack("<d", value))


def link_payload(name: str, addr: int, order: int) -> bytes:
    raw = name.encode()
    return bytes([1, 0x04]) + struct.pack("<Q", order) + bytes([len(raw)]) + raw + struct.pack("<Q", addr)


def filters_v1(entries: list[tuple[int, str, list[int]]]) -> bytes:
    out = bytes([1, len(entries)]) + b"\x00" * 6
    for fid, name, values in entries:
        nm = name.encode() + b"\x00"
        nm += b"\x00" * ((8 - len(nm) % 8) % 8)
        out += struct.pack("<4H", fid, len(nm), 1, len(values)) + nm + struct.pack(f"<{len(values)}I", *values)
        if len(values) % 2:
            out += b"\x00" * 4
    return out


SHUF_DEFL4 = filters_v1([(2, "shuffle", [4]), (1, "deflate", [2])])
SHUF_DEFL8 = filters_v1([(2, "shuffle", [8]), (1, "deflate", [2])])


def tree_leaf(entries: list[tuple[int, int, tuple[int, ...], int]], final: tuple[int, ...]) -> bytes:
    """entries: (stored size, filter mask, offsets incl. trailing 0, address)."""
    body = b"TREE" + bytes([1, 0]) + struct.pack("<H", len(entries)) + struct.pack("<QQ", UNDEF, UNDEF)
    for size, mask, offsets, addr in entries:
        body += struct.pack("<II", size, mask) + struct.pack(f"<{len(offsets)}Q", *offsets) + struct.pack("<Q", addr)
    body += struct.pack("<II", 0, 0) + struct.pack(f"<{len(final)}Q", *final)
    return body


def align(buf: bytearray) -> None:
    while len(buf) % 8:
        buf.append(0)


def make_fields(opts: dict) -> list[list[float]]:
    rng = random.Random(7)
    fields = []
    for t in range(T):
        vals = []
        for i in range(Y * X):
            r = rng.random()
            vals.append(0.0 if r < 0.1 else (-3e-12 if r < 0.13 else rng.lognormvariate(-11, 1.5)))
        fields.append(vals)
    if opts.get("nan"):
        fields[2][5] = float("nan")
    if opts.get("fill"):
        fields[3][7] = 1e20
    if opts.get("constant"):
        fields[1] = [2.5e-5] * (Y * X)
    return fields


def build_file(opts: dict | None = None) -> tuple[bytes, list[bytes]]:
    opts = opts or {}
    buf = bytearray(b"\x00" * 96)
    headers: dict[str, int] = {}

    def chunked_dataset(name: str, arrays: list[bytes], chunk_offsets: list[tuple[int, ...]], final: tuple[int, ...],
                        msgs: list[tuple[int, bytes]], esize: int, order=None, masks=None, skip=None):
        entries = []
        order = order if order is not None else range(len(arrays))
        for k in order:
            if skip is not None and k == skip:
                continue
            stored = zlib.compress(h5lite.shuffle(arrays[k], esize), 2)
            entries.append((len(stored), (masks or {}).get(k, 0), chunk_offsets[k], len(buf)))
            buf.extend(stored)
        align(buf)
        btree = len(buf)
        buf.extend(tree_leaf(entries, final))
        align(buf)
        headers[name] = len(buf)
        out = []
        for mtype, payload in msgs:
            if mtype == 0x08:
                payload = payload[:3] + struct.pack("<Q", btree) + payload[11:]
            out.append((mtype, payload))
        buf.extend(ohdr(out))

    def layout(dims: tuple[int, ...]) -> bytes:
        return bytes([3, 2, len(dims)]) + struct.pack("<Q", 0) + struct.pack(f"<{len(dims)}I", *dims)

    fields = make_fields(opts)
    originals = [struct.pack(f"<{Y * X}f", *v) for v in fields]
    pr_filters = SHUF_DEFL4
    if opts.get("fletcher"):
        pr_filters = filters_v1([(2, "shuffle", [4]), (1, "deflate", [2]), (3, "fletcher32", [])])
    pr_msgs = [(0x01, dataspace((T, Y, X))), (0x03, F32_BE if opts.get("big_endian") else cp.F32LE),
               (0x05, bytes([2, 3, 2, 1]) + struct.pack("<I", 4) + cp.FILL_F32_BYTES),
               (0x0B, pr_filters), (0x08, layout((1, Y, X, 4))),
               (0x0C, str_attr("units", "kg m-2 s-1")), (0x0C, str_attr("standard_name", "precipitation_flux")),
               (0x0C, str_attr("cell_methods", "area: time: mean")), (0x0C, f32_attr("_FillValue", 1e20)),
               (0x0C, f64_attr("missing_value", 1e20))]
    chunked_dataset("pr", originals, [(t, 0, 0, 0) for t in range(T)], (T, 0, 0, 0), pr_msgs, 4,
                    order=[3, 0, 4, 1, 2], masks={1: 1} if opts.get("mask") else None,
                    skip=2 if opts.get("drop_chunk") else None)
    times = [707735.0 + t for t in range(T)]
    if opts.get("time_gap"):
        times[3] += 1.0
    padded = times + [0.0] * (TIME_CHUNK * 2 - T)
    t_arrays = [struct.pack(f"<{TIME_CHUNK}d", *padded[k * TIME_CHUNK:(k + 1) * TIME_CHUNK]) for k in range(2)]
    t_msgs = [(0x01, dataspace((T,))), (0x03, cp.F64LE), (0x0B, SHUF_DEFL8), (0x08, layout((TIME_CHUNK, 8))),
              (0x0C, str_attr("units", "days since 0001-01-01 00:00:00")), (0x0C, str_attr("calendar", "noleap"))]
    chunked_dataset("time", t_arrays, [(0, 0), (TIME_CHUNK, 0)], (2 * TIME_CHUNK, 0), t_msgs, 8)
    b_arrays = [struct.pack("<2d", t - 1.0, t) for t in times]
    b_msgs = [(0x01, dataspace((T, 2))), (0x03, cp.F64LE), (0x0B, SHUF_DEFL8), (0x08, layout((1, 2, 8)))]
    chunked_dataset("time_bnds", b_arrays, [(t, 0, 0) for t in range(T)], (T, 0, 0), b_msgs, 8)
    lat = struct.pack(f"<{Y}d", -90.0, -30.0, 30.0, 90.0)
    lon = struct.pack(f"<{X}d", *[1.25 * i for i in range(X)])
    for name, arr, n in (("lat", lat, Y), ("lon", lon, X)):
        msgs = [(0x01, dataspace((n,))), (0x03, cp.F64LE), (0x0B, SHUF_DEFL8), (0x08, layout((n, 8)))]
        chunked_dataset(name, [arr], [(0, 0)], (n, 0), msgs, 8)
    gattrs = dict(GLOBAL_ATTRS)
    if opts.get("bad_variant"):
        gattrs["variant_label"] = "r2i1p1f1"
    root_msgs = [(0x06, link_payload(n, headers[n], k)) for k, n in enumerate(["pr", "lat", "lon", "time", "time_bnds"])]
    root_msgs += [(0x0C, str_attr(k, v)) for k, v in gattrs.items()] + [(0x0C, str_attr("license", LICENSE))]
    align(buf)
    root_addr = len(buf)
    buf.extend(ohdr(root_msgs))
    eof = len(buf)
    sb = bytearray(b"\x89HDF\r\n\x1a\n" + bytes([0, 0, 0, 0, 0, 8, 8, 0]) + struct.pack("<HHI", 4, 16, 0))
    sb += struct.pack("<4Q", 0, UNDEF, eof, UNDEF)
    sb += struct.pack("<QQII", 0, root_addr, 0, 0) + b"\x00" * 16
    check(len(sb) == 96, "superblock v0 length")
    buf[0:96] = sb
    return bytes(buf), originals


def run_build(tmp: Path, raw: bytes, label: str) -> tuple[Path, Path, dict]:
    root = tmp / label
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    src = root / "source.nc"
    src.write_bytes(raw)
    spec = dict(SPEC, file_size=len(raw))
    summary = cp.build(src, root, spec, log=lambda *_: None)
    return root, src, summary


def test_end_to_end(tmp: Path) -> None:
    raw, originals = build_file()
    root, src, summary = run_build(tmp, raw, "good")
    spec = dict(SPEC, file_size=len(raw))
    check(summary["samples"] == T and summary["total_size_bytes"] == T * Y * X * 4, f"summary {summary}")
    rows = [json.loads(x) for x in (root / "index" / cp.DATASET_ID / "samples.jsonl").read_text().splitlines()]
    check([r["date_label"] for r in rows] == [f"194001{d:02d}" for d in range(1, T + 1)], "date labels")
    for t, row in enumerate(rows):
        data = (root / row["sample_path"]).read_bytes()
        check(data == originals[t], f"field {t} bytes differ from the original")
        vals = struct.unpack(f"<{Y * X}f", data)
        check(row["min"] == min(vals) and row["max"] == max(vals), "index min/max from stored f32")
        check(row["time_bnds"] == [707734.0 + t, 707735.0 + t], f"time_bnds row {t}")
    cp.verify(src, root, None, spec, log=lambda *_: None)
    sample = root / rows[1]["sample_path"]
    good = sample.read_bytes()
    sample.write_bytes(good[:-4] + struct.pack("<f", 1e-7))
    expect_error(lambda: cp.verify(src, root, None, spec, log=lambda *_: None), "tampered sample")
    sample.write_bytes(good)
    orphan = sample.parent / "pr_day_19391231.bin"
    orphan.write_bytes(good)
    expect_error(lambda: cp.verify(src, root, None, spec, log=lambda *_: None), "orphan sample file")
    orphan.unlink()
    cp.verify(src, root, None, spec, log=lambda *_: None)
    bad = bytearray(raw)
    root_addr = struct.unpack_from("<Q", bad, 64)[0]
    bad[root_addr + 20] ^= 0xFF
    expect_error(lambda: run_build(tmp, bytes(bad), "badsum"), "corrupted root object header")


def test_rejections(tmp: Path) -> None:
    cases = {
        "big_endian": "big-endian datatype",
        "fletcher": "fletcher32 filter in pipeline",
        "mask": "nonzero chunk filter mask",
        "drop_chunk": "missing chunk",
        "nan": "NaN value",
        "fill": "1e20 fill value",
        "constant": "constant field",
        "time_gap": "time gap",
        "bad_variant": "wrong variant_label",
    }
    for key, what in cases.items():
        raw, _ = build_file({key: True})
        expect_error(lambda raw=raw, key=key: run_build(tmp, raw, key), what)


def main() -> int:
    test_units()
    tmp = Path(tempfile.mkdtemp(prefix="cesm2_pr_selftest_"))
    try:
        test_end_to_end(tmp)
        test_rejections(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("selftest ok: lookup3, 4-byte shuffle (two implementations), noleap calendar, stats paths, "
          "synthetic superblock-v0 NetCDF4 build/verify, 12 rejection cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
