#!/usr/bin/env python3
"""DANDI:000020 Allen Patch-seq current-clamp membrane-potential sweeps (float32).

Commands
  select         derive sources.tsv from the pinned assets.yaml (documented rule)
  check-sources  re-derive the selection and require it to equal sources.tsv
  check-file     validate one downloaded NWB blob (size, SHA-256, HDF5 superblock)
  build          decode every selected CurrentClampSeries sweep into one sample
  verify         independently re-decode, re-trim and byte-compare every sample
"""
from __future__ import annotations

import argparse
import array
import csv
import hashlib
import io
import json
import math
import mmap
import re
import shutil
import statistics
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nwb_hdf5 as H5  # noqa: E402

DATASET_ID = "dandi_000020_patchseq_current_clamp_f32"
SERIES_ID = "patchseq_cc_membrane_potential_f32"
DANDISET_VERSION = "0.210913.1639"
ASSETS_YAML_BYTES = 11_176_113
ASSETS_YAML_SHA256 = "65ef568e334d0e765283e64b0f203a7eaa545a0d1003bcc064ad2f3557eba8fe"
DANDISET_YAML_SHA256 = "c0667d27943cd65f270d14249d84ec27d8375aa9f43f9b3e3e67e8347d167897"
EXPECTED_ASSET_COUNT = 4_435
EXPECTED_SUBJECT_COUNT = 1_040
EXPECTED_ASSET_BYTES = 141_856_436_428
S3_BLOB_PREFIX = "https://dandiarchive.s3.amazonaws.com/blobs/"

# Selection rule (see README): subjects sorted by numeric donor id, restricted
# to the id window below; SELECT_COUNT donors taken at evenly spaced ranks over
# that window; for each donor, the lexicographically first NWB asset path.
SUBJECT_ID_MIN = 732_239_848
SUBJECT_ID_MAX = 10**12
SELECT_COUNT = 16

# Sweep regime: exactly one acquisition regime is emitted.
NEURODATA_TYPE = "CurrentClampSeries"
REQUIRED_UNIT = "volts"
REQUIRED_CONVERSION = struct.unpack("<f", struct.pack("<f", 0.001))[0]
REQUIRED_RATE_HZ = 50_000.0
REQUIRED_GAIN = struct.unpack("<f", struct.pack("<f", 0.05))[0]
# Every stored word must equal float32(k / (ITC18_CODES_PER_VOLT * gain)) for an
# integer ADC code k, the division evaluated in double precision with the stored
# float32 gain (0.05000000074505806), i.e. a 0.00625 mV (1/160 mV) step.
ITC18_CODES_PER_VOLT = 3200
MIN_SAMPLE_VALUES = 1_000
PRIMARY_CAP_BYTES = 700_000_000
HARD_CAP_BYTES = 1_000_000_000

# Interior MIES zero fill (unacquired span inside a sweep, kept as stored):
# runs of >= FILL_RUN_MIN consecutive +/-0.0 words. Allowed only in X7Ramp
# sweeps, at most one run per sweep, at most FILL_MAX_FRACTION of the sweep.
FILL_RUN_MIN = 50
FILL_ALLOWED_STIMULUS_PREFIX = "X7Ramp"
FILL_MAX_RUNS_PER_SAMPLE = 1
FILL_MAX_FRACTION = 0.02

# Pinned realized output (first successful build, 2026-10-05).
EXPECTED_SAMPLE_COUNT: int | None = 736
EXPECTED_TOTAL_BYTES: int | None = 449_102_516
EXPECTED_AGGREGATE_SHA256: str | None = "c0e5fda2f6674ec41a987907331a9b32ec5466264b36b37ce9cf1ca822be1515"
EXPECTED_INTERIOR_FILL_SAMPLES: int | None = 44
EXPECTED_INTERIOR_FILL_VALUES: int | None = 62_033

SOURCES_FIELDS = (
    "rank",
    "subject_id",
    "asset_path",
    "asset_id",
    "size_bytes",
    "sha256",
    "url",
    "local_name",
)


# ---------------------------------------------------------------------------- utils
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def read_sources(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not rows or tuple(rows[0].keys()) != SOURCES_FIELDS:
        raise SystemExit(f"unexpected sources.tsv header in {path}")
    return rows


def render_sources(rows: list[dict[str, object]]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=SOURCES_FIELDS, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


# ---------------------------------------------------------------- assets.yaml
def parse_assets_yaml(path: Path) -> list[dict[str, object]]:
    """Line parser for the DANDI 0.4.4 assets.yaml (one '- ' item per asset)."""
    if path.stat().st_size != ASSETS_YAML_BYTES or sha256_file(path) != ASSETS_YAML_SHA256:
        raise SystemExit("assets.yaml size/SHA-256 differs from the pinned 0.210913.1639 manifest")
    assets: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    patterns = {
        "size": re.compile(r"^  contentSize: (\d+)$"),
        "url": re.compile(r"^  - (https://dandiarchive\.s3\.amazonaws\.com/blobs/\S+)$"),
        "sha256": re.compile(r"^    dandi:sha2-256: ([0-9a-f]{64})$"),
        "path": re.compile(r"^  path: (\S+)$"),
        "asset_id": re.compile(r"^  identifier: ([0-9a-f-]{36})$"),
        "format": re.compile(r"^  encodingFormat: (\S+)$"),
        "access": re.compile(r"^    status: (dandi:\S+)$"),
    }
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if line.startswith("- "):
                if current is not None:
                    assets.append(current)
                current = {"urls": []}
                continue
            if current is None:
                continue
            for key, pattern in patterns.items():
                match = pattern.match(line)
                if not match:
                    continue
                if key == "url":
                    current["urls"].append(match.group(1))
                elif key in current:
                    if key == "access":
                        break
                    raise SystemExit(f"duplicate {key} in asset {current.get('path')}")
                else:
                    current[key] = int(match.group(1)) if key == "size" else match.group(1)
                break
    if current is not None:
        assets.append(current)
    for asset in assets:
        missing = [k for k in ("size", "sha256", "path", "asset_id", "format", "access") if k not in asset]
        if missing or len(asset["urls"]) != 1:
            raise SystemExit(f"incomplete asset entry {asset.get('path')}: missing={missing}")
        if asset["format"] != "application/x-nwb" or asset["access"] != "dandi:OpenAccess":
            raise SystemExit(f"unexpected asset format/access: {asset['path']}")
        if not re.fullmatch(r"sub-(\d+)/sub-\1_ses-\d+_icephys\.nwb", str(asset["path"])):
            raise SystemExit(f"unexpected asset path: {asset['path']}")
    subjects = {str(a["path"]).split("/")[0] for a in assets}
    total = sum(int(a["size"]) for a in assets)
    if (len(assets), len(subjects), total) != (
        EXPECTED_ASSET_COUNT,
        EXPECTED_SUBJECT_COUNT,
        EXPECTED_ASSET_BYTES,
    ):
        raise SystemExit(f"asset inventory changed: assets={len(assets)} subjects={len(subjects)} bytes={total}")
    return assets


def derive_selection(assets: list[dict[str, object]]) -> list[dict[str, object]]:
    by_subject: dict[int, list[dict[str, object]]] = {}
    for asset in assets:
        subject = int(str(asset["path"]).split("/")[0][4:])
        by_subject.setdefault(subject, []).append(asset)
    window = sorted(s for s in by_subject if SUBJECT_ID_MIN <= s <= SUBJECT_ID_MAX)
    if len(window) < SELECT_COUNT:
        raise SystemExit(f"subject window has only {len(window)} donors")
    if SELECT_COUNT == 1:
        ranks = [0]
    else:
        ranks = [round(i * (len(window) - 1) / (SELECT_COUNT - 1)) for i in range(SELECT_COUNT)]
    if len(set(ranks)) != SELECT_COUNT:
        raise SystemExit("selection ranks collide")
    rows = []
    for rank in ranks:
        subject = window[rank]
        asset = sorted(by_subject[subject], key=lambda a: str(a["path"]))[0]
        url = str(asset["urls"][0])
        if not url.startswith(S3_BLOB_PREFIX):
            raise SystemExit(f"unexpected blob URL {url}")
        rows.append(
            {
                "rank": rank,
                "subject_id": subject,
                "asset_path": asset["path"],
                "asset_id": asset["asset_id"],
                "size_bytes": asset["size"],
                "sha256": asset["sha256"],
                "url": url,
                "local_name": str(asset["path"]).split("/")[1],
            }
        )
    return rows


def command_select(args: argparse.Namespace) -> None:
    rows = derive_selection(parse_assets_yaml(args.assets_yaml))
    args.sources.write_text(render_sources(rows), encoding="utf-8")
    total = sum(int(r["size_bytes"]) for r in rows)
    print(f"selected donors={len(rows)} bytes={total}")


def command_check_sources(args: argparse.Namespace) -> None:
    rows = derive_selection(parse_assets_yaml(args.assets_yaml))
    expected = render_sources(rows)
    actual = args.sources.read_text(encoding="utf-8")
    if actual != expected:
        raise SystemExit("sources.tsv differs from the selection re-derived from assets.yaml")
    total = sum(int(r["size_bytes"]) for r in rows)
    print(f"sources_check=ok donors={len(rows)} bytes={total}")


def command_check_dandiset(args: argparse.Namespace) -> None:
    text = args.dandiset_yaml.read_text(encoding="utf-8")
    digest = hashlib.sha256(args.dandiset_yaml.read_bytes()).hexdigest()
    required = [
        "id: DANDI:000020/0.210913.1639",
        "license:\n- spdx:CC-BY-4.0",
        "- status: dandi:OpenAccess",
        "name: Patch-seq recordings from mouse visual cortex",
        "https://dandiarchive.s3.amazonaws.com/dandisets/000020/0.210913.1639/assets.yaml",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        raise SystemExit(f"dandiset.yaml lacks expected identity/license lines: {missing}")
    if digest != DANDISET_YAML_SHA256:
        raise SystemExit(f"dandiset.yaml SHA-256 changed: {digest}")
    print("dandiset_check=ok license=CC-BY-4.0 access=dandi:OpenAccess version=0.210913.1639")


def command_check_file(args: argparse.Namespace) -> None:
    path = args.file
    if not path.is_file() or path.stat().st_size != args.size:
        raise SystemExit(f"wrong size for {path}: expected {args.size}")
    digest = sha256_file(path)
    if digest != args.sha256:
        raise SystemExit(f"SHA-256 mismatch for {path}: {digest}")
    with path.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as raw:
        h5 = H5.H5File(raw)
        root = h5.links(h5.root_header)
        if root.get("acquisition", ("", None))[0] != "hard":
            raise SystemExit(f"{path.name}: no /acquisition group")
        if h5.attributes(h5.root_header).get("neurodata_type") != "NWBFile":
            raise SystemExit(f"{path.name}: root is not an NWBFile")
    print(f"file_check=ok {path.name} bytes={args.size}")


# ---------------------------------------------------------------- sweep decoding
def is_padding_word(word: int) -> bool:
    """+0.0, -0.0, or NaN: the unacquired tail MIES leaves after early termination."""
    if word & 0x7FFFFFFF == 0:
        return True
    return (word & 0x7F800000) == 0x7F800000 and (word & 0x007FFFFF) != 0


def trim_unacquired_tail(payload: bytes) -> int:
    """Number of leading values kept after removing the trailing padding run."""
    words = memoryview(payload).cast("I")
    keep = len(words)
    while keep and is_padding_word(words[keep - 1]):
        keep -= 1
    return keep


def zero_runs(values: array.array) -> list[list[int]]:
    """[start, length] of every maximal run of +/-0.0 values."""
    runs: list[list[int]] = []
    for index in [i for i, v in enumerate(values) if v == 0.0]:
        if runs and runs[-1][0] + runs[-1][1] == index:
            runs[-1][1] += 1
        else:
            runs.append([index, 1])
    return runs


def scan_values(payload: bytes, gain: float) -> dict[str, object]:
    values = array.array("f")
    values.frombytes(payload)
    words = memoryview(payload).cast("I")
    nonfinite = sum(1 for w in words if (w & 0x7F800000) == 0x7F800000)
    if nonfinite:
        return {"nonfinite": nonfinite}
    divisor = ITC18_CODES_PER_VOLT * gain
    codes = [round(v * divisor) for v in values]
    rebuilt = array.array("f", [k / divisor for k in codes])
    off_lattice = 0 if rebuilt == values else sum(1 for a, b in zip(rebuilt, values) if a != b)
    runs = zero_runs(values)
    fill_runs = [run for run in runs if run[1] >= FILL_RUN_MIN]
    return {
        "nonfinite": 0,
        "minimum": min(values),
        "maximum": max(values),
        "off_lattice": off_lattice,
        "adc_code_min": min(codes),
        "adc_code_max": max(codes),
        "interior_fill_runs": fill_runs,
        "interior_fill_values": sum(run[1] for run in fill_runs),
        "isolated_zero_values": sum(run[1] for run in runs if run[1] < FILL_RUN_MIN),
    }


def check_fill_policy(label: str, stimulus: object, runs: list[list[int]], count: int) -> None:
    fill = sum(run[1] for run in runs)
    if not runs:
        return
    if not str(stimulus or "").startswith(FILL_ALLOWED_STIMULUS_PREFIX):
        raise SystemExit(f"{label}: interior zero-fill run in non-{FILL_ALLOWED_STIMULUS_PREFIX} sweep ({stimulus})")
    if len(runs) > FILL_MAX_RUNS_PER_SAMPLE:
        raise SystemExit(f"{label}: {len(runs)} interior zero-fill runs (max {FILL_MAX_RUNS_PER_SAMPLE})")
    if fill > FILL_MAX_FRACTION * count:
        raise SystemExit(f"{label}: interior zero fill {fill}/{count} exceeds {FILL_MAX_FRACTION:.0%}")


def iter_sweeps(path: Path):
    """Yield (decision dict, payload or None) for every acquisition series, in name order."""
    with path.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as raw:
        h5 = H5.H5File(raw)
        root = h5.links(h5.root_header)
        kind, acq_addr = root["acquisition"]
        if kind != "hard":
            raise SystemExit(f"{path.name}: /acquisition is not a hard link")
        acquisition = h5.links(acq_addr)
        for name in sorted(acquisition):
            link_kind, addr = acquisition[name]
            decision: dict[str, object] = {"sweep_name": name}
            if link_kind != "hard":
                decision.update(neurodata_type=None, status="excluded", reason="not_hard_link")
                yield decision, None
                continue
            attrs = h5.attributes(addr)
            neurodata_type = attrs.get("neurodata_type")
            decision["neurodata_type"] = neurodata_type
            decision["sweep_number"] = attrs.get("sweep_number")
            decision["stimulus_description"] = attrs.get("stimulus_description")
            if neurodata_type != NEURODATA_TYPE:
                decision.update(status="excluded", reason="neurodata_type")
                yield decision, None
                continue
            members = h5.links(addr)
            for required in ("data", "starting_time", "gain"):
                if members.get(required, ("", None))[0] != "hard":
                    raise SystemExit(f"{path.name}/{name}: missing member {required}")
            data_msgs = h5.messages(members["data"][1])
            data_attrs = h5.attributes(members["data"][1], data_msgs)
            info = h5.dataset_info(members["data"][1], data_msgs)
            dtype = info["dtype"]
            if dtype.cls != 1 or dtype.size != 4 or not dtype.little_endian:
                raise SystemExit(f"{path.name}/{name}: data is not little-endian float32")
            if data_attrs.get("unit") != REQUIRED_UNIT or data_attrs.get("conversion") != REQUIRED_CONVERSION:
                decision.update(status="excluded", reason="unit_or_conversion")
                yield decision, None
                continue
            rate = h5.attributes(members["starting_time"][1]).get("rate")
            gain_bytes, _ = h5.read_1d(h5.dataset_info(members["gain"][1]))
            if len(gain_bytes) != 4:
                raise SystemExit(f"{path.name}/{name}: gain is not a single float32")
            gain = struct.unpack("<f", gain_bytes)[0]
            decision["sampling_rate_hz"] = rate
            decision["gain"] = gain
            if rate != REQUIRED_RATE_HZ:
                decision.update(status="excluded", reason="sampling_rate")
                yield decision, None
                continue
            if gain != REQUIRED_GAIN:
                decision.update(status="excluded", reason="gain_regime")
                yield decision, None
                continue
            payload, stats = h5.read_1d(info)
            decision["stored_values"] = len(payload) // 4
            decision["chunks"] = stats["chunks"]
            decision["filters"] = stats.get("filter_ids", [])
            yield decision, payload


def evaluate_payload(decision: dict[str, object], payload: bytes) -> bytes | None:
    """Apply the missing-value policy; return the emitted bytes or None (excluded)."""
    keep = trim_unacquired_tail(payload)
    decision["trimmed_tail_values"] = len(payload) // 4 - keep
    kept = payload[: keep * 4]
    if keep < MIN_SAMPLE_VALUES:
        decision.update(status="excluded", reason="short_after_trim", value_count=keep)
        return None
    scan = scan_values(kept, float(decision["gain"]))
    if scan["nonfinite"]:
        decision.update(status="excluded", reason="interior_nonfinite", nonfinite=scan["nonfinite"])
        return None
    if scan["minimum"] == scan["maximum"]:
        decision.update(status="excluded", reason="constant")
        return None
    if scan["off_lattice"]:
        raise SystemExit(
            f"{decision['sweep_name']}: {scan['off_lattice']} words are not float32(k / "
            f"({ITC18_CODES_PER_VOLT} * gain)) for an integer ADC code k"
        )
    check_fill_policy(
        str(decision["sweep_name"]), decision.get("stimulus_description"), scan["interior_fill_runs"], keep
    )
    decision.update(status="emitted", value_count=keep, **{k: v for k, v in scan.items() if k != "nonfinite"})
    return kept


def sample_name(source: dict[str, str], sweep_name: str) -> str:
    stem = source["local_name"].removesuffix("_icephys.nwb")
    return f"{stem}__{sweep_name}.bin"


def index_row(source: dict[str, str], decision: dict[str, object], rel_path: str, digest: str) -> dict[str, object]:
    count = int(decision["value_count"])
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": rel_path,
        "numeric_kind": "float",
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "sample_size_bytes": count * 4,
        "value_count": count,
        "natural_record_kind": "nwb_current_clamp_series_sweep",
        "source_asset_path": source["asset_path"],
        "source_asset_id": source["asset_id"],
        "subject_id": int(source["subject_id"]),
        "sweep_name": decision["sweep_name"],
        "sweep_number": decision["sweep_number"],
        "stimulus_description": decision["stimulus_description"],
        "sampling_rate_hz": decision["sampling_rate_hz"],
        "stored_values": decision["stored_values"],
        "trimmed_tail_values": decision["trimmed_tail_values"],
        "interior_fill_runs": decision["interior_fill_runs"],
        "interior_fill_values": decision["interior_fill_values"],
        "gain": decision["gain"],
        "adc_code_min": decision["adc_code_min"],
        "adc_code_max": decision["adc_code_max"],
        "unit": "mV",
        "minimum": decision["minimum"],
        "maximum": decision["maximum"],
        "sample_sha256": digest,
    }


def process(args: argparse.Namespace, emit) -> dict[str, object]:
    """Shared traversal used by build (emit writes) and verify (emit compares)."""
    sources = read_sources(args.sources)
    download_dir = args.download_dir
    summary_files = []
    reasons: dict[str, int] = {}
    types: dict[str, int] = {}
    aggregate = hashlib.sha256()
    total_bytes = 0
    total_values = 0
    sample_sizes: list[int] = []
    minimum = math.inf
    maximum = -math.inf
    capped = False
    fill_samples = 0
    fill_runs = 0
    fill_values = 0
    fill_lengths: list[int] = []
    fill_by_stimulus: dict[str, int] = {}
    isolated_zero_values = 0
    tail_trimmed_samples = 0
    tail_trimmed_values = 0
    stored_values = 0
    code_min = math.inf
    code_max = -math.inf
    for source in sources:
        path = download_dir / source["local_name"]
        if not path.is_file() or path.stat().st_size != int(source["size_bytes"]):
            raise SystemExit(f"missing or wrong-sized download {path}")
        if sha256_file(path) != source["sha256"]:
            raise SystemExit(f"SHA-256 mismatch for {path}")
        file_samples = []
        file_reasons: dict[str, int] = {}
        for decision, payload in iter_sweeps(path):
            types[str(decision.get("neurodata_type"))] = types.get(str(decision.get("neurodata_type")), 0) + 1
            if payload is not None:
                kept = evaluate_payload(decision, payload)
                if kept is not None:
                    file_samples.append((decision, kept))
                    continue
            reason = str(decision.get("reason"))
            file_reasons[reason] = file_reasons.get(reason, 0) + 1
        file_bytes = sum(len(k) for _d, k in file_samples)
        if capped or total_bytes + file_bytes > PRIMARY_CAP_BYTES:
            capped = True
            summary_files.append(
                {"asset_path": source["asset_path"], "status": "skipped_primary_cap", "candidate_bytes": file_bytes}
            )
            continue
        for reason, count in file_reasons.items():
            reasons[reason] = reasons.get(reason, 0) + count
        for decision, kept in file_samples:
            digest = hashlib.sha256(kept).hexdigest()
            emit(source, decision, kept, digest)
            aggregate.update(kept)
            total_bytes += len(kept)
            total_values += len(kept) // 4
            sample_sizes.append(len(kept) // 4)
            minimum = min(minimum, float(decision["minimum"]))
            maximum = max(maximum, float(decision["maximum"]))
            code_min = min(code_min, int(decision["adc_code_min"]))
            code_max = max(code_max, int(decision["adc_code_max"]))
            isolated_zero_values += int(decision["isolated_zero_values"])
            stored_values += int(decision["stored_values"])
            if decision["trimmed_tail_values"]:
                tail_trimmed_samples += 1
                tail_trimmed_values += int(decision["trimmed_tail_values"])
            if decision["interior_fill_runs"]:
                fill_samples += 1
                fill_runs += len(decision["interior_fill_runs"])
                fill_values += int(decision["interior_fill_values"])
                fill_lengths.extend(run[1] for run in decision["interior_fill_runs"])
                stimulus = str(decision.get("stimulus_description"))
                fill_by_stimulus[stimulus] = fill_by_stimulus.get(stimulus, 0) + 1
        summary_files.append(
            {
                "asset_path": source["asset_path"],
                "status": "used",
                "emitted_sweeps": len(file_samples),
                "emitted_bytes": file_bytes,
                "excluded": file_reasons,
            }
        )
        print(
            f"file={source['local_name']} emitted={len(file_samples)} bytes={file_bytes} "
            f"excluded={file_reasons} running_bytes={total_bytes}",
            flush=True,
        )
    if total_bytes > HARD_CAP_BYTES:
        raise SystemExit(f"primary output {total_bytes} exceeds 1 GB")
    if not sample_sizes:
        raise SystemExit("no samples emitted")
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "dandiset_version": DANDISET_VERSION,
        "source_files": len(sources),
        "files_used": sum(1 for f in summary_files if f["status"] == "used"),
        "files_with_samples": sum(1 for f in summary_files if f.get("emitted_sweeps")),
        "sample_count": len(sample_sizes),
        "total_values": total_values,
        "total_size_bytes": total_bytes,
        "median_sample_values": statistics.median(sample_sizes),
        "min_sample_values": min(sample_sizes),
        "max_sample_values": max(sample_sizes),
        "minimum": minimum,
        "maximum": maximum,
        "adc_code_min": code_min,
        "adc_code_max": code_max,
        "lattice_rule": f"word == float32(k / ({ITC18_CODES_PER_VOLT} * float32(0.05))), k integer, division in double",
        "interior_fill_samples": fill_samples,
        "interior_fill_runs": fill_runs,
        "interior_fill_values": fill_values,
        "interior_fill_run_length_min": min(fill_lengths) if fill_lengths else 0,
        "interior_fill_run_length_max": max(fill_lengths) if fill_lengths else 0,
        "interior_fill_samples_by_stimulus": dict(sorted(fill_by_stimulus.items())),
        "isolated_zero_values": isolated_zero_values,
        "stored_values_of_emitted_sweeps": stored_values,
        "tail_trimmed_samples": tail_trimmed_samples,
        "tail_trimmed_values": tail_trimmed_values,
        "acquisition_series_by_type": dict(sorted(types.items())),
        "excluded_by_reason": dict(sorted(reasons.items())),
        "aggregate_sha256": aggregate.hexdigest(),
        "files": summary_files,
    }


def check_pins(summary: dict[str, object]) -> None:
    pins = {
        "sample_count": EXPECTED_SAMPLE_COUNT,
        "total_size_bytes": EXPECTED_TOTAL_BYTES,
        "aggregate_sha256": EXPECTED_AGGREGATE_SHA256,
        "interior_fill_samples": EXPECTED_INTERIOR_FILL_SAMPLES,
        "interior_fill_values": EXPECTED_INTERIOR_FILL_VALUES,
    }
    for key, expected in pins.items():
        if expected is not None and summary[key] != expected:
            raise SystemExit(f"pinned output mismatch {key}: {summary[key]!r} != {expected!r}")


def command_build(args: argparse.Namespace) -> None:
    if sys.byteorder != "little":
        raise SystemExit("build assumes a little-endian host")
    out_root = args.samples_dir / SERIES_ID
    tmp_root = args.samples_dir / f".{SERIES_ID}.tmp"
    if tmp_root.exists():
        shutil.rmtree(tmp_root)
    tmp_root.mkdir(parents=True)
    rows: list[dict[str, object]] = []

    def emit(source, decision, kept, digest):
        name = sample_name(source, str(decision["sweep_name"]))
        (tmp_root / name).write_bytes(kept)
        rel = (out_root / name).relative_to(args.data_root).as_posix()
        rows.append(index_row(source, decision, rel, digest))

    try:
        summary = process(args, emit)
        check_pins(summary)
    except BaseException:
        shutil.rmtree(tmp_root, ignore_errors=True)
        raise
    if out_root.exists():
        shutil.rmtree(out_root)
    tmp_root.replace(out_root)
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text(
        "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in rows), encoding="utf-8"
    )
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    brief = {k: v for k, v in summary.items() if k != "files"}
    print(json.dumps(brief, indent=2, sort_keys=True))


# ------------------------------------------------------------------- verification
def independent_profile(payload: bytes, row: dict[str, object]) -> tuple[float, float]:
    """Re-check an emitted sample from its bytes alone, without the build helpers."""
    if len(payload) % 4 or len(payload) // 4 < MIN_SAMPLE_VALUES:
        raise SystemExit("sample shorter than the minimum or not float32-aligned")
    count = len(payload) // 4
    values = array.array("f")
    values.frombytes(payload)
    if not all(math.isfinite(v) for v in values):
        raise SystemExit("sample contains non-finite values")
    if values[-1] == 0.0:
        raise SystemExit("sample ends with an untrimmed zero padding value")
    lo, hi = min(values), max(values)
    if lo == hi:
        raise SystemExit("constant sample")
    if lo < -250.0 or hi > 250.0:
        raise SystemExit(f"membrane potential outside the plausible +/-250 mV ADC span: {lo}..{hi}")

    # Interior zero fill: scan the raw words for runs of +/-0.0 bit patterns.
    runs: list[list[int]] = []
    start = -1
    for index, word in enumerate(memoryview(payload).cast("I")):
        if word & 0x7FFFFFFF == 0:
            if start < 0:
                start = index
        elif start >= 0:
            if index - start >= FILL_RUN_MIN:
                runs.append([start, index - start])
            start = -1
    if start >= 0 and count - start >= FILL_RUN_MIN:
        runs.append([start, count - start])
    fill = sum(length for _start, length in runs)
    if runs != row["interior_fill_runs"] or fill != row["interior_fill_values"]:
        raise SystemExit(f"interior fill runs differ from the index: {runs} vs {row['interior_fill_runs']}")
    if runs:
        if not str(row["stimulus_description"]).startswith(FILL_ALLOWED_STIMULUS_PREFIX):
            raise SystemExit(f"interior zero fill in a {row['stimulus_description']} sweep")
        if len(runs) > FILL_MAX_RUNS_PER_SAMPLE:
            raise SystemExit(f"{len(runs)} interior zero-fill runs in one sweep")
        if fill > FILL_MAX_FRACTION * count:
            raise SystemExit(f"interior zero fill {fill}/{count} above {FILL_MAX_FRACTION:.0%}")

    # Exact ADC lattice, compared bit for bit after repacking.
    if row["gain"] != REQUIRED_GAIN:
        raise SystemExit(f"unexpected gain {row['gain']}")
    divisor = ITC18_CODES_PER_VOLT * float(row["gain"])
    codes = [round(v * divisor) for v in values]
    repacked = struct.pack(f"<{count}f", *[math.copysign(k / divisor, v) for k, v in zip(codes, values)])
    if repacked != payload:
        raise SystemExit("sample words are not float32(k / (3200 * gain)) for integer ADC codes k")
    if min(codes) != row["adc_code_min"] or max(codes) != row["adc_code_max"]:
        raise SystemExit("ADC code range differs from the index")
    return lo, hi


def command_verify(args: argparse.Namespace) -> None:
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    stored = json.loads(args.stats.read_text(encoding="utf-8"))
    out_root = args.samples_dir / SERIES_ID
    cursor = 0
    seen: set[Path] = set()
    hashes: set[str] = set()

    def compare(source, decision, kept, digest):
        nonlocal cursor
        if cursor >= len(rows):
            raise SystemExit("index has fewer rows than re-derived sweeps")
        row = rows[cursor]
        cursor += 1
        name = sample_name(source, str(decision["sweep_name"]))
        expected_rel = (out_root / name).relative_to(args.data_root).as_posix()
        expected = index_row(source, decision, expected_rel, digest)
        if row != expected:
            diff = {k: (row.get(k), expected.get(k)) for k in set(row) | set(expected) if row.get(k) != expected.get(k)}
            raise SystemExit(f"index row mismatch for {name}: {diff}")
        path = args.data_root / row["sample_path"]
        actual = path.read_bytes() if path.is_file() else None
        if actual != kept:
            raise SystemExit(f"sample differs from fresh decode: {path}")
        lo, hi = independent_profile(actual, row)
        if f32(lo) != row["minimum"] or f32(hi) != row["maximum"]:
            raise SystemExit(f"min/max mismatch for {name}")
        if digest in hashes:
            raise SystemExit(f"duplicate sample payload {name}")
        hashes.add(digest)
        seen.add(path.resolve())

    fresh = process(args, compare)
    if cursor != len(rows):
        raise SystemExit("index has extra rows")
    on_disk = {p.resolve() for p in out_root.glob("*.bin")}
    if on_disk != seen:
        raise SystemExit("sample directory has missing or stale files")
    if fresh != stored:
        raise SystemExit("ingest stats differ from a fresh decode")
    check_pins(fresh)
    if fresh["median_sample_values"] < 1_000 or fresh["total_size_bytes"] > HARD_CAP_BYTES:
        raise SystemExit("output violates the repository floors/cap")
    if len({r["subject_id"] for r in rows}) < 2:
        raise SystemExit("samples come from fewer than two donors")
    print(
        f"verified samples={fresh['sample_count']} values={fresh['total_values']} bytes={fresh['total_size_bytes']} "
        f"donors={len({r['subject_id'] for r in rows})} range={fresh['minimum']}..{fresh['maximum']} "
        f"aggregate_sha256={fresh['aggregate_sha256']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("select")
    p.add_argument("--assets-yaml", type=Path, required=True)
    p.add_argument("--sources", type=Path, required=True)
    p = sub.add_parser("check-sources")
    p.add_argument("--assets-yaml", type=Path, required=True)
    p.add_argument("--sources", type=Path, required=True)
    p = sub.add_parser("check-dandiset")
    p.add_argument("--dandiset-yaml", type=Path, required=True)
    p = sub.add_parser("check-file")
    p.add_argument("--file", type=Path, required=True)
    p.add_argument("--size", type=int, required=True)
    p.add_argument("--sha256", required=True)
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--sources", type=Path, required=True)
        p.add_argument("--download-dir", type=Path, required=True)
        p.add_argument("--samples-dir", type=Path, required=True)
        p.add_argument("--index", type=Path, required=True)
        p.add_argument("--stats", type=Path, required=True)
        p.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    {
        "select": command_select,
        "check-sources": command_check_sources,
        "check-dandiset": command_check_dandiset,
        "check-file": command_check_file,
        "build": command_build,
        "verify": command_verify,
    }[args.command](args)


if __name__ == "__main__":
    try:
        main()
    except H5.H5Error as exc:
        raise SystemExit(f"{DATASET_ID}: HDF5 error: {exc}") from exc
