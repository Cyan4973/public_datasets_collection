#!/usr/bin/env python3
"""MACE-MP foundation checkpoints -> native float64 parameter-tensor samples.

Commands:
  resources        print "tag url bytes relative_local_path" for download.sh
  validate-file    validate one downloaded checkpoint (download.sh gate)
  validate-docs    validate the pinned README/LICENSE license evidence
  build            emit samples, index and ingest stats
  verify           independently re-derive and check the emitted output

Pure standard library; torch/mace/e3nn are never imported (see
torch_zip_pickle.py for the inert unpickler).
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import operator
import re
import shutil
import statistics
import sys
import tomllib
import zipfile
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import torch_zip_pickle as tzp  # noqa: E402

DATASET_ID = "mace_mp_foundation_model_weights_f64"
RELEASE_BASE = "https://github.com/ACEsuit/mace-foundations/releases/download"
REPO_REVISION = "16a9f178706ce053f3ca8531efbab00a305d0854"
DOCS = {
    "README.md": (
        f"https://raw.githubusercontent.com/ACEsuit/mace-foundations/{REPO_REVISION}/README.md",
        9392,
        "3981e18e5b2d83bd6223ffc0724a261c638a9a0c812eddad91645821c91a3a12",
    ),
    "LICENSE": (
        f"https://raw.githubusercontent.com/ACEsuit/mace-foundations/{REPO_REVISION}/LICENSE",
        1064,
        "31ea0ccf7bc19797081bff51c7eff3a3927c8cb6c1d7a726dec3d157b436da1c",
    ),
}
MIN_VALUES = 1_000

# One row per MIT-licensed checkpoint linked from the pinned README model table.
# sha256: full-file digest. GitHub publishes none for these assets; 0b2/0b3/
# MPA-0 values are the Hugging Face LFS oids of byte-identical mirrors (matched
# on download), 0a/0b values were recorded from the first verified download
# (size + central directory + data.pkl + member CRCs pinned). cd_tail_sha256 is the
# sha256 of everything from the central-directory offset to EOF, i.e. it pins
# every member name, size, offset and CRC32.
CHECKPOINTS = [
    {
        "tag": "mace_mp_0a_small", "generation": "MACE-MP-0a", "size_label": "small",
        "release": "mace_mp_0", "asset": "2023-12-10-mace-128-L0_energy_epoch-249.model",
        "bytes": 32581838, "sha256": "2ddb079cee0e131eaaf6912ba581b394551ead283e95c99cfe78c605d10b5736",
        "members": 71, "prefix": "05-128-L0_run-1/", "cd_offset": 32576850,
        "cd_tail_sha256": "2729d2018e47935b3463aa68620ba22084ca59749f8abf937ef127fb3a31842e",
        "pkl_bytes": 188755, "pkl_sha256": "c1e07350aca4bf35adb0d8692ef6930408eb392302e0b24c142be53cea6f16cf",
        "parameters": 26, "buffers": 43, "selected": 22, "values": 3846272,
    },
    {
        "tag": "mace_mp_0a_medium", "generation": "MACE-MP-0a", "size_label": "medium",
        "release": "mace_mp_0", "asset": "2023-12-03-mace-128-L1_epoch-199.model",
        "bytes": 44422970, "sha256": "01bfe22100139f424713cf921144e5509cbe353d67aa9fa1be9c6e1e0ed35845",
        "members": 77, "prefix": "01-128-channels_run-1/", "cd_offset": 44417106,
        "cd_tail_sha256": "7c227bf365625a317f6618b5eb03ebf9c06b4d4a0730409127203786c0560cb6",
        "pkl_bytes": 216041, "pkl_sha256": "db179f2265a065433134cff4595202bdd07cf6877fecfe7367b9ebaa5147795e",
        "parameters": 29, "buffers": 46, "selected": 25, "values": 4687232,
    },
    {
        "tag": "mace_mp_0a_large", "generation": "MACE-MP-0a", "size_label": "large",
        "release": "mace_mp_0", "asset": "2024-01-07-mace-128-L2_epoch-199.model",
        "bytes": 63509066, "sha256": "514bd2f1938653c37929f7c275a489378f03a7e3ffb27aa2ae0ddce8d0c859c8",
        "members": 83, "prefix": "04-128-L2_run-1/", "cd_offset": 63503250,
        "cd_tail_sha256": "15ae7e7fc86eec3cbd08b38e3fb4af3938ce9bd17ba50ed54aaef18d36a2d27f",
        "pkl_bytes": 241042, "pkl_sha256": "e0b105dd58a715ff3516be452a76728ed492182068beb603d965163811760847",
        "parameters": 32, "buffers": 49, "selected": 28, "values": 5723648,
    },
    {
        "tag": "mace_mp_0b_small", "generation": "MACE-MP-0b", "size_label": "small",
        "release": "mace_mp_0b", "asset": "mace_agnesi_small.model",
        "bytes": 67603120, "sha256": "7e3a0abcaf41e03a80e69f778e1b11b29de1cca704783dc25917a736392f8cf0",
        "members": 83, "prefix": "MACE_agnesi_small/", "cd_offset": 67597138,
        "cd_tail_sha256": "f1df341e4ab6c6d44089e850e5f14e36e189ed80f2bb70f30db67237845c4cc0",
        "pkl_bytes": 194034, "pkl_sha256": "22c7c5335ad7da52d4ecc992547f070de7c70b59850d121e09fa47484bea702a",
        "parameters": 26, "buffers": 55, "selected": 22, "values": 8220800,
    },
    {
        "tag": "mace_mp_0b_medium", "generation": "MACE-MP-0b", "size_label": "medium",
        "release": "mace_mp_0b", "asset": "mace_agnesi_medium.model",
        "bytes": 79447096, "sha256": "ab8baff639a8f295f3eccad3d3ccf574efb6fb63220bd52cd88664211569e521",
        "members": 89, "prefix": "mace_agnesi_full_medium_128_cpu/", "cd_offset": 79439442,
        "cd_tail_sha256": "355bff30b92ab2ec8c93dc8c17159090817b55b452f19d9c76f1e07e5fad58b5",
        "pkl_bytes": 226081, "pkl_sha256": "19e1c2a61f636fb6afb80fb5889402eea4554f38d1a7deeba01db522168f553f",
        "parameters": 29, "buffers": 58, "selected": 25, "values": 9061760,
    },
    {
        "tag": "mace_mp_0b2_small", "generation": "MACE-MP-0b2", "size_label": "small",
        "release": "mace_mp_0b2", "asset": "mace-small-density-agnesi-stress.model",
        "bytes": 67622684, "sha256": "d5773bf9440e96d6eb8c598f84bd0e6369fcfa432f626a87f890e07da3c651c9",
        "members": 87, "prefix": "mace-small-density-agnesi-stress/", "cd_offset": 67615096,
        "cd_tail_sha256": "1fa03afab3eab47e603e04fd98c0e831e93f192c38eebc6d4aed0d2b67ed49c4",
        "pkl_bytes": 212463, "pkl_sha256": "416c38ac0f52d9879360082e04fbb30aaac24bddfecb91ba62e1f5c98ac66226",
        "parameters": 28, "buffers": 55, "selected": 22, "values": 8220800,
    },
    {
        "tag": "mace_mp_0b2_medium", "generation": "MACE-MP-0b2", "size_label": "medium",
        "release": "mace_mp_0b2", "asset": "mace-medium-density-agnesi-stress.model",
        "bytes": 79462798, "sha256": "a90be07c8aa6623c390fcc4653d3e319c4a356f8b4a53d323f96b2012d375caf",
        "members": 93, "prefix": "mace-medium-density-agnesi-stress-test/", "cd_offset": 79454136,
        "cd_tail_sha256": "a282a8814f6eb9dbdc04eae103021c1d6fd9083062a98619b29ebbc8128e305c",
        "pkl_bytes": 239913, "pkl_sha256": "396f5ad531fd64a56a8261c1d83785d041f1337e383793b007a80385b15c596c",
        "parameters": 31, "buffers": 58, "selected": 25, "values": 9061760,
    },
    {
        "tag": "mace_mp_0b2_large", "generation": "MACE-MP-0b2", "size_label": "large",
        "release": "mace_mp_0b2", "asset": "mace-large-density-agnesi-stress.model",
        "bytes": 98544548, "sha256": "348390e758e1c90011c7675e864850f8e9c5b3e7c217f79a2b4bad1baaa657ad",
        "members": 99, "prefix": "mace-large-density-agnesi-stress/", "cd_offset": 98535928,
        "cd_tail_sha256": "56de598fe51c1217631d5038134427064554119cbe542db5a431781b0f5aecce",
        "pkl_bytes": 264343, "pkl_sha256": "a112dee63c86936c9301cf5539a7137aba7a02a4e5263f1f97c7c5856544d979",
        "parameters": 34, "buffers": 61, "selected": 28, "values": 10098176,
    },
    {
        "tag": "mace_mp_0b3_medium", "generation": "MACE-MP-0b3", "size_label": "medium",
        "release": "mace_mp_0b3", "asset": "mace-mp-0b3-medium.model",
        "bytes": 79472952, "sha256": "2f2be696351ac9e94fbe01cdfb6f017679acdbd2db7645209ef55fec9826b012",
        "members": 93, "prefix": "mace-medium-ema-99999_99/", "cd_offset": 79465592,
        "cd_tail_sha256": "a40238c0857c01827ba16ed5c939cf0e33b2356f58699e6fe3c69cb4b00eef51",
        "pkl_bytes": 249380, "pkl_sha256": "72a007807b695995b31f85f64a7da5180680e75943476e877eab2d3d5473701c",
        "parameters": 31, "buffers": 58, "selected": 25, "values": 9061760,
    },
    {
        "tag": "mace_mpa_0_medium", "generation": "MACE-MPA-0", "size_label": "medium",
        "release": "mace_mpa_0", "asset": "mace-mpa-0-medium.model",
        "bytes": 79462305, "sha256": "75428afe3a1d7d8062e19bcaabd5c433623cabf308242ec9fb493e38604fb638",
        "members": 93, "prefix": "mace-alex-main-branch/", "cd_offset": 79455224,
        "cd_tail_sha256": "63c78e84f9de65bcb847d6ba68f986f38c1f1cfe7d38c1ee44766e76f8bf06a1",
        "pkl_bytes": 239852, "pkl_sha256": "3a61fa049c1882bb01dade58aff6ba66ac8ba445e297055829dc86a6ce21888e",
        "parameters": 31, "buffers": 58, "selected": 25, "values": 9061760,
    },
]

SERIES_PATTERNS = [
    (
        "mace_equivariant_linear_weight_f64",
        re.compile(
            r"^(node_embedding\.linear|interactions\.\d+\.(linear_up|linear|skip_tp)"
            r"|products\.\d+\.linear|readouts\.\d+\.linear(_\d+)?)\.weight$"
        ),
    ),
    ("mace_radial_mlp_weight_f64", re.compile(r"^interactions\.\d+\.conv_tp_weights\.layer\d+\.weight$")),
    (
        "mace_symmetric_contraction_weight_f64",
        re.compile(r"^products\.\d+\.symmetric_contractions\.contractions\.\d+\.(weights_max|weights\.\d+)$"),
    ),
]
EXPECTED_SERIES = {
    # series_id: (samples, values, bytes, tensor rank)
    "mace_equivariant_linear_weight_f64": (100, 63_098_112, 504_784_896, 1),
    "mace_radial_mlp_weight_f64": (60, 1_277_952, 10_223_616, 2),
    "mace_symmetric_contraction_weight_f64": (87, 12_667_904, 101_343_232, 3),
}
EXPECTED_SAMPLES = 247
EXPECTED_VALUES = 77_043_968
EXPECTED_BYTES = 616_351_744

# Cross-checkpoint near-duplicate screen: same-named, same-shape tensors are
# compared on up to NEAR_DUP_POSITIONS evenly spaced positions. A position
# "matches" when the values are equal or within 1e-6 relative. A later
# checkpoint's tensor is excluded as a copy when >= NEAR_DUP_EXCLUDE of
# positions match an earlier kept tensor; the pinned exclusion list is checked.
NEAR_DUP_POSITIONS = 8192
NEAR_DUP_REL_TOL = 1e-6
NEAR_DUP_EXCLUDE = 0.5
EXPECTED_NEAR_DUP_EXCLUSIONS: list[str] = []
# Full-tensor exact equality with an earlier checkpoint's same-named tensor:
# the neon (Z=10, z_table index 9) node_embedding row and skip_tp block, which
# receive no gradient from MPtrj and keep the same-seed initialization, plus
# part of the argon (Z=18) skip_tp block in the 0b family. 0.27% of values.
EXPECTED_EXACT_OVERLAP_VALUES = 208_965

SUBNORMAL_LIMIT = 2.2250738585072014e-308
DISTINCT_PREFIX = 200_000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def local_rel(ck: dict) -> str:
    return f"downloads/{DATASET_ID}/{ck['release']}/{ck['asset']}"


def checkpoint_by_tag(tag: str) -> dict:
    for ck in CHECKPOINTS:
        if ck["tag"] == tag:
            return ck
    raise SystemExit(f"unknown checkpoint tag {tag}")


def series_for(name: str) -> str:
    hits = [sid for sid, pattern in SERIES_PATTERNS if pattern.match(name)]
    if len(hits) != 1:
        raise ValueError(f"selected parameter {name!r} matches {len(hits)} series patterns")
    return hits[0]


def sample_filename(ck: dict, name: str) -> str:
    return f"{ck['tag']}__{re.sub(r'[^A-Za-z0-9]+', '_', name)}_f64le.bin"


# --- validation of downloaded resources --------------------------------------

def validate_docs(download_dir: Path) -> None:
    for name, (_, size, sha) in DOCS.items():
        path = download_dir / name
        if not path.is_file() or path.stat().st_size != size or sha256_file(path) != sha:
            raise ValueError(f"pinned {name} missing or changed")
    readme = (download_dir / "README.md").read_text(encoding="utf-8")
    rows = {}
    for line in readme.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and cells[0].startswith("MACE-"):
            rows[cells[0]] = cells
    for generation in ("MACE-MP-0a", "MACE-MP-0b", "MACE-MP-0b2", "MACE-MP-0b3", "MACE-MPA-0"):
        cells = rows.get(generation)
        if cells is None or cells[-1] != "MIT":
            raise ValueError(f"README license cell for {generation} is not MIT: {cells}")
        links = cells[5] if len(cells) > 5 else ""
        for ck in CHECKPOINTS:
            if ck["generation"] != generation:
                continue
            if f"releases/download/{ck['release']}/{ck['asset']}" not in links and f"releases/tag/{ck['release']})" not in links:
                raise ValueError(f"README row {generation} does not link {ck['release']}/{ck['asset']}")
    license_text = (download_dir / "LICENSE").read_text(encoding="utf-8")
    if not license_text.startswith("MIT License") or "Permission is hereby granted, free of charge" not in license_text:
        raise ValueError("repository LICENSE is no longer MIT")


def validate_checkpoint_file(path: Path, ck: dict, *, full_sha: bool = True) -> dict:
    """Size, optional full sha256, central-directory pin, data.pkl pin, member CRCs."""
    if not path.is_file() or path.stat().st_size != ck["bytes"]:
        raise ValueError(f"{ck['tag']}: missing or wrong size")
    observed_sha = sha256_file(path) if full_sha else None
    if full_sha and ck["sha256"] is not None and observed_sha != ck["sha256"]:
        raise ValueError(f"{ck['tag']}: sha256 mismatch {observed_sha}")
    with path.open("rb") as handle:
        directory = tzp.read_central_directory(handle, ck["bytes"])
        if directory["cd_offset"] != ck["cd_offset"] or directory["count"] != ck["members"]:
            raise ValueError(f"{ck['tag']}: central directory moved or member count changed")
        handle.seek(ck["cd_offset"])
        if hashlib.sha256(handle.read()).hexdigest() != ck["cd_tail_sha256"]:
            raise ValueError(f"{ck['tag']}: central directory content changed")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) != ck["members"]:
            raise ValueError(f"{ck['tag']}: member count changed")
        for info in infos:
            if info.compress_type != zipfile.ZIP_STORED or not info.filename.startswith(ck["prefix"]):
                raise ValueError(f"{ck['tag']}: unexpected member {info.filename}")
        bad = archive.testzip()
        if bad is not None:
            raise ValueError(f"{ck['tag']}: CRC failure in {bad}")
        pkl = archive.read(ck["prefix"] + "data.pkl")
    if len(pkl) != ck["pkl_bytes"] or hashlib.sha256(pkl).hexdigest() != ck["pkl_sha256"]:
        raise ValueError(f"{ck['tag']}: data.pkl changed")
    return {"tag": ck["tag"], "bytes": ck["bytes"], "sha256": observed_sha, "members": len(infos)}


# --- statistics --------------------------------------------------------------

def tensor_stats(payload: bytes) -> dict:
    values = array("d")
    values.frombytes(payload)
    if sys.byteorder != "little":
        values.byteswap()
    n = len(values)
    if not all(map(math.isfinite, values)):
        raise ValueError("non-finite value in tensor")
    minimum = min(values)
    maximum = max(values)
    zeros = values.count(0.0)
    tiny = sum(1 for v in values if -SUBNORMAL_LIMIT < v < SUBNORMAL_LIMIT)
    narrowed = array("d", array("f", values))
    f32_exact = sum(map(operator.eq, values, narrowed))
    distinct = len(set(values[:DISTINCT_PREFIX]))
    return {
        "minimum": minimum,
        "maximum": maximum,
        "zero_count": zeros,
        "subnormal_count": tiny - zeros,
        "f32_exact_count": f32_exact,
        "distinct_in_prefix": distinct,
        "value_count": n,
    }


def check_not_degenerate(stats: dict, label: str) -> None:
    if stats["minimum"] == stats["maximum"]:
        raise ValueError(f"constant tensor {label}")
    if stats["distinct_in_prefix"] < min(32, stats["value_count"]):
        raise ValueError(f"degenerate tensor {label}: {stats['distinct_in_prefix']} distinct values")
    if stats["zero_count"] * 2 > stats["value_count"]:
        raise ValueError(f"degenerate tensor {label}: majority zeros")


def probe_positions(numel: int) -> range:
    step = max(1, -(-numel // NEAR_DUP_POSITIONS))
    return range(0, numel, step)


def probe_values(payload: bytes) -> list[float]:
    values = array("d")
    values.frombytes(payload)
    if sys.byteorder != "little":
        values.byteswap()
    return [values[i] for i in probe_positions(len(values))]


def match_fraction(a: list[float], b: list[float]) -> float:
    hits = 0
    for x, y in zip(a, b):
        if x == y or abs(x - y) <= NEAR_DUP_REL_TOL * max(abs(x), abs(y)):
            hits += 1
    return hits / len(a)


def near_duplicate_screen(records: list[dict]) -> tuple[list[str], list[dict]]:
    """records: dicts with key, ck_index, name, shape, probe. Returns (excluded keys, pair stats)."""
    excluded: list[str] = []
    pairs: list[dict] = []
    by_name: dict[tuple, list[dict]] = {}
    for record in sorted(records, key=lambda r: r["ck_index"]):
        group = (record["name"], tuple(record["shape"]))
        kept = by_name.setdefault(group, [])
        worst = 0.0
        for earlier in kept:
            fraction = match_fraction(earlier["probe"], record["probe"])
            pairs.append({"a": earlier["key"], "b": record["key"], "match_fraction": fraction})
            worst = max(worst, fraction)
        if worst >= NEAR_DUP_EXCLUDE:
            excluded.append(record["key"])
        else:
            kept.append(record)
    return excluded, pairs


# --- decoding ----------------------------------------------------------------

def decode_checkpoint(ck: dict, pkl: bytes) -> tuple[dict, list[tuple[str, tzp.TensorRef]]]:
    tree = tzp.load_module_tree(pkl)
    if tree["root_class"] != "mace.modules.models.ScaleShiftMACE":
        raise ValueError(f"{ck['tag']}: unexpected root {tree['root_class']}")
    if len(tree["parameters"]) != ck["parameters"] or len(tree["buffers"]) != ck["buffers"]:
        raise ValueError(f"{ck['tag']}: parameter/buffer inventory changed")
    selected = []
    for name, tensor in tree["parameters"]:
        if tensor.storage.type_name != "DoubleStorage":
            raise ValueError(f"{ck['tag']}: parameter {name} is {tensor.storage.type_name}, not float64")
        if tensor.numel < MIN_VALUES:
            continue
        if not tensor.is_c_contiguous():
            raise ValueError(f"{ck['tag']}: non-contiguous parameter {name}")
        start, end = tensor.byte_range()
        if end > tensor.storage.numel * tensor.storage.itemsize:
            raise ValueError(f"{ck['tag']}: parameter {name} overruns its storage")
        selected.append((name, tensor))
    if len(selected) != ck["selected"] or sum(t.numel for _, t in selected) != ck["values"]:
        raise ValueError(f"{ck['tag']}: selected parameter inventory changed")
    return tree, selected


def materialize(download_dir: Path, *, raw_reader: bool):
    """Decode every checkpoint; yield (row_without_stats, payload, probe) in order.

    raw_reader=False reads members with zipfile (CRC-checked); raw_reader=True
    slices bytes at the local-header data offsets with the independent parser.
    """
    data_root = download_dir.parent.parent
    for ck_index, ck in enumerate(CHECKPOINTS):
        path = data_root / local_rel(ck)
        if raw_reader:
            handle = path.open("rb")
            directory = tzp.read_central_directory(handle, path.stat().st_size)
            members = directory["members"]

            def read(member_name: str) -> bytes:
                return tzp.read_stored_member(handle, members[member_name])
        else:
            archive = zipfile.ZipFile(path)

            def read(member_name: str) -> bytes:
                return archive.read(member_name)
        try:
            pkl = read(ck["prefix"] + "data.pkl")
            if hashlib.sha256(pkl).hexdigest() != ck["pkl_sha256"]:
                raise ValueError(f"{ck['tag']}: data.pkl changed")
            byteorder_name = ck["prefix"] + "byteorder"
            names = set(members) if raw_reader else set(archive.namelist())
            if byteorder_name in names and read(byteorder_name) != b"little":
                raise ValueError(f"{ck['tag']}: checkpoint is not little-endian")
            _, selected = decode_checkpoint(ck, pkl)
            for name, tensor in selected:
                member_name = ck["prefix"] + "data/" + tensor.storage.key
                storage = read(member_name)
                if len(storage) != tensor.storage.numel * 8:
                    raise ValueError(f"{ck['tag']}: storage size mismatch for {name}")
                start, end = tensor.byte_range()
                payload = storage[start:end]
                series_id = series_for(name)
                filename = sample_filename(ck, name)
                row = {
                    "dataset_id": DATASET_ID,
                    "series_id": series_id,
                    "role": "primary",
                    "sample_path": f"samples/{DATASET_ID}/{series_id}/{filename}",
                    "numeric_kind": "float",
                    "bit_width": 64,
                    "endianness": "little",
                    "element_size_bytes": 8,
                    "sample_size_bytes": len(payload),
                    "value_count": tensor.numel,
                    "sample_shape": list(tensor.size),
                    "sample_rank": len(tensor.size),
                    "checkpoint": ck["tag"],
                    "model_generation": ck["generation"],
                    "model_size": ck["size_label"],
                    "parameter_name": name,
                    "source_sample": local_rel(ck),
                    "source_member": member_name,
                    "source_storage_type": "torch.DoubleStorage",
                    "source_storage_offset": tensor.offset,
                    "source_stride": list(tensor.stride),
                }
                yield ck_index, row, payload
        finally:
            if raw_reader:
                handle.close()
            else:
                archive.close()


def collect(download_dir: Path, *, raw_reader: bool):
    rows: list[dict] = []
    payload_hashes: dict[str, str] = {}
    records: list[dict] = []
    for ck_index, row, payload in materialize(download_dir, raw_reader=raw_reader):
        stats = tensor_stats(payload)
        check_not_degenerate(stats, f"{row['checkpoint']}:{row['parameter_name']}")
        row.update({k: stats[k] for k in ("minimum", "maximum", "zero_count", "subnormal_count", "f32_exact_count", "distinct_in_prefix")})
        row["sha256"] = hashlib.sha256(payload).hexdigest()
        rows.append(row)
        payload_hashes[row["sample_path"]] = row["sha256"]
        records.append({
            "key": f"{row['checkpoint']}:{row['parameter_name']}",
            "ck_index": ck_index,
            "name": row["parameter_name"],
            "shape": row["sample_shape"],
            "probe": probe_values(payload),
        })
    return rows, records


def summarize(rows: list[dict], records: list[dict]) -> tuple[list[dict], dict]:
    excluded, pairs = near_duplicate_screen(records)
    if excluded != EXPECTED_NEAR_DUP_EXCLUSIONS:
        raise ValueError(f"near-duplicate exclusions changed: {excluded}")
    excluded_set = set(excluded)
    rows = [r for r in rows if f"{r['checkpoint']}:{r['parameter_name']}" not in excluded_set]
    if len({r["sha256"] for r in rows}) != len(rows):
        raise ValueError("duplicate sample payloads")
    if len({r["sample_path"] for r in rows}) != len(rows):
        raise ValueError("sample filename collision")
    totals = (len(rows), sum(r["value_count"] for r in rows), sum(r["sample_size_bytes"] for r in rows))
    if totals != (EXPECTED_SAMPLES, EXPECTED_VALUES, EXPECTED_BYTES):
        raise ValueError(f"aggregate inventory changed: {totals}")
    series_stats = {}
    for sid, (count, values, size, rank) in EXPECTED_SERIES.items():
        srows = [r for r in rows if r["series_id"] == sid]
        actual = (len(srows), sum(r["value_count"] for r in srows), sum(r["sample_size_bytes"] for r in srows))
        if actual != (count, values, size) or any(r["sample_rank"] != rank for r in srows):
            raise ValueError(f"series inventory changed for {sid}: {actual}")
        counts = sorted(r["value_count"] for r in srows)
        spairs = [p for p in pairs if p["b"] in {f"{r['checkpoint']}:{r['parameter_name']}" for r in srows}]
        worst = max(spairs, key=lambda p: p["match_fraction"]) if spairs else None
        series_stats[sid] = {
            "samples": count,
            "primary_values": values,
            "primary_sample_bytes": size,
            "min_value_count": counts[0],
            "median_value_count": statistics.median(counts),
            "max_value_count": counts[-1],
            "minimum": min(r["minimum"] for r in srows),
            "maximum": max(r["maximum"] for r in srows),
            "zero_count": sum(r["zero_count"] for r in srows),
            "subnormal_count": sum(r["subnormal_count"] for r in srows),
            "f32_exact_count": sum(r["f32_exact_count"] for r in srows),
            "cross_checkpoint_pairs_compared": len(spairs),
            "max_cross_checkpoint_match_fraction": worst,
        }
    per_checkpoint = {
        ck["tag"]: {
            "generation": ck["generation"],
            "size": ck["size_label"],
            "source": local_rel(ck),
            "samples": sum(1 for r in rows if r["checkpoint"] == ck["tag"]),
            "values": sum(r["value_count"] for r in rows if r["checkpoint"] == ck["tag"]),
        }
        for ck in CHECKPOINTS
    }
    stats = {
        "dataset_id": DATASET_ID,
        "repo_revision": REPO_REVISION,
        "samples": totals[0],
        "primary_values": totals[1],
        "primary_sample_bytes": totals[2],
        "f32_exact_count": sum(r["f32_exact_count"] for r in rows),
        "subnormal_count": sum(r["subnormal_count"] for r in rows),
        "zero_count": sum(r["zero_count"] for r in rows),
        "near_duplicate_rule": {
            "positions_per_pair": NEAR_DUP_POSITIONS,
            "relative_tolerance": NEAR_DUP_REL_TOL,
            "exclude_at_match_fraction": NEAR_DUP_EXCLUDE,
            "pairs_compared": len(pairs),
            "excluded": excluded,
        },
        "series": series_stats,
        "checkpoints": per_checkpoint,
    }
    return rows, stats


# --- commands ----------------------------------------------------------------

def cmd_resources(args) -> None:
    """kind tag url bytes sha256-or-dash relative_local_path"""
    for name, (url, size, sha) in DOCS.items():
        print(f"doc doc_{name.replace('.', '_').lower()} {url} {size} {sha} downloads/{DATASET_ID}/{name}")
    for ck in CHECKPOINTS:
        print(f"model {ck['tag']} {RELEASE_BASE}/{ck['release']}/{ck['asset']} {ck['bytes']} {ck['sha256'] or '-'} {local_rel(ck)}")


def cmd_validate_file(args) -> None:
    ck = checkpoint_by_tag(args.tag)
    info = validate_checkpoint_file(Path(args.file), ck)
    print(f"validated {info['tag']} bytes={info['bytes']} members={info['members']} sha256={info['sha256']}"
          f" pinned_sha256={'yes' if ck['sha256'] else 'no (central directory + data.pkl + member CRCs pinned)'}")


def cmd_validate_docs(args) -> None:
    validate_docs(Path(args.download_dir))
    print("validated README MIT rows for MACE-MP-0a/0b/0b2/0b3/MPA-0 and MIT LICENSE")


def exact_overlap(rows: list[dict], data_root: Path) -> dict:
    """Full-tensor exact equality against earlier same-named, same-shape tensors.

    For every tensor, counts positions whose value equals the value at the same
    position in any earlier checkpoint's tensor of the same name and shape
    (e.g. untrained element blocks left at a shared-seed initialization).
    """
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        groups.setdefault((row["parameter_name"], tuple(row["sample_shape"])), []).append(row)
    per_tensor: dict[str, int] = {}
    by_series: dict[str, int] = {sid: 0 for sid in EXPECTED_SERIES}
    for group in groups.values():
        arrays = []
        for row in group:
            values = array("d")
            values.frombytes((data_root / row["sample_path"]).read_bytes())
            arrays.append(values)
        for j in range(1, len(group)):
            mask = None
            for i in range(j):
                equal = list(map(operator.eq, arrays[i], arrays[j]))
                if any(equal):
                    mask = equal if mask is None else list(map(operator.or_, mask, equal))
            count = sum(mask) if mask is not None else 0
            if count:
                key = f"{group[j]['checkpoint']}:{group[j]['parameter_name']}"
                per_tensor[key] = count
                by_series[group[j]["series_id"]] += count
    total = sum(per_tensor.values())
    if total != EXPECTED_EXACT_OVERLAP_VALUES:
        raise ValueError(f"exact cross-checkpoint overlap changed: {total}")
    sizes = {f"{r['checkpoint']}:{r['parameter_name']}": r["value_count"] for r in rows}
    fractions = {k: v / sizes[k] for k, v in per_tensor.items()}
    worst = max(fractions, key=fractions.get) if fractions else None
    if worst is not None and fractions[worst] >= NEAR_DUP_EXCLUDE:
        raise ValueError(f"tensor {worst} is mostly an exact copy of an earlier checkpoint")
    return {
        "values": total,
        "fraction_of_primary_values": total / sum(sizes.values()),
        "by_series": by_series,
        "tensors_with_overlap": len(per_tensor),
        "max_tensor": worst,
        "max_tensor_fraction": fractions.get(worst, 0.0) if worst else 0.0,
        "per_tensor": dict(sorted(per_tensor.items())),
    }


def cmd_build(args) -> None:
    download_dir = Path(args.download_dir)
    validate_docs(download_dir)
    data_root = download_dir.parent.parent
    for ck in CHECKPOINTS:
        validate_checkpoint_file(data_root / local_rel(ck), ck)
    samples_dir = Path(args.samples_dir)
    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    rows: list[dict] = []
    records: list[dict] = []
    for ck_index, row, payload in materialize(download_dir, raw_reader=False):
        stats = tensor_stats(payload)
        check_not_degenerate(stats, f"{row['checkpoint']}:{row['parameter_name']}")
        row.update({k: stats[k] for k in ("minimum", "maximum", "zero_count", "subnormal_count", "f32_exact_count", "distinct_in_prefix")})
        row["sha256"] = hashlib.sha256(payload).hexdigest()
        out = data_root / row["sample_path"]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(payload)
        rows.append(row)
        records.append({
            "key": f"{row['checkpoint']}:{row['parameter_name']}",
            "ck_index": ck_index,
            "name": row["parameter_name"],
            "shape": row["sample_shape"],
            "probe": probe_values(payload),
        })
    written = {r["sample_path"] for r in rows}
    rows, stats = summarize(rows, records)
    for stale in written - {r["sample_path"] for r in rows}:
        (data_root / stale).unlink()
    stats["exact_overlap"] = exact_overlap(rows, data_root)
    index = Path(args.index)
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    stats_path = Path(args.stats)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"built samples={stats['samples']} primary_values={stats['primary_values']} "
          f"primary_bytes={stats['primary_sample_bytes']} f32_exact={stats['f32_exact_count']} "
          f"subnormal={stats['subnormal_count']} zeros={stats['zero_count']}")
    for sid, s in stats["series"].items():
        print(f"  {sid}: samples={s['samples']} values={s['primary_values']} median={s['median_value_count']} "
              f"range=[{s['minimum']!r}, {s['maximum']!r}] max_pair={s['max_cross_checkpoint_match_fraction']}")
    overlap = stats["exact_overlap"]
    print(f"  exact cross-checkpoint overlap: values={overlap['values']} "
          f"fraction={overlap['fraction_of_primary_values']:.5f} tensors={overlap['tensors_with_overlap']} "
          f"max={overlap['max_tensor']} ({overlap['max_tensor_fraction']:.4f})")


def cmd_verify(args) -> None:
    download_dir = Path(args.download_dir)
    data_root = download_dir.parent.parent
    validate_docs(download_dir)
    for ck in CHECKPOINTS:
        path = data_root / local_rel(ck)
        if not path.is_file() or path.stat().st_size != ck["bytes"]:
            raise ValueError(f"{ck['tag']}: source missing or wrong size")
        if ck["sha256"] is not None and sha256_file(path) != ck["sha256"]:
            raise ValueError(f"{ck['tag']}: source sha256 changed")
    # Independent decode: raw local-header slicing, statistics recomputed from source bytes.
    expected_rows, records = collect(download_dir, raw_reader=True)
    expected_rows, expected_stats = summarize(expected_rows, records)
    actual_rows = [json.loads(line) for line in Path(args.index).read_text(encoding="utf-8").splitlines() if line.strip()]
    if actual_rows != json.loads(json.dumps(expected_rows)):
        raise ValueError("sample index differs from the independent raw-offset decode")
    # Emitted files: exact inventory, sizes, hashes and statistics recomputed from disk.
    samples_dir = Path(args.samples_dir)
    expected_paths = {r["sample_path"] for r in actual_rows}
    actual_paths = {str(p.relative_to(data_root)) for p in samples_dir.rglob("*") if p.is_file()}
    if actual_paths != expected_paths:
        raise ValueError(f"sample file inventory mismatch: extra={sorted(actual_paths - expected_paths)[:5]} "
                         f"missing={sorted(expected_paths - actual_paths)[:5]}")
    for row in actual_rows:
        payload = (data_root / row["sample_path"]).read_bytes()
        if len(payload) != row["sample_size_bytes"] or len(payload) != row["value_count"] * 8:
            raise ValueError(f"size mismatch {row['sample_path']}")
        if hashlib.sha256(payload).hexdigest() != row["sha256"]:
            raise ValueError(f"hash mismatch {row['sample_path']}")
        stats = tensor_stats(payload)
        check_not_degenerate(stats, row["sample_path"])
        for key in ("minimum", "maximum", "zero_count", "subnormal_count", "f32_exact_count", "distinct_in_prefix"):
            if stats[key] != row[key]:
                raise ValueError(f"{key} mismatch {row['sample_path']}")
    # Emitted files are now hash-identical to the raw-offset source slices.
    expected_stats["exact_overlap"] = exact_overlap(actual_rows, data_root)
    actual_stats = json.loads(Path(args.stats).read_text(encoding="utf-8"))
    if actual_stats != json.loads(json.dumps(expected_stats)):
        raise ValueError("ingest stats differ from the independent decode")
    # Manifest claims must match realized output.
    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    declared = {s["id"]: s for s in manifest["series"]}
    if set(declared) != set(EXPECTED_SERIES):
        raise ValueError("manifest series set differs from emitted series")
    for sid, s in declared.items():
        srows = [r for r in actual_rows if r["series_id"] == sid]
        if s["sample_count"] != len(srows) or s["total_size_bytes"] != sum(r["sample_size_bytes"] for r in srows):
            raise ValueError(f"manifest totals differ for {sid}")
        if (s["numeric_kind"], s["bit_width"], s["endianness"]) != ("float", 64, "little"):
            raise ValueError(f"manifest type differs for {sid}")
    print(f"verified samples={len(actual_rows)} primary_values={expected_stats['primary_values']} "
          f"primary_bytes={expected_stats['primary_sample_bytes']} f32_exact={expected_stats['f32_exact_count']} "
          f"near_dup_pairs={expected_stats['near_duplicate_rule']['pairs_compared']}")


def main() -> None:
    root = argparse.ArgumentParser()
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("resources").set_defaults(func=cmd_resources)
    p = sub.add_parser("validate-file")
    p.add_argument("--tag", required=True)
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_validate_file)
    p = sub.add_parser("validate-docs")
    p.add_argument("--download-dir", required=True)
    p.set_defaults(func=cmd_validate_docs)
    for name, func in (("build", cmd_build), ("verify", cmd_verify)):
        p = sub.add_parser(name)
        p.add_argument("--download-dir", required=True)
        p.add_argument("--samples-dir", required=True)
        p.add_argument("--index", required=True)
        p.add_argument("--stats", required=True)
        if name == "verify":
            p.add_argument("--manifest", required=True)
        p.set_defaults(func=func)
    args = root.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
