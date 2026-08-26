#!/usr/bin/env python3
"""Build and independently verify SDO/AIA logical int32 image planes."""
from __future__ import annotations

import argparse
from array import array
import csv
import hashlib
import html
import json
import math
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
from typing import Callable


DATASET_ID = "nasa_sdo_aia_synoptic_i32"
SERIES_ID = "sdo_aia_synoptic_stored_pixels_i32"
WAVELENGTHS = (94, 131, 171, 193, 211, 304, 335, 1600, 1700, 4500)
WIDTH = 1024
HEIGHT = 1024
VALUE_COUNT = WIDTH * HEIGHT
SAMPLE_BYTES = VALUE_COUNT * 4
BSCALE = 0.0625
BZERO = 0.0
BLANK = -(2**31)
EXPECTED_RIGHTS = {
    "sdo_copyright": (
        18_193,
        "e0f4c7de9bbbac0fc1abbbed3c1b116a386adae61f0e950e3f5392124b42d291",
    ),
    "nasa_guidelines": (
        313_822,
        "e2089ae202702b52cf4225dbe7c05b21cd61738ba9cce168353a52c6715713b7",
    ),
}
Consumer = Callable[[dict[str, object], bytes, dict[str, object]], None]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_selection(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8", newline="") as handle:
        raw = list(csv.DictReader(handle, delimiter="\t"))
    if len(raw) != len(WAVELENGTHS):
        raise SystemExit(f"selection has {len(raw)} rows; expected {len(WAVELENGTHS)}")
    rows: list[dict[str, object]] = []
    for source in raw:
        row = {
            **source,
            "wavelength": int(source["wavelength"]),
            "size_bytes": int(source["size_bytes"]),
            "bitpix": int(source["bitpix"]),
            "width": int(source["width"]),
            "height": int(source["height"]),
            "bscale": float(source["bscale"]),
            "bzero": float(source["bzero"]),
        }
        rows.append(row)
    if tuple(row["wavelength"] for row in rows) != WAVELENGTHS:
        raise SystemExit("selection wavelengths or order changed")
    for row in rows:
        if (
            row["bitpix"] != 32
            or row["width"] != WIDTH
            or row["height"] != HEIGHT
            or row["bscale"] != BSCALE
            or row["bzero"] != BZERO
            or row["compression"] != "RICE_1"
        ):
            raise SystemExit(f"invalid selected schema for wavelength {row['wavelength']}")
        if "/mostrecent/" in str(row["url"]) or "/nrt/" in str(row["url"]):
            raise SystemExit("mutable JSOC URL in selection")
    return rows


def validate_source(path: Path, row: dict[str, object]) -> None:
    if not path.is_file():
        raise SystemExit(f"missing selected FITS source: {path}")
    size = path.stat().st_size
    digest = file_hash(path)
    if size != row["size_bytes"] or digest != row["sha256"]:
        raise SystemExit(
            f"source identity mismatch for wavelength {row['wavelength']}: "
            f"size={size} sha256={digest}"
        )


def validate_rights(sdo_copyright: Path, nasa_guidelines: Path) -> None:
    for label, path in (
        ("sdo_copyright", sdo_copyright),
        ("nasa_guidelines", nasa_guidelines),
    ):
        if not path.is_file():
            raise SystemExit(f"missing rights evidence: {path}")
        expected_size, expected_hash = EXPECTED_RIGHTS[label]
        if path.stat().st_size != expected_size or file_hash(path) != expected_hash:
            raise SystemExit(f"rights evidence identity mismatch: {path}")
    sdo = re.sub(
        r"\s+", " ", html.unescape(sdo_copyright.read_text(errors="replace"))
    ).lower()
    nasa = re.sub(
        r"\s+", " ", html.unescape(nasa_guidelines.read_text(errors="replace"))
    ).lower()
    if "sdo images and movies are not copyrighted unless explicitly noted" not in sdo:
        raise SystemExit("pinned SDO page lacks expected non-copyright statement")
    if "generally are not subject to copyright in the united states" not in nasa:
        raise SystemExit("pinned NASA page lacks expected copyright statement")


def parse_value(card: str) -> str:
    token = card[10:80].split("/", 1)[0].strip()
    return token.strip("'").strip()


def read_primary_image(path: Path) -> tuple[bytes, dict[str, object]]:
    data = path.read_bytes()
    cards: dict[str, str] = {}
    end = None
    for offset in range(0, len(data) - 79, 80):
        card = data[offset : offset + 80].decode("ascii", errors="strict")
        key = card[:8].strip()
        if key == "END":
            end = offset + 80
            break
        if card[8:10] == "= ":
            cards[key] = parse_value(card)
    if end is None:
        raise SystemExit(f"missing FITS END card: {path}")
    header_bytes = math.ceil(end / 2880) * 2880
    expected = {
        "SIMPLE": "T",
        "BITPIX": "32",
        "NAXIS": "2",
        "NAXIS1": str(WIDTH),
        "NAXIS2": str(HEIGHT),
    }
    for key, value in expected.items():
        if cards.get(key) != value:
            raise SystemExit(f"unexpected unpacked FITS {key}={cards.get(key)!r}: {path}")
    if float(cards.get("BSCALE", "1")) != BSCALE or float(cards.get("BZERO", "0")) != BZERO:
        raise SystemExit(f"unpacked FITS scaling changed: {path}")
    if int(cards.get("BLANK", str(BLANK))) != BLANK:
        raise SystemExit(f"unexpected FITS BLANK sentinel: {path}")
    payload = data[header_bytes : header_bytes + SAMPLE_BYTES]
    if len(payload) != SAMPLE_BYTES:
        raise SystemExit(f"truncated unpacked FITS image payload: {path}")
    padded_end = header_bytes + math.ceil(SAMPLE_BYTES / 2880) * 2880
    if len(data) != padded_end or any(data[header_bytes + SAMPLE_BYTES : padded_end]):
        raise SystemExit(f"unexpected unpacked FITS trailing bytes: {path}")

    values = array("i")
    values.frombytes(payload)
    if values.itemsize != 4:
        raise SystemExit("host array('i') is not 32 bits")
    if sys.byteorder == "little":
        values.byteswap()
    blank_count = values.count(BLANK)
    if blank_count:
        raise SystemExit(f"unpacked FITS contains {blank_count} undefined pixels: {path}")
    minimum = min(values)
    maximum = max(values)
    distinct = len(set(values))
    if distinct < 2:
        raise SystemExit(f"constant unpacked FITS image: {path}")
    if sys.byteorder == "little":
        output = values.tobytes()
    else:
        output_values = array("i", values)
        output_values.byteswap()
        output = output_values.tobytes()
    return output, {
        "minimum": minimum,
        "maximum": maximum,
        "distinct_values": distinct,
        "date_obs": cards.get("DATE-OBS", ""),
        "wavelength_header": int(cards.get("WAVELNTH", "0")),
        "blank_count": blank_count,
        "bscale": BSCALE,
        "bzero": BZERO,
    }


def funpack_version(funpack: Path) -> str:
    if not funpack.is_file() or not funpack.stat().st_mode & 0o111:
        raise SystemExit(f"missing executable funpack; run build_tool.sh: {funpack}")
    result = subprocess.run([str(funpack), "-V"], check=True, capture_output=True, text=True)
    return (result.stdout + result.stderr).strip()


def scan(
    selection_path: Path,
    fits_dir: Path,
    funpack: Path,
    work_dir: Path,
    consumer: Consumer | None = None,
) -> dict[str, object]:
    rows = load_selection(selection_path)
    version = funpack_version(funpack)
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)
    hashes: set[str] = set()
    profiles: list[dict[str, object]] = []
    for row in rows:
        source = fits_dir / Path(str(row["url"])).name
        validate_source(source, row)
        unpacked = work_dir / source.name
        result = subprocess.run(
            [str(funpack), "-C", "-O", str(unpacked), str(source)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            detail = (result.stdout + result.stderr).strip()
            raise SystemExit(f"funpack failed for {source.name}: {detail}")
        payload, metrics = read_primary_image(unpacked)
        if metrics["wavelength_header"] != row["wavelength"]:
            raise SystemExit(f"wavelength header mismatch in {source.name}")
        digest = hashlib.sha256(payload).hexdigest()
        if digest in hashes:
            raise SystemExit(f"duplicate decoded image: {source.name}")
        hashes.add(digest)
        profile = {
            "wavelength_angstrom": row["wavelength"],
            "source_name": source.name,
            "source_size_bytes": row["size_bytes"],
            "source_sha256": row["sha256"],
            "value_count": VALUE_COUNT,
            "sample_size_bytes": len(payload),
            "sha256": digest,
            **metrics,
        }
        profiles.append(profile)
        if consumer is not None:
            consumer(row, payload, profile)
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "decoder": version,
        "sample_count": len(profiles),
        "value_count": len(profiles) * VALUE_COUNT,
        "total_size_bytes": len(profiles) * SAMPLE_BYTES,
        "sample_shape": [HEIGHT, WIDTH],
        "bscale": BSCALE,
        "bzero": BZERO,
        "blank_pixel_count": sum(int(profile["blank_count"]) for profile in profiles),
        "images": profiles,
    }


def build(args: argparse.Namespace) -> None:
    validate_rights(args.sdo_copyright, args.nasa_guidelines)
    if args.samples_dir.exists():
        shutil.rmtree(args.samples_dir)
    series_dir = args.samples_dir / SERIES_ID
    series_dir.mkdir(parents=True)
    args.index.parent.mkdir(parents=True, exist_ok=True)
    index_rows: list[dict[str, object]] = []

    def emit(row: dict[str, object], payload: bytes, profile: dict[str, object]) -> None:
        wavelength = int(row["wavelength"])
        output = series_dir / f"aia_20250101_{wavelength:04d}_i32_1024x1024.bin"
        output.write_bytes(payload)
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "source_sample": (args.fits_dir / str(profile["source_name"])).relative_to(args.data_root).as_posix(),
            "source_url": row["url"],
            "source_sha256": profile["source_sha256"],
            "wavelength_angstrom": wavelength,
            "date_obs": profile["date_obs"],
            "numeric_kind": "int",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "value_count": VALUE_COUNT,
            "sample_size_bytes": SAMPLE_BYTES,
            "sample_format": "raw homogeneous signed-int32 solar image plane",
            "sample_geometry": "sdo_aia_synoptic_wavelength_image_2d",
            "sample_rank": 2,
            "sample_shape": [HEIGHT, WIDTH],
            "sample_axes": ["y", "x"],
            "natural_record_kind": "complete_aia_synoptic_wavelength_image",
            "physical_scale": BSCALE,
            "physical_zero": BZERO,
            "minimum": profile["minimum"],
            "maximum": profile["maximum"],
            "distinct_values": profile["distinct_values"],
            "sha256": profile["sha256"],
        })

    summary = scan(args.selection, args.fits_dir, args.funpack, args.work_dir, emit)
    args.index.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in index_rows),
        encoding="utf-8",
    )
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "images"}, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    validate_rights(args.sdo_copyright, args.nasa_guidelines)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or stats; run build first")
    rows = [json.loads(line) for line in args.index.read_text().splitlines() if line.strip()]
    cursor = 0
    expected_outputs: set[Path] = set()

    def compare(row: dict[str, object], payload: bytes, profile: dict[str, object]) -> None:
        nonlocal cursor
        if cursor >= len(rows):
            raise SystemExit("sample index has fewer rows than selected FITS files")
        indexed = rows[cursor]
        cursor += 1
        required = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "source_sha256": profile["source_sha256"],
            "wavelength_angstrom": row["wavelength"],
            "date_obs": profile["date_obs"],
            "numeric_kind": "int",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "value_count": VALUE_COUNT,
            "sample_size_bytes": SAMPLE_BYTES,
            "physical_scale": BSCALE,
            "physical_zero": BZERO,
            "minimum": profile["minimum"],
            "maximum": profile["maximum"],
            "distinct_values": profile["distinct_values"],
            "sha256": profile["sha256"],
        }
        for key, expected in required.items():
            if indexed.get(key) != expected:
                raise SystemExit(f"index mismatch at wavelength {row['wavelength']}: {key}")
        output = args.data_root / str(indexed.get("sample_path", ""))
        if not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"output differs from fresh CFITSIO decode: {output}")
        expected_outputs.add(output.resolve())

    summary = scan(args.selection, args.fits_dir, args.funpack, args.work_dir, compare)
    if cursor != len(rows):
        raise SystemExit("sample index has extra rows")
    actual_outputs = {
        path.resolve()
        for path in (args.data_root / "samples" / DATASET_ID).glob("*/*.bin")
    }
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contains missing, stale, or extra outputs")
    if json.loads(args.stats.read_text()) != summary:
        raise SystemExit("ingest stats differ from fresh CFITSIO decode")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_samples": cursor,
        "verified_values": summary["value_count"],
        "verified_bytes": summary["total_size_bytes"],
        "blank_pixel_count": summary["blank_pixel_count"],
    }, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("build", "verify"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--selection", type=Path, required=True)
        sub.add_argument("--fits-dir", type=Path, required=True)
        sub.add_argument("--funpack", type=Path, required=True)
        sub.add_argument("--sdo-copyright", type=Path, required=True)
        sub.add_argument("--nasa-guidelines", type=Path, required=True)
        sub.add_argument("--work-dir", type=Path, required=True)
        sub.add_argument("--index", type=Path, required=True)
        sub.add_argument("--stats", type=Path, required=True)
        sub.add_argument("--data-root", type=Path, required=True)
        if command == "build":
            sub.add_argument("--samples-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        build(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
