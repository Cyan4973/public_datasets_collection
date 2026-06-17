#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import re
import shutil
import statistics
import struct
import tarfile
import zipfile
import zlib
from collections import Counter
from pathlib import Path
from typing import Any, BinaryIO


MAX_PRIMARY_BYTES = 1_000_000_000
MIN_PRIMARY_BYTES = 102_400
MIN_PRIMARY_VALUES = 10_000
MIN_MEDIAN_VALUES = 1_000


def clean_name(value: str, fallback: str = "sample") -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return value or fallback


def read_u16(data: bytes, offset: int, endian: str) -> int:
    return struct.unpack_from(endian + "H", data, offset)[0]


def read_u32(data: bytes, offset: int, endian: str) -> int:
    return struct.unpack_from(endian + "I", data, offset)[0]


def write_sample(
    *,
    data_root: Path,
    out_dir: Path,
    rows: list[dict[str, Any]],
    dataset_id: str,
    series_id: str,
    source_path: Path,
    sample_name: str,
    payload: bytes,
    numeric_kind: str,
    endianness: str,
    geometry: str,
    shape: list[int],
    axes: list[str],
    extra: dict[str, Any] | None = None,
) -> None:
    if len(payload) <= 0 or len(payload) % 2:
        raise ValueError(f"{source_path}: invalid 16-bit payload length {len(payload)}")
    path = out_dir / f"{len(rows) + 1:06d}_{clean_name(sample_name)}.bin"
    path.write_bytes(payload)
    row = {
        "dataset_id": dataset_id,
        "series_id": series_id,
        "role": "primary",
        "sample_path": path.relative_to(data_root).as_posix(),
        "numeric_kind": numeric_kind,
        "bit_width": 16,
        "endianness": endianness,
        "element_size_bytes": 2,
        "sample_size_bytes": len(payload),
        "value_count": len(payload) // 2,
        "sample_geometry": geometry,
        "sample_rank": len(shape),
        "sample_shape": shape,
        "sample_axes": axes,
        "source_path": source_path.as_posix(),
    }
    if extra:
        row.update(extra)
    rows.append(row)


def extract_archives(download_dir: Path, extracted_dir: Path, max_extracted_bytes: int) -> list[Path]:
    extracted_dir.mkdir(parents=True, exist_ok=True)
    roots = [download_dir, extracted_dir]
    total = 0
    for path in sorted(download_dir.rglob("*")):
        if not path.is_file():
            continue
        lower = path.name.lower()
        target = extracted_dir / clean_name(path.name)
        if lower.endswith(".zip"):
            target.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(path) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    total += int(info.file_size)
                    if total > max_extracted_bytes:
                        raise SystemExit(f"archive extraction exceeds MAX_EXTRACTED_BYTES={max_extracted_bytes}")
                    zf.extract(info, target)
        elif lower.endswith((".tar", ".tar.gz", ".tgz")):
            target.mkdir(parents=True, exist_ok=True)
            with tarfile.open(path) as tf:
                members = [m for m in tf.getmembers() if m.isfile()]
                for member in members:
                    total += int(member.size)
                    if total > max_extracted_bytes:
                        raise SystemExit(f"archive extraction exceeds MAX_EXTRACTED_BYTES={max_extracted_bytes}")
                tf.extractall(target, members=members)
        elif lower.endswith(".gz") and not lower.endswith((".tar.gz", ".tgz")):
            out = target.with_suffix("")
            with gzip.open(path, "rb") as src, out.open("wb") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_extracted_bytes:
                        raise SystemExit(f"gzip extraction exceeds MAX_EXTRACTED_BYTES={max_extracted_bytes}")
                    dst.write(chunk)
    return roots


def scan_files(roots: list[Path], suffixes: tuple[str, ...]) -> list[Path]:
    seen: set[Path] = set()
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.resolve() in seen:
                continue
            if path.name.lower().endswith(suffixes):
                files.append(path)
                seen.add(path.resolve())
    return files


def parse_dicom_value(data: bytes, tag: tuple[int, int], endian: str, explicit: bool) -> bytes | None:
    offset = dicom_start_offset(data, tag, explicit)
    target_group, target_element = tag
    long_vr = {"OB", "OD", "OF", "OL", "OW", "SQ", "UC", "UR", "UT", "UN"}
    while offset + 8 <= len(data):
        group = read_u16(data, offset, endian)
        element = read_u16(data, offset + 2, endian)
        offset += 4
        if explicit:
            vr = data[offset : offset + 2].decode("ascii", "replace")
            offset += 2
            if vr in long_vr:
                offset += 2
                length = read_u32(data, offset, endian)
                offset += 4
            else:
                length = read_u16(data, offset, endian)
                offset += 2
        else:
            length = read_u32(data, offset, endian)
            offset += 4
        if length == 0xFFFFFFFF:
            return None
        value = data[offset : offset + length]
        if (group, element) == (target_group, target_element):
            return value
        offset += length + (length % 2)
    return None


def dicom_start_offset(data: bytes, tag: tuple[int, int], explicit: bool) -> int:
    if data[128:132] != b"DICM":
        return 0
    if tag[0] == 0x0002:
        return 132
    offset = 132
    long_vr = {"OB", "OD", "OF", "OL", "OW", "SQ", "UC", "UR", "UT", "UN"}
    while offset + 8 <= len(data):
        group = read_u16(data, offset, "<")
        if group != 0x0002:
            return offset
        offset += 4
        vr = data[offset : offset + 2].decode("ascii", "replace")
        offset += 2
        if vr in long_vr:
            offset += 2
            length = read_u32(data, offset, "<")
            offset += 4
        else:
            length = read_u16(data, offset, "<")
            offset += 2
        offset += length + (length % 2)
    return 132


def dicom_int(data: bytes, tag: tuple[int, int], endian: str, explicit: bool) -> int | None:
    value = parse_dicom_value(data, tag, endian, explicit)
    if not value:
        return None
    if len(value) == 2:
        return read_u16(value, 0, endian)
    text = value.decode("ascii", "ignore").strip("\0 ")
    return int(text) if text else None


def dicom_text(data: bytes, tag: tuple[int, int], endian: str, explicit: bool) -> str | None:
    value = parse_dicom_value(data, tag, endian, explicit)
    if value is None:
        return None
    return value.decode("ascii", "ignore").strip("\0 ")


def build_dicom(paths: list[Path], args: argparse.Namespace, data_root: Path, out_dir: Path, rows: list[dict[str, Any]]) -> None:
    accepted_transfer_syntaxes = {
        "1.2.840.10008.1.2": ("<", False, "little"),
        "1.2.840.10008.1.2.1": ("<", True, "little"),
        "1.2.840.10008.1.2.2": (">", True, "big"),
    }
    for path in paths:
        data = path.read_bytes()
        meta_explicit = True
        transfer = dicom_text(data, (0x0002, 0x0010), "<", meta_explicit) or "1.2.840.10008.1.2.1"
        if transfer not in accepted_transfer_syntaxes:
            continue
        endian, explicit, endianness = accepted_transfer_syntaxes[transfer]
        bits = dicom_int(data, (0x0028, 0x0100), endian, explicit)
        rows_count = dicom_int(data, (0x0028, 0x0010), endian, explicit)
        cols_count = dicom_int(data, (0x0028, 0x0011), endian, explicit)
        samples = dicom_int(data, (0x0028, 0x0002), endian, explicit) or 1
        pixel_repr = dicom_int(data, (0x0028, 0x0103), endian, explicit) or 0
        pixel_data = parse_dicom_value(data, (0x7FE0, 0x0010), endian, explicit)
        if bits != 16 or not rows_count or not cols_count or samples != 1 or not pixel_data:
            continue
        expected = rows_count * cols_count * 2
        if len(pixel_data) < expected:
            continue
        payload = pixel_data[:expected]
        write_sample(
            data_root=data_root,
            out_dir=out_dir,
            rows=rows,
            dataset_id=args.dataset_id,
            series_id=args.series_id,
            source_path=path,
            sample_name=path.stem,
            payload=payload,
            numeric_kind="int" if pixel_repr else "uint",
            endianness=endianness,
            geometry="2d_raster",
            shape=[rows_count, cols_count],
            axes=["y", "x"],
            extra={"container_format": "dicom", "transfer_syntax_uid": transfer},
        )


def build_wav(paths: list[Path], args: argparse.Namespace, data_root: Path, out_dir: Path, rows: list[dict[str, Any]]) -> None:
    import wave

    for path in paths:
        with wave.open(str(path), "rb") as wav:
            channels = wav.getnchannels()
            width = wav.getsampwidth()
            frames = wav.getnframes()
            if width != 2 or frames <= 0:
                continue
            payload = wav.readframes(frames)
        write_sample(
            data_root=data_root,
            out_dir=out_dir,
            rows=rows,
            dataset_id=args.dataset_id,
            series_id=args.series_id,
            source_path=path,
            sample_name=path.stem,
            payload=payload,
            numeric_kind="int",
            endianness="little",
            geometry="1d_waveform" if channels == 1 else "2d_interleaved_waveform",
            shape=[frames] if channels == 1 else [frames, channels],
            axes=["frame"] if channels == 1 else ["frame", "channel"],
            extra={"container_format": "wav", "sample_rate_hz": wav.getframerate(), "channels": channels},
        )


def build_segy(paths: list[Path], args: argparse.Namespace, data_root: Path, out_dir: Path, rows: list[dict[str, Any]]) -> None:
    for path in paths:
        data = path.read_bytes()
        if len(data) < 3600:
            continue
        format_code = struct.unpack_from(">H", data, 3224)[0]
        binary_ns = struct.unpack_from(">H", data, 3220)[0]
        if format_code != 3:
            continue
        offset = 3600
        trace_index = 0
        while offset + 240 <= len(data):
            ns = struct.unpack_from(">H", data, offset + 114)[0] or binary_ns
            if ns <= 0:
                break
            start = offset + 240
            end = start + ns * 2
            if end > len(data):
                break
            trace_index += 1
            write_sample(
                data_root=data_root,
                out_dir=out_dir,
                rows=rows,
                dataset_id=args.dataset_id,
                series_id=args.series_id,
                source_path=path,
                sample_name=f"{path.stem}_trace_{trace_index:06d}",
                payload=data[start:end],
                numeric_kind="int",
                endianness="big",
                geometry="1d_trace",
                shape=[ns],
                axes=["sample"],
                extra={"container_format": "segy", "trace_index": trace_index},
            )
            offset = end


def build_las(paths: list[Path], args: argparse.Namespace, data_root: Path, out_dir: Path, rows: list[dict[str, Any]]) -> None:
    for path in paths:
        if path.suffix.lower() == ".laz":
            continue
        data = path.read_bytes()
        if len(data) < 375 or data[:4] != b"LASF":
            continue
        point_offset = struct.unpack_from("<I", data, 96)[0]
        point_format = data[104] & 0x3F
        record_length = struct.unpack_from("<H", data, 105)[0]
        legacy_count = struct.unpack_from("<I", data, 107)[0]
        count = legacy_count
        if len(data) >= 255 and count == 0:
            count = struct.unpack_from("<Q", data, 247)[0]
        if point_format > 10 or record_length < 20 or count <= 0:
            continue
        end = point_offset + count * record_length
        if end > len(data):
            continue
        payload = bytearray()
        for index in range(count):
            start = point_offset + index * record_length + 12
            payload.extend(data[start : start + 2])
        write_sample(
            data_root=data_root,
            out_dir=out_dir,
            rows=rows,
            dataset_id=args.dataset_id,
            series_id=args.series_id,
            source_path=path,
            sample_name=f"{path.stem}_intensity",
            payload=bytes(payload),
            numeric_kind="uint",
            endianness="little",
            geometry="1d_point_attribute_stream",
            shape=[count],
            axes=["point"],
            extra={"container_format": "las", "point_format": point_format, "point_record_length": record_length},
        )


def parse_tiff_ifds(data: bytes) -> tuple[str, list[dict[int, tuple[int, int, int]]]]:
    if data[:2] == b"II":
        endian = "<"
    elif data[:2] == b"MM":
        endian = ">"
    else:
        return "", []
    if read_u16(data, 2, endian) != 42:
        return "", []
    offset = read_u32(data, 4, endian)
    ifds: list[dict[int, tuple[int, int, int]]] = []
    while offset and offset + 2 <= len(data):
        count = read_u16(data, offset, endian)
        offset += 2
        ifd: dict[int, tuple[int, int, int]] = {}
        for _ in range(count):
            if offset + 12 > len(data):
                break
            tag = read_u16(data, offset, endian)
            typ = read_u16(data, offset + 2, endian)
            n = read_u32(data, offset + 4, endian)
            value = read_u32(data, offset + 8, endian)
            ifd[tag] = (typ, n, value)
            offset += 12
        ifds.append(ifd)
        if offset + 4 > len(data):
            break
        offset = read_u32(data, offset, endian)
    return endian, ifds


def tiff_values(data: bytes, endian: str, ifd: dict[int, tuple[int, int, int]], tag: int) -> list[int]:
    if tag not in ifd:
        return []
    typ, n, value = ifd[tag]
    type_size = {3: 2, 4: 4}.get(typ)
    if not type_size:
        return []
    raw_len = n * type_size
    if raw_len <= 4:
        raw = struct.pack(endian + "I", value)[:raw_len]
    else:
        raw = data[value : value + raw_len]
    fmt = "H" if typ == 3 else "I"
    return [struct.unpack_from(endian + fmt, raw, i * type_size)[0] for i in range(n)]


def build_tiff(paths: list[Path], args: argparse.Namespace, data_root: Path, out_dir: Path, rows: list[dict[str, Any]]) -> None:
    for path in paths:
        data = path.read_bytes()
        endian, ifds = parse_tiff_ifds(data)
        if not endian:
            continue
        for ifd_index, ifd in enumerate(ifds, start=1):
            width = tiff_values(data, endian, ifd, 256)
            height = tiff_values(data, endian, ifd, 257)
            bits = tiff_values(data, endian, ifd, 258)
            compression = tiff_values(data, endian, ifd, 259) or [1]
            samples_per_pixel = tiff_values(data, endian, ifd, 277) or [1]
            offsets = tiff_values(data, endian, ifd, 273)
            counts = tiff_values(data, endian, ifd, 279)
            sample_format = tiff_values(data, endian, ifd, 339) or [1]
            if not width or not height or bits != [16] or compression != [1] or samples_per_pixel != [1] or not offsets or not counts:
                continue
            payload = bytearray()
            for offset, count in zip(offsets, counts):
                payload.extend(data[offset : offset + count])
            expected = width[0] * height[0] * 2
            if len(payload) != expected:
                continue
            write_sample(
                data_root=data_root,
                out_dir=out_dir,
                rows=rows,
                dataset_id=args.dataset_id,
                series_id=args.series_id,
                source_path=path,
                sample_name=f"{path.stem}_ifd_{ifd_index}",
                payload=bytes(payload),
                numeric_kind="int" if sample_format[0] == 2 else "uint",
                endianness="little" if endian == "<" else "big",
                geometry="2d_raster",
                shape=[height[0], width[0]],
                axes=["y", "x"],
                extra={"container_format": "tiff", "ifd_index": ifd_index},
            )


def parse_envi_header(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in text.splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        result[key.strip().lower()] = value.strip().strip("{}").strip()
    return result


def build_envi(paths: list[Path], args: argparse.Namespace, data_root: Path, out_dir: Path, rows: list[dict[str, Any]]) -> None:
    headers = [p for p in paths if p.name.lower().endswith(".hdr")]
    for hdr in headers:
        meta = parse_envi_header(hdr.read_text(encoding="utf-8", errors="replace"))
        try:
            samples = int(meta["samples"])
            lines = int(meta["lines"])
            bands = int(meta.get("bands", "1"))
            data_type = int(meta["data type"])
            header_offset = int(meta.get("header offset", "0"))
        except Exception:
            continue
        if data_type not in {2, 12}:
            continue
        byte_order = int(meta.get("byte order", "0"))
        raw_candidates = [hdr.with_suffix("")]
        raw_file = meta.get("data file")
        if raw_file:
            raw_candidates.insert(0, hdr.parent / raw_file)
        source = next((candidate for candidate in raw_candidates if candidate.exists()), None)
        if not source:
            continue
        data = source.read_bytes()
        expected = samples * lines * bands * 2
        payload = data[header_offset : header_offset + expected]
        if len(payload) != expected:
            continue
        write_sample(
            data_root=data_root,
            out_dir=out_dir,
            rows=rows,
            dataset_id=args.dataset_id,
            series_id=args.series_id,
            source_path=source,
            sample_name=source.stem,
            payload=payload,
            numeric_kind="int" if data_type == 2 else "uint",
            endianness="little" if byte_order == 0 else "big",
            geometry="3d_hyperspectral_cube" if bands > 1 else "2d_raster",
            shape=[lines, samples, bands] if bands > 1 else [lines, samples],
            axes=["y", "x", "band"] if bands > 1 else ["y", "x"],
            extra={"container_format": "envi", "interleave": meta.get("interleave", "")},
        )


def pds_value(text: str, key: str) -> str | None:
    match = re.search(rf"(?im)^\s*{re.escape(key)}\s*=\s*(.+?)\s*$", text)
    if not match:
        return None
    return match.group(1).strip().strip('"')


def pds_tuple_ints(text: str | None) -> list[int]:
    if not text:
        return []
    return [int(token) for token in re.findall(r"[-+]?\d+", text)]


def pds_pointer(value: str | None) -> tuple[str, int]:
    if not value:
        return "", 1
    value = value.strip()
    if value.startswith("("):
        parts = [part.strip().strip('"') for part in value.strip("()").split(",")]
        file_name = parts[0] if parts else ""
        record_index = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
        return file_name, record_index
    if value.startswith('"'):
        return value.strip('"'), 1
    if value.isdigit():
        return "", int(value)
    return "", 1


def pds_payload_source(label: Path, file_name: str) -> Path | None:
    source = label.parent / file_name if file_name else label.with_suffix(".img")
    if source.exists():
        return source
    for suffix in (".img", ".IMG", ".dat", ".DAT", ".qub", ".QUB"):
        candidate = label.with_suffix(suffix)
        if candidate.exists():
            return candidate
    return None


def build_pds(paths: list[Path], args: argparse.Namespace, data_root: Path, out_dir: Path, rows: list[dict[str, Any]]) -> None:
    labels = [p for p in paths if p.name.lower().endswith((".lbl", ".xml"))]
    for label in labels:
        text = label.read_text(encoding="utf-8", errors="replace")
        if label.suffix.lower() == ".xml":
            bits_match = re.search(r"<(?:sample_bits|bits_per_sample)>\s*(\d+)\s*</", text, re.I)
            lines_match = re.search(r"<(?:lines|Axis_Array[^>]*>\s*<elements)>\s*(\d+)\s*</", text, re.I)
            if not bits_match or bits_match.group(1) != "16" or not lines_match:
                continue
            # PDS4 products vary too much to parse safely without exact product-class handling.
            continue

        object_kind = ""
        sample_type = ""
        shape: list[int] = []
        axes: list[str] = []
        pointer_value = ""
        try:
            lines = int((pds_value(text, "LINES") or "0").split()[0])
            line_samples = int((pds_value(text, "LINE_SAMPLES") or "0").split()[0])
            bands = int((pds_value(text, "BANDS") or "1").split()[0])
            bits = int((pds_value(text, "SAMPLE_BITS") or "0").split()[0])
        except Exception:
            lines = line_samples = bands = bits = 0
        if bits == 16 and lines > 0 and line_samples > 0:
            object_kind = "image"
            sample_type = (pds_value(text, "SAMPLE_TYPE") or "").upper()
            shape = [lines, line_samples, bands] if bands > 1 else [lines, line_samples]
            axes = ["line", "sample", "band"] if bands > 1 else ["line", "sample"]
            pointer_value = pds_value(text, "^IMAGE") or ""

        core_items = pds_tuple_ints(pds_value(text, "CORE_ITEMS"))
        core_item_bytes = int((pds_value(text, "CORE_ITEM_BYTES") or "0").split()[0] or "0")
        if not object_kind and len(core_items) >= 3 and core_item_bytes == 2:
            object_kind = "qube"
            sample_type = (pds_value(text, "CORE_ITEM_TYPE") or "").upper()
            shape = core_items[:3]
            axis_names = re.findall(r'"?([A-Za-z_]+)"?', pds_value(text, "AXIS_NAME") or "")
            axes = [name.lower() for name in axis_names[:3]] if len(axis_names) >= 3 else ["sample", "band", "line"]
            pointer_value = pds_value(text, "^QUBE") or ""

        if not object_kind or not shape or any(dim <= 0 for dim in shape):
            continue
        endian = "little" if "LSB" in sample_type or "PC_" in sample_type else "big"
        numeric = "uint" if "UNSIGNED" in sample_type else "int"
        file_name, record_index = pds_pointer(pointer_value)
        source = pds_payload_source(label, file_name)
        if not source:
            continue
        record_bytes = int((pds_value(text, "RECORD_BYTES") or "0").split()[0] or "0")
        offset = max(record_index - 1, 0) * record_bytes if record_bytes else 0
        data = source.read_bytes()
        expected = math.prod(shape) * 2
        payload = data[offset : offset + expected]
        if len(payload) != expected:
            continue
        write_sample(
            data_root=data_root,
            out_dir=out_dir,
            rows=rows,
            dataset_id=args.dataset_id,
            series_id=args.series_id,
            source_path=source,
            sample_name=source.stem,
            payload=payload,
            numeric_kind=numeric,
            endianness=endian,
            geometry="3d_cube" if len(shape) == 3 else "2d_raster",
            shape=shape,
            axes=axes,
            extra={"container_format": "pds3", "pds_object": object_kind, "sample_type": sample_type},
        )


def build_gltf(paths: list[Path], args: argparse.Namespace, data_root: Path, out_dir: Path, rows: list[dict[str, Any]]) -> None:
    for path in paths:
        if path.suffix.lower() != ".glb":
            continue
        data = path.read_bytes()
        if len(data) < 20 or data[:4] != b"glTF":
            continue
        version, _length = struct.unpack_from("<II", data, 4)
        if version != 2:
            continue
        offset = 12
        json_doc = None
        bin_chunk = b""
        while offset + 8 <= len(data):
            chunk_len, chunk_type = struct.unpack_from("<II", data, offset)
            offset += 8
            chunk = data[offset : offset + chunk_len]
            offset += chunk_len
            if chunk_type == 0x4E4F534A:
                json_doc = json.loads(chunk.rstrip(b" \0").decode("utf-8"))
            elif chunk_type == 0x004E4942:
                bin_chunk = chunk
        if not json_doc or not bin_chunk:
            continue
        buffer_views = json_doc.get("bufferViews", [])
        accessors = json_doc.get("accessors", [])
        meshes = json_doc.get("meshes", [])
        index_accessors: set[int] = set()
        for mesh in meshes:
            for primitive in mesh.get("primitives", []):
                if "indices" in primitive:
                    index_accessors.add(int(primitive["indices"]))
        for accessor_index in sorted(index_accessors):
            if accessor_index >= len(accessors):
                continue
            accessor = accessors[accessor_index]
            if accessor.get("componentType") != 5123 or accessor.get("type") != "SCALAR":
                continue
            view_index = accessor.get("bufferView")
            if view_index is None or int(view_index) >= len(buffer_views):
                continue
            view = buffer_views[int(view_index)]
            if view.get("byteStride"):
                continue
            count = int(accessor.get("count", 0))
            start = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
            byte_length = count * 2
            payload = bin_chunk[start : start + byte_length]
            if len(payload) != byte_length:
                continue
            write_sample(
                data_root=data_root,
                out_dir=out_dir,
                rows=rows,
                dataset_id=args.dataset_id,
                series_id=args.series_id,
                source_path=path,
                sample_name=f"{path.stem}_indices_{accessor_index}",
                payload=payload,
                numeric_kind="uint",
                endianness="little",
                geometry="1d_mesh_index_accessor",
                shape=[count],
                axes=["index"],
                extra={"container_format": "glb", "accessor_index": accessor_index},
            )


def exr_header(data: bytes) -> tuple[int, int, list[tuple[str, int]], tuple[int, int, int, int], int] | None:
    if len(data) < 16 or struct.unpack_from("<I", data, 0)[0] != 20000630:
        return None
    offset = 8
    channels: list[tuple[str, int]] = []
    data_window = (0, 0, -1, -1)
    compression = -1
    while offset < len(data):
        end = data.find(b"\0", offset)
        if end < 0:
            return None
        name = data[offset:end].decode("ascii", "replace")
        offset = end + 1
        if not name:
            break
        end = data.find(b"\0", offset)
        if end < 0:
            return None
        attr_type = data[offset:end].decode("ascii", "replace")
        offset = end + 1
        if offset + 4 > len(data):
            return None
        size = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        value = data[offset : offset + size]
        offset += size
        if name == "channels" and attr_type == "chlist":
            pos = 0
            while pos < len(value):
                end_name = value.find(b"\0", pos)
                if end_name < 0:
                    break
                channel_name = value[pos:end_name].decode("ascii", "replace")
                pos = end_name + 1
                if not channel_name:
                    break
                if pos + 16 > len(value):
                    break
                pixel_type = struct.unpack_from("<I", value, pos)[0]
                pos += 16
                channels.append((channel_name, pixel_type))
        elif name == "dataWindow" and attr_type == "box2i" and len(value) == 16:
            data_window = struct.unpack("<iiii", value)
        elif name == "compression" and attr_type == "compression" and value:
            compression = value[0]
    return offset, compression, channels, data_window, len(channels)


def build_exr(paths: list[Path], args: argparse.Namespace, data_root: Path, out_dir: Path, rows: list[dict[str, Any]]) -> None:
    for path in paths:
        data = path.read_bytes()
        parsed = exr_header(data)
        if not parsed:
            continue
        offset, compression, channels, data_window, channel_count = parsed
        if compression != 0 or not channels or any(pixel_type != 1 for _, pixel_type in channels):
            continue
        x_min, y_min, x_max, y_max = data_window
        width = x_max - x_min + 1
        height = y_max - y_min + 1
        if width <= 0 or height <= 0:
            continue
        chunk_count = height
        table_bytes = chunk_count * 8
        chunk_table_end = offset + table_bytes
        if chunk_table_end > len(data):
            continue
        planes = {name: bytearray() for name, _ in channels}
        chunk_offsets = [struct.unpack_from("<Q", data, offset + i * 8)[0] for i in range(chunk_count)]
        for chunk_offset in chunk_offsets:
            if chunk_offset + 8 > len(data):
                break
            y, packed_size = struct.unpack_from("<iI", data, chunk_offset)
            payload = data[chunk_offset + 8 : chunk_offset + 8 + packed_size]
            expected = width * channel_count * 2
            if len(payload) != expected:
                break
            pos = 0
            for name, _ in channels:
                planes[name].extend(payload[pos : pos + width * 2])
                pos += width * 2
        else:
            for name, payload in planes.items():
                if len(payload) != width * height * 2:
                    continue
                write_sample(
                    data_root=data_root,
                    out_dir=out_dir,
                    rows=rows,
                    dataset_id=args.dataset_id,
                    series_id=args.series_id,
                    source_path=path,
                    sample_name=f"{path.stem}_{name}",
                    payload=bytes(payload),
                    numeric_kind="float",
                    endianness="little",
                    geometry="2d_raster",
                    shape=[height, width],
                    axes=["y", "x"],
                    extra={"container_format": "openexr", "channel": name, "compression": "none"},
                )


BUILDERS = {
    "dicom": ((".dcm", ".dicom", ""), build_dicom),
    "wav": ((".wav",), build_wav),
    "segy": ((".sgy", ".segy"), build_segy),
    "las": ((".las", ".laz"), build_las),
    "tiff": ((".tif", ".tiff"), build_tiff),
    "envi": ((".hdr", ".img", ".dat", ".raw"), build_envi),
    "pds": ((".lbl", ".img", ".dat", ".qub", ".xml"), build_pds),
    "gltf": ((".glb",), build_gltf),
    "exr": ((".exr",), build_exr),
}


def summarize_and_validate(rows: list[dict[str, Any]], max_primary_bytes: int) -> dict[str, Any]:
    if not rows:
        raise SystemExit("no native 16-bit samples accepted")
    sizes = [int(row["sample_size_bytes"]) for row in rows]
    values = [int(row["value_count"]) for row in rows]
    total_bytes = sum(sizes)
    total_values = sum(values)
    median_values = statistics.median(values)
    if total_bytes > max_primary_bytes:
        raise SystemExit(f"primary output exceeds cap: {total_bytes} > {max_primary_bytes}")
    if total_bytes < MIN_PRIMARY_BYTES or total_values < MIN_PRIMARY_VALUES or median_values < MIN_MEDIAN_VALUES:
        raise SystemExit(
            f"below floor: samples={len(rows)} bytes={total_bytes} values={total_values} median_values={median_values}"
        )
    return {
        "sample_count": len(rows),
        "primary_bytes": total_bytes,
        "primary_values": total_values,
        "min_sample_bytes": min(sizes),
        "p25_sample_bytes": statistics.quantiles(sizes, n=4, method="inclusive")[0] if len(sizes) > 1 else sizes[0],
        "median_sample_bytes": statistics.median(sizes),
        "p75_sample_bytes": statistics.quantiles(sizes, n=4, method="inclusive")[2] if len(sizes) > 1 else sizes[0],
        "max_sample_bytes": max(sizes),
        "unique_sample_sizes": len(set(sizes)),
        "same_size_fraction": max(Counter(sizes).values()) / len(sizes),
    }


def build(args: argparse.Namespace) -> int:
    data_root = Path(args.repo_root) / args.data_dir
    download_dir = data_root / "downloads" / args.dataset_id
    extracted_dir = data_root / "extracted" / args.dataset_id
    filtered_dir = data_root / "filtered" / args.dataset_id
    index_dir = data_root / "index" / args.dataset_id
    samples_dir = data_root / "samples" / args.dataset_id
    out_dir = samples_dir / args.series_id
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    filtered_dir.mkdir(parents=True, exist_ok=True)
    index_dir.mkdir(parents=True, exist_ok=True)

    suffixes, builder = BUILDERS[args.format]
    roots = extract_archives(download_dir, extracted_dir, args.max_extracted_bytes)
    paths = scan_files(roots, suffixes)
    if args.format == "dicom":
        paths = [p for p in paths if p.is_file()]
    rows: list[dict[str, Any]] = []
    builder(paths, args, data_root, out_dir, rows)
    stats = summarize_and_validate(rows, args.max_primary_bytes)
    stats.update({"dataset_id": args.dataset_id, "series_id": args.series_id, "format": args.format})
    (filtered_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    print(
        "built "
        f"samples={stats['sample_count']} primary_bytes={stats['primary_bytes']} "
        f"size_range={stats['min_sample_bytes']}/{stats['median_sample_bytes']}/{stats['max_sample_bytes']}"
    )
    return 0


def verify(args: argparse.Namespace) -> int:
    data_root = Path(args.repo_root) / args.data_dir
    index_path = data_root / "index" / args.dataset_id / "samples.jsonl"
    stats_path = data_root / "filtered" / args.dataset_id / "ingest_stats.json"
    if not index_path.exists() or not stats_path.exists():
        raise SystemExit("missing samples index or ingest stats")
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in rows:
        if row["dataset_id"] != args.dataset_id or row["series_id"] != args.series_id:
            raise SystemExit(f"unexpected row identity: {row}")
        if int(row["bit_width"]) != 16 or int(row["element_size_bytes"]) != 2:
            raise SystemExit(f"unexpected bit width: {row}")
        path = data_root / row["sample_path"]
        if not path.is_file():
            raise SystemExit(f"missing sample: {path}")
        actual = path.stat().st_size
        if actual != int(row["sample_size_bytes"]) or actual != int(row["value_count"]) * 2:
            raise SystemExit(f"size mismatch: {path}")
        if int(row["value_count"]) < 1:
            raise SystemExit(f"empty sample: {path}")
    stats = summarize_and_validate(rows, args.max_primary_bytes)
    recorded = json.loads(stats_path.read_text(encoding="utf-8"))
    if int(recorded.get("primary_bytes", -1)) != stats["primary_bytes"]:
        raise SystemExit("ingest stats do not match sample index")
    print(
        "verified "
        f"samples={stats['sample_count']} primary_values={stats['primary_values']} "
        f"primary_bytes={stats['primary_bytes']} size_range={stats['min_sample_bytes']}/"
        f"{stats['median_sample_bytes']}/{stats['max_sample_bytes']} "
        f"same_size_fraction={stats['same_size_fraction']:.6f}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract native 16-bit numeric samples from local source files.")
    parser.add_argument("command", choices=["build", "verify"])
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--series-id", required=True)
    parser.add_argument("--format", choices=sorted(BUILDERS), required=True)
    parser.add_argument("--repo-root", default=os.getcwd())
    parser.add_argument("--data-dir", default=os.environ.get("DATA_DIR", ".data"))
    parser.add_argument("--max-primary-bytes", type=int, default=MAX_PRIMARY_BYTES)
    parser.add_argument("--max-extracted-bytes", type=int, default=int(os.environ.get("MAX_EXTRACTED_BYTES", "2000000000")))
    args = parser.parse_args()
    if args.command == "build":
        return build(args)
    return verify(args)


if __name__ == "__main__":
    raise SystemExit(main())
