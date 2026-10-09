#!/usr/bin/env python3
"""Validation suite for tools/laz/laszip.py against public LAS/LAZ fixtures.

Fetch the fixtures first (about 9.5 MB):

    bash tools/laz/fetch_fixtures.sh
    python3 -m unittest tools/laz/test_laszip.py      # or: python3 tools/laz/test_laszip.py

Fixtures are looked up in $LAZ_FIXTURES_DIR, else ${DATA_DIR:-.data}/laz_fixtures
(relative DATA_DIR is resolved from the repository root). Every test skips
with a message when the files are missing.

What is checked:
  * byte-exact pairs: the decoded point records of each .laz equal the point
    records of its reference .las; point count and bounds agree; the CLI
    'decode' output is byte-identical to the whole reference .las file.
  * v3 cross-checks: COPC / LAS 1.4 files whose points also exist in a
    validated reference (same points, other point format or order) agree
    field by field.
  * consistency-only files: point count, bounds and per-return counts agree
    with the header (and every layer decoder consumed exactly its bytes).
  * structural variants built on the fly: chunk table offset = -1, missing
    chunk table, compressor 1 (no chunks), partial decodes, chunk iterator.
  * unsupported inputs are rejected with LazError.
"""

from __future__ import annotations

import csv
import functools
import hashlib
import io
import os
import struct
import sys
import tempfile
import unittest
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOL_DIR.parent.parent
sys.path.insert(0, str(TOOL_DIR))

import laszip  # noqa: E402


def fixture_dir() -> Path:
    override = os.environ.get("LAZ_FIXTURES_DIR")
    if override:
        return Path(override)
    data_dir = Path(os.environ.get("DATA_DIR", ".data"))
    if not data_dir.is_absolute():
        data_dir = REPO_ROOT / data_dir
    return data_dir / "laz_fixtures"


FIXTURES = fixture_dir()


def load_fixture_table() -> dict:
    with (TOOL_DIR / "fixtures.tsv").open(newline="", encoding="utf-8") as fh:
        return {row["name"]: row for row in csv.DictReader(fh, delimiter="\t")}


FIXTURE_TABLE = load_fixture_table()


def need(*names: str) -> list:
    """Return fixture paths, or skip the test if any is missing."""
    paths = [FIXTURES / n for n in names]
    missing = [p.name for p in paths if not p.is_file()]
    if missing:
        raise unittest.SkipTest(
            f"LAZ fixtures not found in {FIXTURES} (missing {', '.join(missing[:3])}"
            f"{'...' if len(missing) > 3 else ''}); run: bash tools/laz/fetch_fixtures.sh")
    return paths


@functools.lru_cache(maxsize=None)
def decoded(path: str) -> tuple:
    return laszip.decode_points(path)


def las_records(path: Path) -> tuple:
    hdr = laszip.read_header(str(path))
    with open(path, "rb") as fh:
        fh.seek(hdr["offset_to_point_data"])
        data = fh.read(hdr["point_count"] * hdr["point_record_length"])
    return hdr, data


# (reference .las, .laz) pairs holding the same points in the same format.
BYTE_EXACT_PAIRS = [
    ("lazrs_point10.las", "lazrs_point10.laz"),                  # fmt 0, POINT10 v2
    ("lazrs_point-time.las", "lazrs_point-time.laz"),            # fmt 1, + GPSTIME11 v2
    ("lazrs_point-color.las", "lazrs_point-color.laz"),          # fmt 2, + RGB12 v2
    ("lazrs_point-time-color.las", "lazrs_point-time-color.laz"),  # fmt 3
    ("lazrs_extra-bytes.las", "lazrs_extra-bytes.laz"),          # fmt 3 + BYTE v2 x27
    ("pdal_autzen_trim.las", "pdal_autzen_trim.laz"),            # fmt 3, 110000 pts, 3 chunks
    ("rlas_extra_byte.las", "rlas_extra_byte.laz"),              # fmt 1 + BYTE v2 x4
    ("laspy_extrabytes.las", "laspy_extra.laz"),                 # LAS 1.4 header, fmt 3 + 27
    ("laspy_1_4_w_evlr.las", "laspy_1_4_w_evlr.laz"),            # fmt 6, POINT14 v3, EVLRs
]


def scaled_xyz_extents(hdr: dict, records: bytes) -> tuple:
    rlen = hdr["point_record_length"]
    n = len(records) // rlen
    xs, ys, zs = [], [], []
    for i in range(n):
        x, y, z = struct.unpack_from("<iii", records, i * rlen)
        xs.append(x)
        ys.append(y)
        zs.append(z)
    (sx, sy, sz), (ox, oy, oz) = hdr["scale"], hdr["offset"]
    lo = (min(xs) * sx + ox, min(ys) * sy + oy, min(zs) * sz + oz)
    hi = (max(xs) * sx + ox, max(ys) * sy + oy, max(zs) * sz + oz)
    return lo, hi


def point_fields(hdr: dict, records: bytes) -> list:
    """Format-independent tuples of the standard fields of every point."""
    rlen = hdr["point_record_length"]
    fmt = hdr["point_format"]
    (sx, sy, sz), (ox, oy, oz) = hdr["scale"], hdr["offset"]
    out = []
    for i in range(len(records) // rlen):
        o = i * rlen
        x, y, z, intensity = struct.unpack_from("<iiiH", records, o)
        if fmt < 6:
            b = records[o + 14]
            ret, nret = b & 7, (b >> 3) & 7
            cls = records[o + 15] & 31
            (scan_deg,) = struct.unpack_from("<b", records, o + 16)
            user = records[o + 17]
            (psid,) = struct.unpack_from("<H", records, o + 18)
            q = 20
            gps = None
            if fmt in (1, 3):
                gps = records[o + q:o + q + 8]
                q += 8
            rgb = struct.unpack_from("<HHH", records, o + q) if fmt in (2, 3) else None
        else:
            b = records[o + 14]
            ret, nret = b & 15, b >> 4
            cls = records[o + 16]
            user = records[o + 17]
            (scan,) = struct.unpack_from("<h", records, o + 18)
            scan_deg = round(scan * 0.006)
            (psid,) = struct.unpack_from("<H", records, o + 20)
            gps = records[o + 22:o + 30]
            rgb = struct.unpack_from("<HHH", records, o + 30) if fmt in (7, 8) else None
        out.append((round(x * sx + ox, 6), round(y * sy + oy, 6), round(z * sz + oz, 6),
                    intensity, ret, nret, cls, user, psid, gps, rgb, scan_deg))
    return out


class FixtureTableTests(unittest.TestCase):
    def test_table_is_well_formed(self):
        self.assertGreaterEqual(len(FIXTURE_TABLE), 20)
        for name, row in FIXTURE_TABLE.items():
            self.assertTrue(row["url"].startswith("https://"), name)
            self.assertEqual(len(row["sha256"]), 64, name)
            self.assertLess(int(row["size"]), 20_000_000, name)
        for las, laz in BYTE_EXACT_PAIRS:
            self.assertIn(las, FIXTURE_TABLE)
            self.assertIn(laz, FIXTURE_TABLE)

    def test_present_fixtures_match_checksums(self):
        need(*FIXTURE_TABLE)
        for name, row in FIXTURE_TABLE.items():
            data = (FIXTURES / name).read_bytes()
            self.assertEqual(len(data), int(row["size"]), name)
            self.assertEqual(hashlib.sha256(data).hexdigest(), row["sha256"], name)


class ByteExactTests(unittest.TestCase):
    """Decoded point records must equal the reference LAS records."""

    def check_pair(self, las_name: str, laz_name: str) -> None:
        las, laz = need(las_name, laz_name)
        ref_hdr, ref = las_records(las)
        hdr, records = decoded(str(laz))
        self.assertTrue(hdr["compressed"])
        self.assertEqual(hdr["point_format"], ref_hdr["point_format"])
        self.assertEqual(hdr["point_record_length"], ref_hdr["point_record_length"])
        self.assertEqual(hdr["point_count"], ref_hdr["point_count"])
        self.assertEqual(len(records), hdr["point_count"] * hdr["point_record_length"])
        self.assertEqual(hdr["min"], ref_hdr["min"])
        self.assertEqual(hdr["max"], ref_hdr["max"])
        if records != ref:
            rlen = hdr["point_record_length"]
            first = next(i for i in range(len(ref) // rlen)
                         if records[i * rlen:(i + 1) * rlen] != ref[i * rlen:(i + 1) * rlen])
            self.fail(f"{laz_name}: point {first} differs from {las_name}")
        lo, hi = scaled_xyz_extents(hdr, records)
        for axis in range(3):
            tol = hdr["scale"][axis] / 2 + 1e-9
            self.assertLessEqual(abs(lo[axis] - hdr["min"][axis]), tol)
            self.assertLessEqual(abs(hi[axis] - hdr["max"][axis]), tol)

    def check_cli_decode(self, las_name: str, laz_name: str) -> None:
        las, laz = need(las_name, laz_name)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.las"
            with redirect_stdout(io.StringIO()):
                rc = laszip.main(["decode", str(laz), str(out)])
            self.assertEqual(rc, 0)
            # these fixtures were made by compressing the reference file, so
            # the whole decompressed file (header, VLRs, EVLRs) must match
            self.assertEqual(out.read_bytes(), las.read_bytes(),
                             f"decoded {laz_name} differs from {las_name}")


def _add_pair_tests() -> None:
    for las_name, laz_name in BYTE_EXACT_PAIRS:
        stem = laz_name.replace(".", "_").replace("-", "_")
        setattr(ByteExactTests, f"test_points_{stem}",
                lambda self, a=las_name, b=laz_name: self.check_pair(a, b))
        setattr(ByteExactTests, f"test_cli_file_{stem}",
                lambda self, a=las_name, b=laz_name: self.check_cli_decode(a, b))


_add_pair_tests()


class CrossFormatTests(unittest.TestCase):
    """v3 files checked field by field against a validated reference."""

    def assert_same_point_multiset(self, a_name: str, b_name: str) -> None:
        a, b = need(a_name, b_name)
        ha, ra = decoded(str(a))
        hb, rb = decoded(str(b)) if laszip.read_header(str(b))["compressed"] else las_records(b)
        fa, fb = point_fields(ha, ra), point_fields(hb, rb)
        self.assertEqual(len(fa), ha["point_count"])
        self.assertEqual(len(fa), len(fb))
        self.assertEqual(Counter(fa), Counter(fb))

    def test_copc_rgb14_variable_chunks_vs_las(self):
        # point format 7 (POINT14 + RGB14), many variable-size chunks
        self.assert_same_point_multiset("laspy_simple.copc.laz", "laspy_simple.las")

    def test_copc_chunk_size_zero_vs_las(self):
        # LASzip treats a chunk size of 0 like variable-size chunks
        self.assert_same_point_multiset("rlas_example.copc.laz", "rlas_example.las")

    def test_ellipsoid_copc_vs_v2(self):
        # 100000 points: COPC point format 7 vs the v2-compressed format 3 file
        self.assert_same_point_multiset("copcjs_ellipsoid.copc.laz", "copcjs_ellipsoid.laz")

    def test_ellipsoid_14_byte14_vs_v2(self):
        # point format 7 + 2 extra bytes (BYTE14), two fixed-size chunks. The
        # writer rescaled RGB from 8 to 16 bits (x257), mapped intensity
        # 128 -> 32767 / 255 -> 65535 and stored 'InvertedIntensity' as the
        # extra bytes; everything else is unchanged.
        a, b = need("copcjs_ellipsoid-1.4.laz", "copcjs_ellipsoid.laz")
        ha, ra = decoded(str(a))
        hb, rb = decoded(str(b))
        self.assertEqual(ha["point_record_length"], 38)
        ref = {}
        for p in point_fields(hb, rb):
            ref[(p[0], p[1], p[2], p[9])] = p
        self.assertEqual(len(ref), 100000)
        intensity_map, extra_map = {}, {}
        for i, p in enumerate(point_fields(ha, ra)):
            q = ref.pop((p[0], p[1], p[2], p[9]))
            self.assertEqual(p[4:10] + p[11:], q[4:10] + q[11:])
            self.assertEqual(p[10], tuple(257 * c for c in q[10]))
            (extra,) = struct.unpack_from("<H", ra, i * 38 + 36)
            self.assertEqual(intensity_map.setdefault(q[3], p[3]), p[3])
            self.assertEqual(extra_map.setdefault(q[3], extra), extra)
        self.assertEqual(ref, {})
        self.assertEqual(intensity_map, {128: 32767, 255: 65535})
        self.assertEqual(extra_map, {128: 65535, 255: 32767})


class ConsistencyTests(unittest.TestCase):
    """Files without a reference: header count, bounds and return counts."""

    def check_consistency(self, name: str) -> dict:
        (path,) = need(name)
        hdr, records = decoded(str(path))
        rlen = hdr["point_record_length"]
        n = len(records) // rlen
        self.assertEqual(n, hdr["point_count"])
        lo, hi = scaled_xyz_extents(hdr, records)
        for axis in range(3):
            tol = hdr["scale"][axis] / 2 + 1e-9
            self.assertLessEqual(abs(lo[axis] - hdr["min"][axis]), tol)
            self.assertLessEqual(abs(hi[axis] - hdr["max"][axis]), tol)
        if hdr["point_format"] >= 6:
            counts = Counter(records[i * rlen + 14] & 15 for i in range(n))
            by_return = hdr["points_by_return_64"]
        else:
            counts = Counter(records[i * rlen + 14] & 7 for i in range(n))
            by_return = hdr["legacy_points_by_return"]
        self.assertEqual([counts.get(r, 0) for r in range(1, len(by_return) + 1)], list(by_return))
        return hdr

    def test_point14_byte14_16_extra_bytes(self):
        hdr = self.check_consistency("untwine_eb.laz")
        self.assertEqual(hdr["point_format"], 6)
        self.assertEqual(hdr["extra_bytes_per_point"], 16)

    def test_point_format_8_rgbnir14_byte14(self):
        name = "pdal_las_with_several_extra_byte_bloc.laz"
        hdr = self.check_consistency(name)
        self.assertEqual(hdr["point_format"], 8)
        items = [it["name"] for it in hdr["laszip"]["items"]]
        self.assertEqual(items, ["POINT14", "RGBNIR14", "BYTE14"])
        # plausibility: this file's NIR comes from an 8-bit source scaled by
        # 256, so every low byte is 0 (a desynchronised NIR layer would not
        # keep that); the NIR values also vary
        _, records = decoded(str(FIXTURES / name))
        rlen = hdr["point_record_length"]
        nir_low = records[36::rlen]
        nir_high = records[37::rlen]
        self.assertEqual(len(nir_low), hdr["point_count"])
        self.assertEqual(nir_low.count(0), len(nir_low))
        self.assertGreater(len(set(nir_high)), 100)


class StructureTests(unittest.TestCase):
    """Chunk-table variants, compressor 1, partial decodes, LAS input."""

    @staticmethod
    def _table_offset_pos(hdr: dict) -> int:
        return hdr["offset_to_point_data"]

    def _variant(self, src: Path, tmp: str, mode: str) -> Path:
        data = bytearray(src.read_bytes())
        hdr = laszip.read_header(str(src))
        pos = self._table_offset_pos(hdr)
        (table_offset,) = struct.unpack_from("<q", data, pos)
        out = Path(tmp) / f"{mode}_{src.name}"
        if mode == "offset_at_end":
            struct.pack_into("<q", data, pos, -1)
            data += struct.pack("<q", table_offset)
        elif mode == "no_table":
            # as if the compressor was interrupted before writing the table
            # (the table bytes stay in place so EVLR offsets remain valid)
            struct.pack_into("<q", data, pos, pos)
        else:
            raise ValueError(mode)
        out.write_bytes(bytes(data))
        return out

    def test_chunk_table_offset_minus_one(self):
        (laz,) = need("pdal_autzen_trim.laz")
        with tempfile.TemporaryDirectory() as tmp:
            variant = self._variant(laz, tmp, "offset_at_end")
            self.assertEqual(laszip.decode_points(str(variant))[1], decoded(str(laz))[1])

    def test_missing_chunk_table_is_decoded_sequentially(self):
        names = ["pdal_autzen_trim.laz",       # point-wise, fixed chunks
                 "copcjs_ellipsoid-1.4.laz",   # layered, fixed chunks
                 "laspy_simple.copc.laz"]      # layered, variable chunks
        paths = need(*names)
        with tempfile.TemporaryDirectory() as tmp:
            for laz in paths:
                with self.subTest(laz.name):
                    variant = self._variant(laz, tmp, "no_table")
                    self.assertEqual(laszip.decode_points(str(variant))[1], decoded(str(laz))[1])

    def test_compressor_1_single_stream(self):
        # A one-chunk compressor-2 file becomes a compressor-1 file by
        # dropping the chunk-table offset and the table, and setting
        # compressor = 1 in the LASzip VLR: the arithmetic stream is the same.
        las, laz = need("lazrs_point-time-color.las", "lazrs_point-time-color.laz")
        hdr = laszip.read_header(str(laz))
        data = bytearray(laz.read_bytes())
        start = hdr["offset_to_point_data"]
        (table_offset,) = struct.unpack_from("<q", data, start)
        vlr = next(v for v in hdr["vlrs"] if v["record_id"] == laszip.LASZIP_RECORD_ID)
        struct.pack_into("<H", data, vlr["data_offset"], laszip.COMPRESSOR_POINTWISE)
        variant_bytes = bytes(data[:start]) + bytes(data[start + 8:table_offset])
        with tempfile.TemporaryDirectory() as tmp:
            variant = Path(tmp) / "pointwise.laz"
            variant.write_bytes(variant_bytes)
            vhdr, records = laszip.decode_points(str(variant))
            self.assertEqual(vhdr["laszip"]["compressor"], laszip.COMPRESSOR_POINTWISE)
            self.assertEqual(records, las_records(las)[1])

    def test_max_points_crosses_chunk_boundary(self):
        las, laz = need("pdal_autzen_trim.las", "pdal_autzen_trim.laz")
        ref_hdr, ref = las_records(las)
        rlen = ref_hdr["point_record_length"]
        for n in (1, 2, 49999, 50000, 50001, 60000):
            with self.subTest(n=n):
                _, records = laszip.decode_points(str(laz), max_points=n)
                self.assertEqual(records, ref[:n * rlen])

    def test_max_points_layered(self):
        (laz,) = need("copcjs_ellipsoid-1.4.laz")
        full = decoded(str(laz))[1]
        _, part = laszip.decode_points(str(laz), max_points=50001)
        self.assertEqual(part, full[:50001 * 38])

    def test_cli_decode_max_points(self):
        las, laz = need("laspy_1_4_w_evlr.las", "laspy_1_4_w_evlr.laz")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "head.las"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(laszip.main(["decode", str(laz), str(out), "--max-points", "10"]), 0)
            hdr, records = las_records(out)
            ref_hdr, ref = las_records(las)
            self.assertFalse(hdr["compressed"])
            self.assertEqual(hdr["point_count"], 10)
            self.assertEqual(records, ref[:10 * ref_hdr["point_record_length"]])
            # the EVLRs follow the shortened point data
            self.assertEqual([(e["user_id"], e["record_id"], e["length"]) for e in hdr["evlrs"]],
                             [(e["user_id"], e["record_id"], e["length"]) for e in ref_hdr["evlrs"]])
            self.assertEqual(hdr["start_of_first_evlr"],
                             hdr["offset_to_point_data"] + 10 * hdr["point_record_length"])

    def test_iter_chunks(self):
        (laz,) = need("pdal_autzen_trim.laz")
        chunks = list(laszip.iter_chunks(str(laz)))
        self.assertEqual([n for _, n, _ in chunks], [50000, 50000, 10000])
        self.assertEqual(b"".join(r for _, _, r in chunks), decoded(str(laz))[1])

    def test_uncompressed_las_input(self):
        (las,) = need("lazrs_point-time.las")
        hdr, records = laszip.decode_points(str(las))
        self.assertFalse(hdr["compressed"])
        self.assertIsNone(hdr["laszip"])
        self.assertEqual(records, las_records(las)[1])

    def test_header_fields(self):
        (laz,) = need("laspy_1_4_w_evlr.laz")
        hdr = laszip.read_header(str(laz))
        self.assertEqual(hdr["version"], "1.4")
        self.assertEqual(hdr["point_format_raw"], 0x86)
        self.assertEqual(hdr["point_format"], 6)
        self.assertEqual(hdr["legacy_point_count"], 0)
        self.assertEqual(hdr["point_count"], 1000)
        self.assertEqual(len(hdr["evlrs"]), hdr["number_of_evlrs"])
        lz = hdr["laszip"]
        self.assertEqual(lz["compressor"], laszip.COMPRESSOR_LAYERED_CHUNKED)
        self.assertEqual(lz["chunk_size"], 50000)
        self.assertEqual([(i["name"], i["size"], i["version"]) for i in lz["items"]],
                         [("POINT14", 30, 3)])

    def test_cli_info(self):
        (laz,) = need("laspy_simple.copc.laz")
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(laszip.main(["info", str(laz)]), 0)
        text = buf.getvalue()
        self.assertIn("chunk size variable", text)
        self.assertIn("decodable by this tool: yes", text)


class RejectionTests(unittest.TestCase):
    def test_wave_packets_rejected(self):
        (laz,) = need("rlas_fwf.laz")
        with self.assertRaisesRegex(laszip.LazError, "wave packets"):
            laszip.decode_points(str(laz))

    def test_version_1_items_rejected(self):
        (laz,) = need("lazrs_point-version-1-point-wise.laz")
        with self.assertRaisesRegex(laszip.LazError, "version 1"):
            laszip.decode_points(str(laz))

    def test_corrupt_chunk_detected(self):
        # flip bytes in the middle of a point-wise chunk: the decoder must not
        # silently return the original points
        las, laz = need("lazrs_point-time-color.las", "lazrs_point-time-color.laz")
        data = bytearray(laz.read_bytes())
        hdr = laszip.read_header(str(laz))
        mid = hdr["offset_to_point_data"] + 8 + 2000
        for i in range(mid, mid + 16):
            data[i] ^= 0x5A
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "corrupt.laz"
            bad.write_bytes(bytes(data))
            try:
                _, records = laszip.decode_points(str(bad))
            except laszip.LazError:
                return
            self.assertNotEqual(records, las_records(las)[1])


if __name__ == "__main__":
    unittest.main()
