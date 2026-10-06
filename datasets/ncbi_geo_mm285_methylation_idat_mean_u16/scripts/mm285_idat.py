#!/usr/bin/env python3
"""Illumina IDAT v3 decoding, download validation and build for
ncbi_geo_mm285_methylation_idat_mean_u16 (GEO GSE290585, GPL30650 MM285).

Pure standard library; no network I/O (download.sh fetches with curl).

Subcommands
  check-license   README.ftp still carries the NCBI public-data sentence
  check-filelist  every pinned (name, size) appears unchanged in filelist.txt
  check-matrix    series matrix: GSE290585 / GPL30650 / Mus musculus, and every
                  pinned GSM lists exactly the pinned Grn/Red IDAT names
  check-idats     structural validation of every downloaded IDAT
  build           emit one uint16 Mean sample per IDAT plus the sample index
  selftest        parser self-test on synthetic IDAT inputs

IDAT v3 layout (little-endian): b"IDAT", int64 version (=3), int32 nFields,
then nFields x (uint16 field code, int64 byte offset). Field 1000 holds int32
N (bead types read); field 102 holds N int32 IlluminaIDs, 103 N uint16 SD,
104 N uint16 Mean, 107 N uint8 NBeads, 200 the int32-counted MidBlock;
402/403/404 are .NET 7-bit-length-prefixed strings (chip barcode, chip type,
array position such as R01C01).
"""
from __future__ import annotations

import argparse
import collections
import csv
import gzip
import hashlib
import json
import os
import re
import shutil
import struct
import sys
import zlib
from array import array
from pathlib import Path

DATASET_ID = "ncbi_geo_mm285_methylation_idat_mean_u16"
SERIES_ACCESSION = "GSE290585"
PLATFORM = "GPL30650"
ORGANISM = "Mus musculus"
EXPECTED_N = 361_821
EXPECTED_CHIP_TYPE = "BeadChip 12x8"
LICENSE_SENTENCE = (
    "ALL DATA HERE IS PUBLIC, NON-SENSITIVE, UNRESTRICTED SCIENTIFIC DATA SHARING "
    "AMONG SCIENTIFIC COMMUNITIES"
)

MAGIC = b"IDAT"
CODE_NSNPS = 1000
CODE_ILLUMINA_ID = 102
CODE_SD = 103
CODE_MEAN = 104
CODE_NBEADS = 107
CODE_MIDBLOCK = 200
CODE_BARCODE = 402
CODE_CHIP_TYPE = 403
CODE_POSITION = 404
REQUIRED_CODES = (
    CODE_NSNPS,
    CODE_ILLUMINA_ID,
    CODE_SD,
    CODE_MEAN,
    CODE_NBEADS,
    CODE_MIDBLOCK,
    CODE_BARCODE,
    CODE_CHIP_TYPE,
    CODE_POSITION,
)

SERIES_BY_CHANNEL = {
    "Grn": "mm285_grn_bead_type_mean_u16",
    "Red": "mm285_red_bead_type_mean_u16",
}
NAME_RE = re.compile(r"^(GSM\d+)_(\d{12})_(R\d\dC\d\d)_(Grn|Red)\.idat\.gz$")

# Degenerate-array policy (verify_mm285.py re-declares the same thresholds).
MIN_DISTINCT = 2_000
MAX_ZERO_FRACTION = 0.001
MAX_P01 = 1_500
MIN_P50 = 200
MIN_P99 = 3_000
MIN_MAX = 10_000
MAX_NBEADS_ZERO_FRACTION = 0.01


class IdatError(ValueError):
    pass


# --------------------------------------------------------------------------
# pins and metadata


def load_pins(path: Path) -> list[dict]:
    rows = list(csv.DictReader(path.open(encoding="ascii"), delimiter="\t"))
    pins: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        match = NAME_RE.match(row["file_name"])
        if not match:
            raise SystemExit(f"pinned name does not match the IDAT pattern: {row['file_name']!r}")
        gsm, barcode, position, channel = match.groups()
        if (gsm, barcode, position, channel) != (row["gsm"], row["chip_barcode"], row["array_position"], row["channel"]):
            raise SystemExit(f"pinned columns disagree with file name: {row}")
        if row["file_name"] in seen:
            raise SystemExit(f"duplicate pinned file {row['file_name']}")
        seen.add(row["file_name"])
        digest = (row.get("sha256") or "").strip().lower()
        if digest and not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise SystemExit(f"malformed pinned sha256 for {row['file_name']}")
        pins.append(
            {
                "gsm": gsm,
                "file_name": row["file_name"],
                "size_bytes": int(row["size_bytes"]),
                "chip_barcode": barcode,
                "array_position": position,
                "channel": channel,
                "sha256": digest,
            }
        )
    channels = collections.defaultdict(list)
    for pin in pins:
        channels[pin["gsm"]].append(pin["channel"])
    bad = [gsm for gsm, chans in channels.items() if sorted(chans) != ["Grn", "Red"]]
    if bad:
        raise SystemExit(f"pinned GSMs without exactly one Grn and one Red IDAT: {bad[:5]}")
    return pins


def gsm_dir_url_part(gsm: str) -> str:
    return f"{gsm[:-3]}nnn/{gsm}"


def parse_series_matrix(path: Path) -> dict:
    """Return series-level fields and per-GSM annotations from the matrix."""
    series: dict[str, list[str]] = collections.defaultdict(list)
    sample_rows: dict[str, list[list[str]]] = collections.defaultdict(list)
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if line.startswith("!Series_"):
                parts = next(csv.reader([line], delimiter="\t"))
                series[parts[0]].extend(parts[1:])
            elif line.startswith("!Sample_"):
                parts = next(csv.reader([line], delimiter="\t"))
                sample_rows[parts[0]].append(parts[1:])
    accessions = sample_rows.get("!Sample_geo_accession", [[]])[0]
    if not accessions:
        raise SystemExit("series matrix has no !Sample_geo_accession row")

    def single(key: str) -> list[str]:
        rows = sample_rows.get(key, [])
        if len(rows) != 1 or len(rows[0]) != len(accessions):
            raise SystemExit(f"series matrix row {key} missing or ragged")
        return rows[0]

    samples: dict[str, dict] = {}
    organisms = single("!Sample_organism_ch1")
    platforms = single("!Sample_platform_id")
    titles = single("!Sample_title")
    for i, gsm in enumerate(accessions):
        samples[gsm] = {
            "organism": organisms[i],
            "platform": platforms[i],
            "title": titles[i],
            "characteristics": {},
            "supplementary": [],
        }
    for row in sample_rows.get("!Sample_characteristics_ch1", []):
        for gsm, value in zip(accessions, row):
            if ": " in value:
                key, val = value.split(": ", 1)
                samples[gsm]["characteristics"][key.strip()] = val.strip()
    for row in sample_rows.get("!Sample_supplementary_file", []):
        for gsm, value in zip(accessions, row):
            if value and value != "NONE":
                samples[gsm]["supplementary"].append(value.rsplit("/", 1)[-1])
    return {"series": dict(series), "samples": samples}


def matrix_annotations(matrix: dict, pins: list[dict]) -> dict[str, dict]:
    """Validate the matrix against the pins; return per-GSM annotations."""
    series = matrix["series"]
    if series.get("!Series_geo_accession") != [SERIES_ACCESSION]:
        raise SystemExit(f"series matrix is not {SERIES_ACCESSION}: {series.get('!Series_geo_accession')}")
    if PLATFORM not in series.get("!Series_platform_id", []):
        raise SystemExit(f"series matrix platform is not {PLATFORM}")
    expected_names: dict[str, set[str]] = collections.defaultdict(set)
    for pin in pins:
        expected_names[pin["gsm"]].add(pin["file_name"])
    out: dict[str, dict] = {}
    for gsm, names in expected_names.items():
        sample = matrix["samples"].get(gsm)
        if sample is None:
            raise SystemExit(f"pinned {gsm} missing from series matrix")
        if sample["organism"] != ORGANISM:
            raise SystemExit(f"{gsm}: organism {sample['organism']!r} != {ORGANISM!r}")
        if sample["platform"] != PLATFORM:
            raise SystemExit(f"{gsm}: platform {sample['platform']!r} != {PLATFORM}")
        idats = {name for name in sample["supplementary"] if name.endswith(".idat.gz")}
        if idats != names:
            raise SystemExit(f"{gsm}: matrix IDAT names {sorted(idats)} != pinned {sorted(names)}")
        chars = sample["characteristics"]
        conversion = chars.get("cytosine_conversion_type", "")
        if conversion not in {"BS", "bACE"}:
            raise SystemExit(f"{gsm}: unexpected cytosine_conversion_type {conversion!r}")
        out[gsm] = {
            "cytosine_conversion_type": conversion,
            "tissue": chars.get("tissue", ""),
            "sample_title": sample["title"],
        }
    return out


# --------------------------------------------------------------------------
# IDAT decoding


def read_dotnet_string(buf: bytes, offset: int) -> str:
    length = 0
    shift = 0
    for _ in range(5):
        if offset >= len(buf):
            raise IdatError("string length prefix runs past end of file")
        byte = buf[offset]
        offset += 1
        length |= (byte & 0x7F) << shift
        if byte < 0x80:
            break
        shift += 7
    else:
        raise IdatError("string length prefix longer than 5 bytes")
    end = offset + length
    if end > len(buf):
        raise IdatError("string runs past end of file")
    try:
        return buf[offset:end].decode("ascii")
    except UnicodeDecodeError as exc:
        raise IdatError(f"non-ASCII string field: {exc}") from exc


def parse_idat(raw: bytes, expected_n: int = EXPECTED_N) -> dict:
    if len(raw) < 16:
        raise IdatError("file shorter than the IDAT header")
    if raw[:4] != MAGIC:
        raise IdatError(f"bad magic {raw[:4]!r}")
    version = struct.unpack_from("<q", raw, 4)[0]
    if version != 3:
        raise IdatError(f"unsupported IDAT version {version}")
    n_fields = struct.unpack_from("<i", raw, 12)[0]
    if not 1 <= n_fields <= 64:
        raise IdatError(f"implausible field count {n_fields}")
    table_end = 16 + 10 * n_fields
    if table_end > len(raw):
        raise IdatError("field table runs past end of file")
    offsets: dict[int, int] = {}
    for i in range(n_fields):
        code, offset = struct.unpack_from("<Hq", raw, 16 + 10 * i)
        if code in offsets:
            raise IdatError(f"duplicate field code {code}")
        if not table_end <= offset < len(raw):
            raise IdatError(f"field {code} offset {offset} outside the payload")
        offsets[code] = offset
    missing = [code for code in REQUIRED_CODES if code not in offsets]
    if missing:
        raise IdatError(f"missing field codes {missing}")
    n = struct.unpack_from("<i", raw, offsets[CODE_NSNPS])[0]
    if n != expected_n:
        raise IdatError(f"nSNPsRead {n} != expected {expected_n}")
    o_id, o_sd, o_mean, o_nb, o_mid = (
        offsets[CODE_ILLUMINA_ID],
        offsets[CODE_SD],
        offsets[CODE_MEAN],
        offsets[CODE_NBEADS],
        offsets[CODE_MIDBLOCK],
    )
    if o_sd - o_id != 4 * n:
        raise IdatError(f"off(103)-off(102)={o_sd - o_id} != 4N={4 * n}")
    if o_mean - o_sd != 2 * n:
        raise IdatError(f"off(104)-off(103)={o_mean - o_sd} != 2N={2 * n}")
    if o_nb - o_mean != 2 * n:
        raise IdatError(f"off(107)-off(104)={o_nb - o_mean} != 2N={2 * n}")
    if o_mid < o_nb + n:
        raise IdatError("MidBlock overlaps the NBeads array")
    if o_mid + 4 > len(raw):
        raise IdatError("MidBlock count past end of file")
    mid_count = struct.unpack_from("<i", raw, o_mid)[0]
    if mid_count != n or o_mid + 4 + 4 * mid_count > len(raw):
        raise IdatError(f"MidBlock count {mid_count} != N={n} or truncated")
    return {
        "version": version,
        "n_fields": n_fields,
        "n": n,
        "offsets": offsets,
        "barcode": read_dotnet_string(raw, offsets[CODE_BARCODE]),
        "chip_type": read_dotnet_string(raw, offsets[CODE_CHIP_TYPE]),
        "position": read_dotnet_string(raw, offsets[CODE_POSITION]),
        "illumina_id": raw[o_id : o_id + 4 * n],
        "mean": raw[o_mean : o_mean + 2 * n],
        "nbeads": raw[o_nb : o_nb + n],
    }


def le_array(code: str, data: bytes) -> array:
    values = array(code)
    values.frombytes(data)
    if sys.byteorder == "big":
        values.byteswap()
    return values


def check_illumina_ids(id_bytes: bytes) -> None:
    ids = le_array("i", id_bytes)
    if ids[0] <= 0:
        raise IdatError("non-positive IlluminaID")
    for i in range(1, len(ids)):
        if ids[i] <= ids[i - 1]:
            raise IdatError(f"IlluminaIDs not strictly increasing at index {i}")


def intensity_profile(mean_bytes: bytes) -> dict:
    values = le_array("H", mean_bytes)
    counts = collections.Counter(values)
    keys = sorted(counts)
    total = len(values)
    targets = {"p01": 0.01, "p50": 0.50, "p99": 0.99}
    ranks = {name: int(total * q) for name, q in targets.items()}
    found: dict[str, int] = {}
    cumulative = 0
    for key in keys:
        cumulative += counts[key]
        for name, rank in ranks.items():
            if name not in found and cumulative > rank:
                found[name] = key
    return {
        "min": keys[0],
        "max": keys[-1],
        "distinct_values": len(keys),
        "zero_count": counts.get(0, 0),
        "p01": found["p01"],
        "p50": found["p50"],
        "p99": found["p99"],
        "sum": sum(values),
    }


def degenerate_reasons(profile: dict, nbeads_zero: int, n: int) -> list[str]:
    reasons = []
    if profile["distinct_values"] < MIN_DISTINCT:
        reasons.append(f"distinct {profile['distinct_values']} < {MIN_DISTINCT}")
    if profile["zero_count"] > MAX_ZERO_FRACTION * n:
        reasons.append(f"zero Mean count {profile['zero_count']} > {MAX_ZERO_FRACTION:.3%} of N")
    if profile["p01"] > MAX_P01:
        reasons.append(f"p01 {profile['p01']} > {MAX_P01} (no background floor)")
    if profile["p50"] < MIN_P50:
        reasons.append(f"median {profile['p50']} < {MIN_P50} (dead array)")
    if profile["p99"] < MIN_P99:
        reasons.append(f"p99 {profile['p99']} < {MIN_P99} (no bright probes)")
    if profile["max"] < MIN_MAX:
        reasons.append(f"max {profile['max']} < {MIN_MAX} (no bright probes)")
    if nbeads_zero > MAX_NBEADS_ZERO_FRACTION * n:
        reasons.append(f"NBeads==0 for {nbeads_zero} bead types > {MAX_NBEADS_ZERO_FRACTION:.1%} of N")
    return reasons


def decode_pinned(path: Path, pin: dict) -> tuple[dict, bytes]:
    """Size, gzip, IDAT structure, and filename identity checks."""
    if not path.is_file():
        raise IdatError("missing local file")
    size = path.stat().st_size
    if size != pin["size_bytes"]:
        raise IdatError(f"size {size} != pinned {pin['size_bytes']}")
    compressed = path.read_bytes()
    if pin.get("sha256") and hashlib.sha256(compressed).hexdigest() != pin["sha256"]:
        raise IdatError("sha256 differs from the pinned value")
    try:
        raw = gzip.decompress(compressed)
    except (OSError, EOFError, zlib.error) as exc:
        raise IdatError(f"gzip decode failed: {exc}") from exc
    parsed = parse_idat(raw)
    if parsed["barcode"] != pin["chip_barcode"]:
        raise IdatError(f"barcode field {parsed['barcode']!r} != file name {pin['chip_barcode']!r}")
    if parsed["position"] != pin["array_position"]:
        raise IdatError(f"position field {parsed['position']!r} != file name {pin['array_position']!r}")
    if parsed["chip_type"] != EXPECTED_CHIP_TYPE:
        raise IdatError(f"chip type {parsed['chip_type']!r} != {EXPECTED_CHIP_TYPE!r}")
    check_illumina_ids(parsed["illumina_id"])
    return parsed, compressed


# --------------------------------------------------------------------------
# subcommands


def cmd_check_license(args: argparse.Namespace) -> int:
    text = Path(args.readme).read_text(encoding="utf-8", errors="replace")
    normalized = re.sub(r"\s+", " ", text).upper()
    if LICENSE_SENTENCE not in normalized:
        print("FATAL: README.ftp no longer contains the NCBI public-data sentence", file=sys.stderr)
        return 1
    print(f"license_sentence_ok=1 readme_sha256={hashlib.sha256(text.encode('utf-8')).hexdigest()}")
    return 0


def cmd_check_filelist(args: argparse.Namespace) -> int:
    pins = load_pins(Path(args.pins))
    listed: dict[str, int] = {}
    for line in Path(args.filelist).read_text(encoding="ascii").splitlines():
        parts = line.split("\t")
        if len(parts) == 5 and parts[0] == "File":
            listed[parts[1]] = int(parts[3])
    if len(listed) < 1000:
        print(f"FATAL: filelist.txt lists only {len(listed)} files; expected the full GSE290585 listing", file=sys.stderr)
        return 1
    problems = []
    for pin in pins:
        size = listed.get(pin["file_name"])
        if size is None:
            problems.append(f"{pin['file_name']}: not listed")
        elif size != pin["size_bytes"]:
            problems.append(f"{pin['file_name']}: listed size {size} != pinned {pin['size_bytes']}")
    if problems:
        print("FATAL: pinned IDATs disagree with filelist.txt:\n  " + "\n  ".join(problems[:20]), file=sys.stderr)
        return 1
    total = sum(pin["size_bytes"] for pin in pins)
    print(f"filelist_ok=1 listed_files={len(listed)} pinned_files={len(pins)} pinned_bytes={total}")
    return 0


def cmd_check_matrix(args: argparse.Namespace) -> int:
    pins = load_pins(Path(args.pins))
    annotations = matrix_annotations(parse_series_matrix(Path(args.matrix)), pins)
    conv = collections.Counter(a["cytosine_conversion_type"] for a in annotations.values())
    tissues = collections.Counter(a["tissue"] for a in annotations.values())
    print(f"matrix_ok=1 gsms={len(annotations)} organism={ORGANISM!r} platform={PLATFORM}")
    print(f"conversion_types={dict(sorted(conv.items()))} tissues={len(tissues)}")
    return 0


def cmd_check_idats(args: argparse.Namespace) -> int:
    pins = load_pins(Path(args.pins))
    idat_dir = Path(args.idat_dir)
    failures: list[str] = []
    id_hashes: collections.Counter = collections.Counter()
    means: dict[tuple[str, str], str] = {}
    for pin in pins:
        path = idat_dir / pin["file_name"]
        try:
            parsed, _ = decode_pinned(path, pin)
        except IdatError as exc:
            failures.append(f"{pin['file_name']}: {exc}")
            if args.delete_corrupt and path.is_file() and ("gzip" in str(exc) or "sha256" in str(exc)):
                path.unlink()
                failures[-1] += " (deleted; re-run download.sh to refetch)"
            continue
        id_hashes[hashlib.sha256(parsed["illumina_id"]).hexdigest()] += 1
        means[(pin["gsm"], pin["channel"])] = hashlib.sha256(parsed["mean"]).hexdigest()
    if len(id_hashes) > 1:
        failures.append(f"IlluminaID order differs across files: {dict(id_hashes)}")
    for gsm in sorted({pin["gsm"] for pin in pins}):
        grn, red = means.get((gsm, "Grn")), means.get((gsm, "Red"))
        if grn is not None and grn == red:
            failures.append(f"{gsm}: Grn and Red Mean arrays are identical")
    if failures:
        print("FATAL: IDAT validation failed:\n  " + "\n  ".join(failures[:40]), file=sys.stderr)
        return 1
    print(
        f"idat_validation=ok files={len(pins)} version=3 N={EXPECTED_N} chip_type={EXPECTED_CHIP_TYPE!r} "
        f"illumina_id_order_sha256={next(iter(id_hashes))}"
    )
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    data_root = Path(args.data_root).resolve()
    pins = load_pins(Path(args.pins))
    annotations = matrix_annotations(parse_series_matrix(Path(args.matrix)), pins)
    idat_dir = Path(args.idat_dir)
    samples_dir = Path(args.samples_dir)
    index_path = Path(args.index)
    stats_path = Path(args.stats)
    if samples_dir.name != DATASET_ID:
        raise SystemExit(f"refusing to clean unexpected samples dir {samples_dir}")
    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    for series_id in SERIES_BY_CHANNEL.values():
        (samples_dir / series_id).mkdir(parents=True, exist_ok=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    failures: list[str] = []
    id_order_hash = None
    pair_hash: dict[tuple[str, str], str] = {}
    for pin in pins:
        path = idat_dir / pin["file_name"]
        try:
            parsed, compressed = decode_pinned(path, pin)
        except IdatError as exc:
            failures.append(f"{pin['file_name']}: {exc}")
            continue
        ids_hash = hashlib.sha256(parsed["illumina_id"]).hexdigest()
        if id_order_hash is None:
            id_order_hash = ids_hash
        elif ids_hash != id_order_hash:
            failures.append(f"{pin['file_name']}: IlluminaID order differs from the first file")
            continue
        mean = parsed["mean"]
        n = parsed["n"]
        profile = intensity_profile(mean)
        nbeads_zero = parsed["nbeads"].count(0)
        reasons = degenerate_reasons(profile, nbeads_zero, n)
        if reasons:
            failures.append(f"{pin['file_name']}: degenerate array: {'; '.join(reasons)}")
            continue
        sample_hash = hashlib.sha256(mean).hexdigest()
        pair_hash[(pin["gsm"], pin["channel"])] = sample_hash
        series_id = SERIES_BY_CHANNEL[pin["channel"]]
        stem = pin["file_name"][: -len(".idat.gz")]
        out_path = samples_dir / series_id / f"{stem}.bin"
        tmp_path = out_path.with_suffix(".bin.tmp")
        # IDAT stores Mean as little-endian uint16; the slice is written unchanged.
        tmp_path.write_bytes(mean)
        os.replace(tmp_path, out_path)
        annotation = annotations[pin["gsm"]]
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": series_id,
                "sample_path": out_path.resolve().relative_to(data_root).as_posix(),
                "numeric_kind": "uint",
                "bit_width": 16,
                "endianness": "little",
                "element_size_bytes": 2,
                "sample_size_bytes": len(mean),
                "value_count": n,
                "gsm": pin["gsm"],
                "chip_barcode": pin["chip_barcode"],
                "array_position": pin["array_position"],
                "channel": pin["channel"],
                "cytosine_conversion_type": annotation["cytosine_conversion_type"],
                "tissue": annotation["tissue"],
                "source_file": pin["file_name"],
                "source_gz_bytes": len(compressed),
                "source_gz_sha256": hashlib.sha256(compressed).hexdigest(),
                "sample_sha256": sample_hash,
                "min": profile["min"],
                "max": profile["max"],
                "median": profile["p50"],
                "distinct_values": profile["distinct_values"],
                "zero_count": profile["zero_count"],
                "nbeads_zero_count": nbeads_zero,
                "illumina_id_order_sha256": ids_hash,
            }
        )
    for gsm in sorted({pin["gsm"] for pin in pins}):
        grn, red = pair_hash.get((gsm, "Grn")), pair_hash.get((gsm, "Red"))
        if grn is not None and grn == red:
            failures.append(f"{gsm}: Grn and Red Mean arrays are identical")
    if failures:
        print("FATAL: build rejected pinned IDATs (fix the pin list explicitly; no padding):", file=sys.stderr)
        for failure in failures[:40]:
            print(f"  {failure}", file=sys.stderr)
        return 1

    tmp_index = index_path.with_suffix(".jsonl.tmp")
    with tmp_index.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=False) + "\n")
    os.replace(tmp_index, index_path)

    stats: dict = {
        "dataset_id": DATASET_ID,
        "series_accession": SERIES_ACCESSION,
        "platform": PLATFORM,
        "pinned_files": len(pins),
        "emitted_samples": len(rows),
        "values_per_sample": EXPECTED_N,
        "illumina_id_order_sha256": id_order_hash,
        "series": {},
        "cytosine_conversion_type_gsms": dict(
            sorted(collections.Counter(a["cytosine_conversion_type"] for a in annotations.values()).items())
        ),
        "tissue_gsms": dict(sorted(collections.Counter(a["tissue"] for a in annotations.values()).items())),
    }
    for channel, series_id in SERIES_BY_CHANNEL.items():
        subset = [row for row in rows if row["series_id"] == series_id]
        stats["series"][series_id] = {
            "channel": channel,
            "sample_count": len(subset),
            "total_size_bytes": sum(row["sample_size_bytes"] for row in subset),
            "min": min(row["min"] for row in subset),
            "max": max(row["max"] for row in subset),
            "median_of_sample_medians": sorted(row["median"] for row in subset)[len(subset) // 2],
        }
    stats_path.write_text(json.dumps(stats, indent=1) + "\n", encoding="utf-8")
    total = sum(row["sample_size_bytes"] for row in rows)
    print(f"build_ok=1 samples={len(rows)} total_bytes={total}")
    for series_id, entry in stats["series"].items():
        print(f"  {series_id}: {json.dumps(entry)}")
    print(f"  conversion types: {stats['cytosine_conversion_type_gsms']}")
    return 0


# --------------------------------------------------------------------------
# self-test


def dotnet_string(text: str) -> bytes:
    data = text.encode("ascii")
    length = len(data)
    prefix = bytearray()
    while True:
        byte = length & 0x7F
        length >>= 7
        if length:
            prefix.append(byte | 0x80)
        else:
            prefix.append(byte)
            break
    return bytes(prefix) + data


def synthetic_idat(n: int, means: list[int], barcode: str, position: str, *, version: int = 3,
                   chip_type: str = EXPECTED_CHIP_TYPE, sd_gap_delta: int = 0, long_string: bool = False) -> bytes:
    """Build an IDAT v3 byte string with the same field order as real MM285 files."""
    codes = [1000, 102, 103, 104, 107, 200, 400, 401, 402, 403, 404, 405, 410, 406, 407, 408, 409, 510, 300]
    header_len = 16 + 10 * len(codes)
    body = bytearray()
    offsets: dict[int, int] = {}

    def put(code: int, payload: bytes) -> None:
        offsets[code] = header_len + len(body)
        body.extend(payload)

    ids = [1_600_000 + 7 * i for i in range(n)]
    put(1000, struct.pack("<i", n))
    put(102, struct.pack(f"<{n}i", *ids))
    put(103, struct.pack(f"<{n}H", *[(v // 10) & 0xFFFF for v in means]) + b"\0" * sd_gap_delta)
    put(104, struct.pack(f"<{n}H", *means))
    put(107, bytes((3 + i % 20) for i in range(n)))
    put(200, struct.pack("<i", n) + struct.pack(f"<{n}i", *ids))
    put(400, struct.pack("<i", 0))
    put(401, dotnet_string(""))
    put(402, dotnet_string(barcode))
    put(403, dotnet_string(chip_type))
    put(404, dotnet_string(position + ("X" * 200 if long_string else "")))
    for code in (405, 410, 406, 407, 408, 409, 510, 300):
        put(code, dotnet_string("x"))
    header = bytearray(MAGIC + struct.pack("<qi", version, len(codes)))
    for code in codes:
        header.extend(struct.pack("<Hq", code, offsets[code]))
    return bytes(header) + bytes(body)


def cmd_selftest(args: argparse.Namespace) -> int:
    n = 4_000
    means = [(i * 2654435761) % 30_000 + 60 for i in range(n)]
    raw = synthetic_idat(n, means, "206102340052", "R01C01")
    parsed = parse_idat(raw, expected_n=n)
    assert parsed["mean"] == struct.pack(f"<{n}H", *means), "Mean slice mismatch"
    assert list(le_array("H", parsed["mean"])) == means
    assert parsed["barcode"] == "206102340052" and parsed["position"] == "R01C01"
    assert parsed["chip_type"] == EXPECTED_CHIP_TYPE
    check_illumina_ids(parsed["illumina_id"])
    long = parse_idat(synthetic_idat(n, means, "206102340052", "R01C01", long_string=True), expected_n=n)
    assert long["position"] == "R01C01" + "X" * 200, "multi-byte .NET length prefix"
    profile = intensity_profile(parsed["mean"])
    assert profile["min"] == min(means) and profile["max"] == max(means)
    assert profile["p50"] == sorted(means)[n // 2]
    assert profile["distinct_values"] == len(set(means))

    def expect_error(blob: bytes, needle: str, expected_n: int = n) -> None:
        try:
            parse_idat(blob, expected_n=expected_n)
        except IdatError as exc:
            assert needle in str(exc), f"expected {needle!r}, got {exc}"
            return
        raise AssertionError(f"no IdatError for {needle!r}")

    expect_error(b"IDAX" + raw[4:], "bad magic")
    expect_error(synthetic_idat(n, means, "1", "R01C01", version=2), "unsupported IDAT version")
    expect_error(raw, "nSNPsRead", expected_n=n + 1)
    expect_error(synthetic_idat(n, means, "1", "R01C01", sd_gap_delta=2), "off(104)-off(103)")
    expect_error(raw[:100], "field table runs past end")
    expect_error(raw[: len(raw) - 50], "outside the payload")

    # identity checks through decode_pinned on a gzip file in a temp dir
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        blob = gzip.compress(synthetic_idat(EXPECTED_N, [100 + (i % 20_000) for i in range(EXPECTED_N)], "206102340052", "R01C01"))
        path = Path(tmp) / "GSM1_206102340052_R01C01_Grn.idat.gz"
        path.write_bytes(blob)
        pin = {"size_bytes": len(blob), "chip_barcode": "206102340052", "array_position": "R01C01", "sha256": ""}
        parsed_full, _ = decode_pinned(path, pin)
        assert len(parsed_full["mean"]) == 2 * EXPECTED_N
        decode_pinned(path, dict(pin, sha256=hashlib.sha256(blob).hexdigest()))
        for key, value, needle in (
            ("chip_barcode", "206102340053", "barcode field"),
            ("array_position", "R02C01", "position field"),
            ("size_bytes", len(blob) + 1, "size"),
            ("sha256", "0" * 64, "sha256"),
        ):
            bad_pin = dict(pin, **{key: value})
            try:
                decode_pinned(path, bad_pin)
            except IdatError as exc:
                assert needle in str(exc), exc
            else:
                raise AssertionError(f"decode_pinned accepted bad {key}")
        corrupt = bytearray(blob)
        corrupt[len(corrupt) // 2] ^= 0xFF
        path.write_bytes(bytes(corrupt))
        try:
            decode_pinned(path, pin)
        except IdatError as exc:
            assert "gzip" in str(exc) or "IDAT" in str(exc) or "field" in str(exc), exc
        else:
            raise AssertionError("corrupted gzip accepted")
    flat = intensity_profile(struct.pack(f"<{n}H", *([500] * n)))
    assert degenerate_reasons(flat, 0, n), "constant array must be degenerate"
    lively = intensity_profile(struct.pack(f"<{n}H", *means))
    assert not degenerate_reasons(lively, 0, n), degenerate_reasons(lively, 0, n)
    assert degenerate_reasons(lively, n // 10, n), "NBeads==0 excess must be degenerate"
    print("selftest_ok=1")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("check-license")
    p.add_argument("--readme", required=True)
    p.set_defaults(func=cmd_check_license)
    p = sub.add_parser("check-filelist")
    p.add_argument("--filelist", required=True)
    p.add_argument("--pins", required=True)
    p.set_defaults(func=cmd_check_filelist)
    p = sub.add_parser("check-matrix")
    p.add_argument("--matrix", required=True)
    p.add_argument("--pins", required=True)
    p.set_defaults(func=cmd_check_matrix)
    p = sub.add_parser("check-idats")
    p.add_argument("--idat-dir", required=True)
    p.add_argument("--pins", required=True)
    p.add_argument("--delete-corrupt", action="store_true")
    p.set_defaults(func=cmd_check_idats)
    p = sub.add_parser("build")
    for name in ("--idat-dir", "--pins", "--matrix", "--samples-dir", "--index", "--stats", "--data-root"):
        p.add_argument(name, required=True)
    p.set_defaults(func=cmd_build)
    p = sub.add_parser("selftest")
    p.set_defaults(func=cmd_selftest)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
