#!/usr/bin/env python3
"""Range-download, build, inspect, and verify pinned Neuropixels templates."""
from __future__ import annotations

from array import array
import argparse
import ast
import binascii
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import statistics
import struct
import subprocess
import sys
import zlib


DATASET_ID = "zenodo_npx_opto_templates_f32"
SERIES_ID = "npx_opto_kilosort_templates_f32"
RECORD_ID = 18_461_445
RECORD_TITLE = "Recordings with prototype Neuropixels Opto probes in the mouse cerebral cortex"
RECORD_API = f"https://zenodo.org/api/records/{RECORD_ID}"
USER_AGENT = "openzl-public-datasets-npx-opto-templates/1.0"
MAX_CENTRAL_BYTES = 20 * 1024 * 1024
MAX_MEMBER_BYTES = 2 * 1024 * 1024
MAX_DISTINCT_VALUES = 1_000_000

ARCHIVES = {
    "KS097.zip": (2_849_010_911, "c1b8917fc0bf8d2458cdc6ba2daf9abf"),
    "Optopus010.zip": (6_994_767_776, "14c76c515cdd93f72480604f77e97115"),
    "Optopus012.zip": (10_042_106_675, "964600a0ab708f998e56dc2b99046b40"),
    "Optopus013_2023-02-28.zip": (1_939_786_577, "199c1774979e41f4c70d2fe79b1c64da"),
    "Optopus013_2023-03-03.zip": (1_771_771_208, "1db0ecb01c194192b81e0dfd6e9ba809"),
    "Optopus013_2023-03-05.zip": (3_621_759_825, "b06c28b64e421d6774093a8ac3350449"),
    "Optopus013_2023-03-06.zip": (5_393_877_522, "1bd6771b39cd50c4b59010fefbf020e9"),
}

# archive, member, compressed bytes, NPY bytes, CRC32, shape, local name,
# complete NPY SHA256, numeric-payload SHA256
MEMBERS = (
    ("KS097.zip", "KS097/2022-06-13/1/raw_ephys_data/probe00/kilosort4.0_spks_2/templates.npy", 1_389_252, 14_825_568, "c16ee694", (434, 61, 140), "KS097_2022-06-13_s1_templates.npy", "fe67edf0438eadcdcdd9c61fba072338c4033587f1b62c53dcd4bcea7af4f7c8", "baea29a020868d57c5fe2a6026c7cc4b55c6e3d756bf59d258d505cb1ff079b6"),
    ("Optopus010.zip", "Optopus010/2022-06-12/1/raw_ephys_data/probe00/kilosort4.0_spks_2/templates.npy", 1_003_891, 9_184_776, "67a66ac3", (319, 61, 118), "Optopus010_2022-06-12_s1_templates.npy", "284b39e10f08e434a52bf4b4cdc3018a880a1f3434c8198fdcd771ea95f9b677", "931f1031eb3b01acbee37c78d74527bb1f7be9e676dce3e7f122d74ce3c61c28"),
    ("Optopus010.zip", "Optopus010/2022-06-13/1/raw_ephys_data/probe00/kilosort4.0_spks_2/templates.npy", 947_359, 7_905_728, "b24272d2", (300, 61, 108), "Optopus010_2022-06-13_s1_templates.npy", "5c1d2594c2a4eb89787873f011181ae4b15b052d4686fb2d03f8d34df668b33e", "c1975721981ed278cb1d189273eba4538c259453512073727fcc4a0efd6262c4"),
    ("Optopus010.zip", "Optopus010/2022-06-14/1/raw_ephys_data/probe00/kilosort4.0_spks_2/templates.npy", 1_221_096, 9_896_768, "ddc5f464", (390, 61, 104), "Optopus010_2022-06-14_s1_templates.npy", "1dfd9fa86569e4eac0bba47907c706a330fcd05202a57ffa569c6b940050ba47", "b7dba795b4191e3a8450c7d14f55a1ecf453895b87557419b6ec73900722e2bb"),
    ("Optopus012.zip", "Optopus012/2023-02-05/1/raw_ephys_data/probe00/kilosort4.0_spks_2/templates.npy", 789_321, 6_825_296, "8f5abbdf", (259, 61, 108), "Optopus012_2023-02-05_s1_templates.npy", "33c861a7cad81b9a5f27e2f21bc43aa66d55eed719b234ed79fea63533dbd7fe", "397e9665b11bce0962fb10c88295c439294974787527ebed2ed292ef9d22ce09"),
    ("Optopus012.zip", "Optopus012/2023-02-07/1/raw_ephys_data/probe00/kilosort4.0_spks_2/templates.npy", 877_143, 9_159_400, "d0de65a9", (274, 61, 137), "Optopus012_2023-02-07_s1_templates.npy", "af351593f80e203b10b5a1bc5e975bd64d1939a67ce221a1f0afba6c6c48fc49", "1985bd6e4e8a71faa15fbc32cbc30aeea769da62c931d95b123afe3c59937ea8"),
    ("Optopus012.zip", "Optopus012/2023-02-08/1/raw_ephys_data/probe00/kilosort4.0_spks_2/templates.npy", 970_636, 10_418_928, "bac728e2", (305, 61, 140), "Optopus012_2023-02-08_s1_templates.npy", "bfc3d183c98bab3f67679763615879707f2f693a5524199a9e0a0a3a6e1a7fb4", "bbbb5c80217a30206474a94438252eb837b4a1821b4973cfc5f76ba2e86cbde4"),
    ("Optopus012.zip", "Optopus012/2023-02-09/1/raw_ephys_data/probe00/kilosort4.0_spks_2/templates.npy", 798_685, 8_710_928, "62c84c16", (255, 61, 140), "Optopus012_2023-02-09_s1_templates.npy", "ee9d5a43e0200544f530339146c5d9ce9e0746be5d6b260a3f645df5d13f5dfa", "5516aaf5aa53d308def606a105087bfe2e25fd72d95561d10527b8ed9430b4ca"),
    ("Optopus012.zip", "Optopus012/2023-02-13/1/raw_ephys_data/probe00/kilosort4.0_spks_2/templates.npy", 640_752, 7_071_248, "0c135180", (210, 61, 138), "Optopus012_2023-02-13_s1_templates.npy", "f0a2a3cc499075f216fb3e63770fc2928eefdc7c25cc99e61250c56fd92934c4", "aae83b784ed9100799341bcdcfdd3695290e73c2a147c4166bd33cec8db30ef2"),
    ("Optopus013_2023-02-28.zip", "Optopus013/2023-02-28/1/raw_ephys_data/probe00/kilosort4.0_spks_2/templates.npy", 1_182_846, 12_413_384, "a6c13ca3", (366, 61, 139), "Optopus013_2023-02-28_s1_templates.npy", "6305cfa40350f0b8f458833e12266a0e5c49a321d48b7a22f47ec4718b31a13c", "d35925542affd9114a08a1390a5cc99edb4844b928a406bb447547f9c8966ad7"),
    ("Optopus013_2023-03-03.zip", "Optopus013/2023-03-03/1/raw_ephys_data/probe00/kilosort4.0_spks_2/templates.npy", 1_218_901, 11_949_296, "0e6a8816", (371, 61, 132), "Optopus013_2023-03-03_s1_templates.npy", "7944c398c0d2cdb55001b48f1c550e8f316aca329a3c81f2c66e9a7a756ef830", "7d5d189d0dc2edffcab3f10d409d99621762438213fa8ee2dd8b05c95b8f0b3b"),
    ("Optopus013_2023-03-05.zip", "Optopus013/2023-03-05/1/raw_ephys_data/probe00/kilosort4.0_spks_2/templates.npy", 723_271, 7_720_288, "8024a483", (226, 61, 140), "Optopus013_2023-03-05_s1_templates.npy", "48f04e834e1a172c2c282cf5d4d0c08ccd086737c727c1b4eb3ea946b2ad3d3e", "4cf7086b61263bfb1758db79491be4d5e44a6022ec97a36713fd410bc9fa1c09"),
    ("Optopus013_2023-03-06.zip", "Optopus013/2023-03-06/1/raw_ephys_data/probe00/kilosort4.0_spks_2/templates.npy", 1_173_900, 13_592_392, "2c8fe4b4", (346, 61, 161), "Optopus013_2023-03-06_s1_templates.npy", "c603765ef7e70ac5cfb804dfac9ce9142a8c553978191d686d573d3a099cba5c", "146cfd07ca1e9da1c125213755e046e183152d01fcb6d2ad5015791447c977a4"),
    ("Optopus013_2023-03-06.zip", "Optopus013/2023-03-06/2/raw_ephys_data/probe00/kilosort4.0_spks_2/templates.npy", 988_955, 10_746_864, "dff6851d", (308, 61, 143), "Optopus013_2023-03-06_s2_templates.npy", "3d6151ed00729f18abef741307998df6ac50a9d10821a91051c11a8d3308bbfc", "94ebd961854a21ce52cf2f803391d73e1b45221b844b7254e7bd22af16d78e99"),
)


def curl_bytes(url: str, *, byte_range: str | None = None, cap: int = 20_000_000) -> bytes:
    command = ["curl", "--fail", "--silent", "--show-error", "--location", "--retry", "5",
               "--retry-delay", "2", "--max-time", "300", "--max-filesize", str(cap),
               "--user-agent", USER_AGENT]
    if byte_range:
        command.extend(["--range", byte_range])
    result = subprocess.run(command + [url], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode or len(result.stdout) > cap:
        raise SystemExit(result.stderr.decode("utf-8", "replace").strip() or f"failed to fetch {url}")
    return result.stdout


def archive_range(url: str, start: int, size: int, cap: int) -> bytes:
    if start < 0 or not 0 < size <= cap:
        raise ValueError(f"invalid range {start}+{size}")
    raw = curl_bytes(url, byte_range=f"{start}-{start + size - 1}", cap=size)
    if len(raw) != size:
        raise ValueError(f"range response length {len(raw)} != {size}")
    return raw


def zip64_values(extra: bytes, need_u: bool, need_c: bool, need_o: bool) -> tuple[int | None, int | None, int | None]:
    position = 0
    while position + 4 <= len(extra):
        field_id, field_size = struct.unpack_from("<HH", extra, position)
        position += 4
        field = extra[position:position + field_size]
        position += field_size
        if field_id != 1:
            continue
        cursor = 0
        values: list[int | None] = []
        for needed in (need_u, need_c, need_o):
            if needed:
                if cursor + 8 > len(field):
                    raise ValueError("truncated ZIP64 extra field")
                values.append(struct.unpack_from("<Q", field, cursor)[0])
                cursor += 8
            else:
                values.append(None)
        return values[0], values[1], values[2]
    raise ValueError("ZIP64 sentinel without ZIP64 extra field")


def remote_zip_members(url: str, size: int) -> list[dict[str, object]]:
    tail_size = min(size, 65_557)
    tail = archive_range(url, size - tail_size, tail_size, 65_557)
    pos = tail.rfind(b"PK\x05\x06")
    if pos < 0 or pos + 22 > len(tail):
        raise ValueError("ZIP end record not found")
    fields = struct.unpack_from("<4s4H2LH", tail, pos)
    _sig, disk, central_disk, disk_entries, total, central_size, central_offset, comment = fields
    if disk or central_disk or pos + 22 + comment > len(tail):
        raise ValueError("spanned or malformed ZIP")
    if total == 0xFFFF or central_size == 0xFFFFFFFF or central_offset == 0xFFFFFFFF:
        locator_pos = tail.rfind(b"PK\x06\x07", 0, pos)
        if locator_pos < 0:
            raise ValueError("ZIP64 locator not found")
        _sig, locator_disk, zip64_offset, disks = struct.unpack_from("<4sLQL", tail, locator_pos)
        if locator_disk or disks != 1:
            raise ValueError("spanned ZIP64 archive")
        record = archive_range(url, zip64_offset, 56, 56)
        values = struct.unpack_from("<4sQ2H2L4Q", record)
        if values[0] != b"PK\x06\x06" or values[4] or values[5]:
            raise ValueError("invalid ZIP64 end record")
        total, central_size, central_offset = values[7], values[8], values[9]
    elif disk_entries != total:
        raise ValueError("ZIP entry counts disagree")
    if not 0 < central_size <= MAX_CENTRAL_BYTES or central_offset + central_size > size:
        raise ValueError("invalid or oversized ZIP central directory")
    central = archive_range(url, int(central_offset), int(central_size), MAX_CENTRAL_BYTES)
    members = []
    pos = 0
    while pos < len(central):
        fields = struct.unpack_from("<4s6H3L5H2L", central, pos)
        if fields[0] != b"PK\x01\x02":
            raise ValueError("invalid central-directory member")
        flags, method, crc, compressed, uncompressed = fields[3], fields[4], fields[7], fields[8], fields[9]
        name_len, extra_len, comment_len, local_offset = fields[10], fields[11], fields[12], fields[16]
        end = pos + 46 + name_len + extra_len + comment_len
        if end > len(central):
            raise ValueError("truncated central-directory member")
        name_raw = central[pos + 46:pos + 46 + name_len]
        extra = central[pos + 46 + name_len:pos + 46 + name_len + extra_len]
        if uncompressed == 0xFFFFFFFF or compressed == 0xFFFFFFFF or local_offset == 0xFFFFFFFF:
            u64, c64, o64 = zip64_values(extra, uncompressed == 0xFFFFFFFF, compressed == 0xFFFFFFFF, local_offset == 0xFFFFFFFF)
            uncompressed = u64 if u64 is not None else uncompressed
            compressed = c64 if c64 is not None else compressed
            local_offset = o64 if o64 is not None else local_offset
        encoding = "utf-8" if flags & 0x800 else "cp437"
        members.append({"name": name_raw.decode(encoding), "flags": flags, "method": method,
                        "crc32": crc, "compressed": compressed, "uncompressed": uncompressed,
                        "offset": local_offset})
        pos = end
    if len(members) != total:
        raise ValueError(f"ZIP member count {len(members)} != {total}")
    return members


def parse_npy(raw: bytes, expected_size: int) -> tuple[dict[str, object], bytes]:
    if len(raw) != expected_size or raw[:8] != b"\x93NUMPY\x01\x00":
        raise ValueError("expected exact NPY v1.0 file")
    header_length = struct.unpack_from("<H", raw, 8)[0]
    header_end = 10 + header_length
    header = ast.literal_eval(raw[10:header_end].decode("latin-1").strip())
    if not isinstance(header, dict) or header.get("descr") != "<f4" or header.get("fortran_order") is not False:
        raise ValueError("expected homogeneous little-endian float32 C-order NPY")
    shape = header.get("shape")
    if not isinstance(shape, tuple) or any(not isinstance(value, int) or value <= 0 for value in shape):
        raise ValueError("invalid NPY shape")
    payload = raw[header_end:]
    if header_end != 128 or len(payload) != math.prod(shape) * 4:
        raise ValueError("unexpected NPY header or payload size")
    return {"shape": list(shape), "header_bytes": header_end, "value_count": math.prod(shape)}, payload


def extract_member(url: str, member: dict[str, object]) -> bytes:
    offset = int(member["offset"])
    fixed = archive_range(url, offset, 30, 30)
    fields = struct.unpack("<4s5H3L2H", fixed)
    if fields[0] != b"PK\x03\x04" or fields[2] != member["flags"] or fields[3] != member["method"]:
        raise ValueError("local and central ZIP headers disagree")
    flags, method, name_len, extra_len = fields[2], fields[3], fields[9], fields[10]
    if flags & 1 or method != 8:
        raise ValueError("member is encrypted or not Deflate-compressed")
    variable = archive_range(url, offset + 30, name_len + extra_len, 2 * 1024 * 1024)
    encoding = "utf-8" if flags & 0x800 else "cp437"
    if variable[:name_len].decode(encoding) != member["name"]:
        raise ValueError("local and central ZIP names disagree")
    compressed = archive_range(url, offset + 30 + name_len + extra_len, int(member["compressed"]), MAX_MEMBER_BYTES)
    raw = zlib.decompress(compressed, -15)
    if len(raw) != member["uncompressed"] or binascii.crc32(raw) & 0xFFFFFFFF != member["crc32"]:
        raise ValueError("inflated ZIP member failed size or CRC32 validation")
    return raw


def validate_record(record: dict[str, object]) -> dict[str, dict[str, object]]:
    metadata = record.get("metadata", {})
    if not isinstance(metadata, dict) or int(record.get("id", 0)) != RECORD_ID or metadata.get("title") != RECORD_TITLE:
        raise SystemExit("unexpected Zenodo record identity")
    license_info = metadata.get("license", {})
    if not isinstance(license_info, dict) or license_info.get("id") != "cc-by-4.0":
        raise SystemExit("Zenodo record no longer declares CC BY 4.0")
    files = record.get("files", [])
    if not isinstance(files, list):
        raise SystemExit("Zenodo file inventory is malformed")
    return {str(item.get("key", "")): item for item in files if isinstance(item, dict)}


def validate_archive_items(items: dict[str, dict[str, object]]) -> None:
    for archive, (archive_size, archive_md5) in ARCHIVES.items():
        item = items.get(archive)
        if item is None or int(item.get("size", 0)) != archive_size or item.get("checksum") != f"md5:{archive_md5}":
            raise SystemExit(f"pinned archive identity changed: {archive}")


def download(args: argparse.Namespace) -> None:
    args.download_dir.mkdir(parents=True, exist_ok=True)
    record = json.loads(curl_bytes(RECORD_API).decode("utf-8"))
    items = validate_record(record)
    validate_archive_items(items)
    urls: dict[str, str] = {}
    selected: dict[str, dict[str, dict[str, object]]] = {}
    for archive, (archive_size, archive_md5) in ARCHIVES.items():
        item = items.get(archive)
        assert item is not None
        links = item.get("links", {})
        url = str(links.get("self") or links.get("download") or "") if isinstance(links, dict) else ""
        if not url:
            raise SystemExit(f"missing archive URL: {archive}")
        urls[archive] = url
        templates = {str(member["name"]): member for member in remote_zip_members(url, archive_size)
                     if PurePosixPath(str(member["name"])).name.lower() == "templates.npy"}
        expected = {row[1] for row in MEMBERS if row[0] == archive}
        if set(templates) != expected:
            raise SystemExit(f"exact templates.npy inventory changed: {archive}")
        selected[archive] = templates
    inventory = []
    for number, row in enumerate(MEMBERS, 1):
        archive, name, compressed_size, npy_size, crc, shape, local_name, npy_sha, payload_sha = row
        member = selected[archive][name]
        if (member["method"], member["compressed"], member["uncompressed"], f"{int(member['crc32']):08x}") != (8, compressed_size, npy_size, crc):
            raise SystemExit(f"pinned ZIP member identity changed: {name}")
        target = args.download_dir / local_name
        raw = target.read_bytes() if target.is_file() else b""
        if hashlib.sha256(raw).hexdigest() != npy_sha:
            print(f"[{number}/{len(MEMBERS)}] range-extracting {name}")
            raw = extract_member(urls[archive], member)
            part = target.with_suffix(target.suffix + ".part")
            part.write_bytes(raw)
            os.replace(part, target)
        else:
            print(f"[{number}/{len(MEMBERS)}] verified cached {local_name}")
        report, payload = parse_npy(raw, npy_size)
        if report["shape"] != list(shape) or hashlib.sha256(raw).hexdigest() != npy_sha or hashlib.sha256(payload).hexdigest() != payload_sha:
            raise SystemExit(f"pinned NPY identity changed: {local_name}")
        inventory.append({"archive_name": archive, "archive_size": ARCHIVES[archive][0],
                          "archive_md5": ARCHIVES[archive][1], "archive_url": urls[archive],
                          "member_name": name, "member_compression_method": 8,
                          "member_compressed_size": compressed_size, "member_uncompressed_size": npy_size,
                          "member_crc32": crc, "local_name": local_name, "npy_shape": list(shape),
                          "npy_sha256": npy_sha, "payload_sha256": payload_sha, "payload_bytes": len(payload)})
    (args.download_dir / f"record_{RECORD_ID}.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    (args.download_dir / "source_inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n")
    print(f"validated {len(inventory)} template tensors totaling {sum(int(x['payload_bytes']) for x in inventory)} numeric bytes")


def local_record(download_dir: Path) -> None:
    path = download_dir / f"record_{RECORD_ID}.json"
    if not path.is_file():
        raise SystemExit("missing pinned record metadata; run download.sh")
    items = validate_record(json.loads(path.read_text(encoding="utf-8")))
    validate_archive_items(items)


def scan(download_dir: Path) -> tuple[list[dict[str, object]], list[bytes], dict[str, object]]:
    local_record(download_dir)
    reports: list[dict[str, object]] = []
    payloads: list[bytes] = []
    sample_hashes: set[str] = set()
    prior_templates: set[bytes] = set()
    for row in MEMBERS:
        archive, member_name, _compressed, npy_size, _crc, shape, local_name, npy_sha, payload_sha = row
        path = download_dir / local_name
        raw = path.read_bytes() if path.is_file() else b""
        if len(raw) != npy_size or hashlib.sha256(raw).hexdigest() != npy_sha:
            raise SystemExit(f"missing or mismatched pinned NPY: {local_name}")
        header, payload = parse_npy(raw, npy_size)
        if header["shape"] != list(shape) or hashlib.sha256(payload).hexdigest() != payload_sha:
            raise SystemExit(f"NPY layout or payload changed: {local_name}")
        if payload_sha in sample_hashes:
            raise SystemExit(f"duplicate sample payload: {local_name}")
        sample_hashes.add(payload_sha)
        values = array("f")
        values.frombytes(payload)
        if sys.byteorder != "little":
            values.byteswap()
        if not all(math.isfinite(value) for value in values):
            raise SystemExit(f"non-finite template value: {local_name}")
        template_count, time_samples, channels = shape
        per_template = time_samples * channels
        template_hashes: set[bytes] = set()
        min_nonzero, min_transitions = per_template, per_template
        for template in range(template_count):
            start, end = template * per_template, (template + 1) * per_template
            selected_values = values[start:end]
            nonzero = sum(value != 0 for value in selected_values)
            transitions = sum(left != right for left, right in zip(selected_values, selected_values[1:]))
            min_nonzero, min_transitions = min(min_nonzero, nonzero), min(min_transitions, transitions)
            template_hashes.add(hashlib.sha256(payload[start * 4:end * 4]).digest())
        within_duplicates = template_count - len(template_hashes)
        cross_duplicates = len(template_hashes & prior_templates)
        if within_duplicates or cross_duplicates or min_nonzero == 0 or min_transitions < 3:
            raise SystemExit(f"degenerate or duplicate templates: {local_name}")
        prior_templates.update(template_hashes)
        step = max(1, len(values) // MAX_DISTINCT_VALUES)
        reports.append({
            "archive_name": archive, "member_name": member_name, "local_name": local_name,
            "output_name": local_name.removesuffix(".npy") + "_f32le.bin", "shape": list(shape),
            "template_count": template_count, "time_samples": time_samples, "channel_count": channels,
            "value_count": len(values), "payload_bytes": len(payload), "minimum": min(values),
            "maximum": max(values), "zero_values": values.count(0.0),
            "positive_values": sum(value > 0 for value in values), "negative_values": sum(value < 0 for value in values),
            "flattened_transitions": sum(left != right for left, right in zip(values, values[1:])),
            "distinct_sample_values": len(set(values[::step])), "distinct_sample_stride": step,
            "minimum_template_nonzero_values": min_nonzero, "minimum_template_transitions": min_transitions,
            "unique_templates": len(template_hashes), "within_session_duplicate_templates": within_duplicates,
            "rows_duplicated_from_prior_sessions": cross_duplicates, "payload_sha256": payload_sha,
            "zlib_ratio": round(len(zlib.compress(payload, 9)) / len(payload), 9),
        })
        payloads.append(payload)
    ratios = [float(report["zlib_ratio"]) for report in reports]
    total_values = sum(int(report["value_count"]) for report in reports)
    total_zeros = sum(int(report["zero_values"]) for report in reports)
    summary = {
        "dataset_id": DATASET_ID, "series_id": SERIES_ID, "record_id": RECORD_ID, "license": "cc-by-4.0",
        "sample_count": len(reports), "total_templates": sum(int(r["template_count"]) for r in reports),
        "time_samples_per_template": 61, "minimum_channels": min(int(r["channel_count"]) for r in reports),
        "maximum_channels": max(int(r["channel_count"]) for r in reports), "value_count": total_values,
        "total_size_bytes": sum(int(r["payload_bytes"]) for r in reports),
        "global_minimum": min(float(r["minimum"]) for r in reports), "global_maximum": max(float(r["maximum"]) for r in reports),
        "zero_values": total_zeros, "zero_fraction": round(total_zeros / total_values, 9),
        "minimum_distinct_sample_values": min(int(r["distinct_sample_values"]) for r in reports),
        "minimum_template_nonzero_values": min(int(r["minimum_template_nonzero_values"]) for r in reports),
        "minimum_template_transitions": min(int(r["minimum_template_transitions"]) for r in reports),
        "unique_sample_payloads": len(sample_hashes), "unique_templates": len(prior_templates),
        "within_session_duplicate_templates": sum(int(r["within_session_duplicate_templates"]) for r in reports),
        "cross_session_duplicate_templates": sum(int(r["rows_duplicated_from_prior_sessions"]) for r in reports),
        "minimum_zlib_ratio": min(ratios), "median_zlib_ratio": statistics.median(ratios),
        "maximum_zlib_ratio": max(ratios), "profiles": reports,
    }
    expected = {"sample_count": 14, "total_templates": 4363, "minimum_channels": 104, "maximum_channels": 161,
                "value_count": 35_104_768, "total_size_bytes": 140_419_072,
                "global_minimum": -91.8678970336914, "global_maximum": 75.7893295288086,
                "zero_values": 31_870_121, "zero_fraction": 0.907857332,
                "minimum_distinct_sample_values": 90_576, "minimum_template_nonzero_values": 610,
                "minimum_template_transitions": 670, "unique_sample_payloads": 14, "unique_templates": 4363,
                "within_session_duplicate_templates": 0, "cross_session_duplicate_templates": 0,
                "minimum_zlib_ratio": 0.086021799, "median_zlib_ratio": 0.094081813,
                "maximum_zlib_ratio": 0.122917071}
    for key, value in expected.items():
        if summary[key] != value:
            raise SystemExit(f"aggregate statistic changed for {key}: {summary[key]} != {value}")
    return reports, payloads, summary


def public_summary(summary: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in summary.items() if key != "profiles"}


def inspect(args: argparse.Namespace) -> None:
    _reports, _payloads, summary = scan(args.download_dir)
    print(json.dumps(public_summary(summary), indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    reports, payloads, summary = scan(args.download_dir)
    series_dir = args.samples_dir / SERIES_ID
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True)
    rows = []
    for report, payload in zip(reports, payloads, strict=True):
        output = series_dir / str(report["output_name"])
        output.write_bytes(payload)
        rows.append({
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "role": "primary",
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "source_sample": f"downloads/{DATASET_ID}/{report['local_name']}", "source_header_bytes": 128,
            "numeric_kind": "float", "bit_width": 32, "endianness": "little", "element_size_bytes": 4,
            "value_count": report["value_count"], "sample_size_bytes": report["payload_bytes"],
            "sample_format": "raw homogeneous float32 Kilosort spike-template tensor",
            "sample_geometry": "3d_kilosort_template_time_channel_tensor", "sample_rank": 3,
            "sample_shape": report["shape"], "sample_axes": ["spike_template", "waveform_time_sample", "probe_channel"],
            "natural_record_kind": "complete_kilosort_session_template_tensor",
            "minimum": report["minimum"], "maximum": report["maximum"], "zero_values": report["zero_values"],
            "sha256": report["payload_sha256"],
        })
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(public_summary(summary), indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    reports, payloads, summary = scan(args.download_dir)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or statistics; run build.sh")
    rows = [json.loads(line) for line in args.index.read_text().splitlines() if line.strip()]
    if len(rows) != len(reports):
        raise SystemExit("index row count changed")
    expected_outputs = set()
    for row, report, payload in zip(rows, reports, payloads, strict=True):
        if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID or row.get("sample_shape") != report["shape"]:
            raise SystemExit(f"index identity or shape changed: {report['local_name']}")
        if row.get("numeric_kind") != "float" or row.get("bit_width") != 32 or row.get("endianness") != "little":
            raise SystemExit(f"indexed numeric representation changed: {report['local_name']}")
        output = args.data_root / str(row["sample_path"])
        expected_outputs.add(output.resolve())
        if not output.is_file() or output.read_bytes() != payload or row.get("sha256") != report["payload_sha256"]:
            raise SystemExit(f"output is not byte-identical to NPY payload: {report['local_name']}")
    actual_outputs = {path.resolve() for path in (args.data_root / "samples" / DATASET_ID).glob("*/*.bin")}
    if actual_outputs != expected_outputs or json.loads(args.stats.read_text()) != summary:
        raise SystemExit("sample inventory or stored statistics changed")
    print(json.dumps({"dataset_id": DATASET_ID, "verified_samples": len(rows),
                      "verified_templates": summary["total_templates"], "verified_values": summary["value_count"],
                      "verified_bytes": summary["total_size_bytes"]}, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    download_parser = subparsers.add_parser("download")
    download_parser.add_argument("--download-dir", type=Path, required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--download-dir", type=Path, required=True)
    for command in ("build", "verify"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--download-dir", type=Path, required=True)
        sub.add_argument("--index", type=Path, required=True)
        sub.add_argument("--stats", type=Path, required=True)
        sub.add_argument("--data-root", type=Path, required=True)
        if command == "build":
            sub.add_argument("--samples-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "download":
        download(args)
    elif args.command == "inspect":
        inspect(args)
    elif args.command == "build":
        build(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
