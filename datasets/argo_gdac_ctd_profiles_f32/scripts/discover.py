#!/usr/bin/env python3
"""License-first bounded-header discovery for native-float32 Argo CTD files."""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import gzip
import hashlib
import html
import json
from pathlib import Path, PurePosixPath
import re
import struct
import subprocess
from urllib.parse import urljoin


CANDIDATE_ID = "argo_gdac_ctd_profiles_f32"
GDAC_ROOT = "https://data-argo.ifremer.fr/"
META_INDEX_URL = urljoin(GDAC_ROOT, "ar_index_global_meta.txt.gz")
POLICY_URLS = (
    "https://argo.ucsd.edu/data/acknowledging-argo/",
    "https://argo.ucsd.edu/data/argo-data-policy/",
    "https://argo.ucsd.edu/data/data-policy/",
)
USER_AGENT = "openzl-public-datasets-argo-ctd-preflight/1.0"
MAX_POLICY_BYTES = 4 * 1024 * 1024
MAX_INDEX_BYTES = 25 * 1024 * 1024
HEADER_BYTES = 1024 * 1024
MAX_PROBES = 80
MAX_PER_DAC = 10
MIN_SOURCE_BYTES = HEADER_BYTES + 1
MAX_SOURCE_BYTES = 250 * 1024 * 1024
MIN_PROFILES = 8
MIN_LEVELS = 50
NC_FLOAT = 5
TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 4, 6: 8}


def curl_bytes(url: str, maximum: int, byte_range: str | None = None) -> bytes:
    command = [
        "curl", "--fail", "--silent", "--show-error", "--location",
        "--retry", "3", "--retry-delay", "2", "--max-time", "300",
        "--max-filesize", str(maximum), "--user-agent", USER_AGENT,
    ]
    if byte_range:
        command.extend(("--range", byte_range))
    result = subprocess.run(command + [url], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode or len(result.stdout) > maximum:
        message = result.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"{url}: {message or 'fetch failed'}")
    return result.stdout


def content_length(url: str) -> int:
    result = subprocess.run(
        [
            "curl", "--fail", "--silent", "--show-error", "--location", "--head",
            "--retry", "3", "--retry-delay", "2", "--max-time", "180",
            "--user-agent", USER_AGENT, url,
        ],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        message = result.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"{url}: {message or 'HEAD failed'}")
    matches = re.findall(rb"(?im)^content-length:\s*(\d+)\s*$", result.stdout)
    if not matches:
        raise RuntimeError(f"{url}: HEAD lacks Content-Length")
    return int(matches[-1])


def policy_evidence() -> tuple[str, bytes, str]:
    failures = []
    for url in POLICY_URLS:
        try:
            raw = curl_bytes(url, MAX_POLICY_BYTES)
        except RuntimeError as error:
            failures.append(str(error))
            continue
        text = html.unescape(re.sub(r"<[^>]+>", " ", raw.decode("utf-8", "replace")))
        normalized = " ".join(text.split())
        lower = normalized.lower()
        phrases = (
            "freely available without restriction",
            "free and unrestricted access",
            "available without restriction",
        )
        phrase = next((item for item in phrases if item in lower), "")
        if phrase and "argo" in lower and ("acknowledg" in lower or "citation" in lower):
            position = lower.index(phrase)
            excerpt = normalized[max(0, position - 200):position + 500]
            return url, raw, excerpt
        failures.append(f"{url}: page lacks free-access plus attribution language")
    raise RuntimeError("official Argo policy validation failed: " + " | ".join(failures))


class HeaderReader:
    def __init__(self, data: bytes):
        self.data = data
        self.position = 0

    def take(self, size: int) -> bytes:
        end = self.position + size
        if end > len(self.data):
            raise ValueError("NetCDF header exceeds bounded prefix")
        value = self.data[self.position:end]
        self.position = end
        return value

    def u32(self) -> int:
        return struct.unpack(">I", self.take(4))[0]

    def u64(self) -> int:
        return struct.unpack(">Q", self.take(8))[0]

    def name(self) -> str:
        length = self.u32()
        raw = self.take(length)
        self.take((-length) % 4)
        return raw.decode("ascii", "strict")


def read_attributes(reader: HeaderReader) -> None:
    tag = reader.u32()
    count = reader.u32()
    if tag == 0 and count == 0:
        return
    if tag != 12:
        raise ValueError(f"unexpected NetCDF attribute tag {tag}")
    for _ in range(count):
        reader.name()
        value_type = reader.u32()
        element_count = reader.u32()
        size = TYPE_SIZES.get(value_type)
        if size is None:
            raise ValueError(f"unsupported NetCDF attribute type {value_type}")
        byte_count = size * element_count
        reader.take(byte_count)
        reader.take((-byte_count) % 4)


def parse_netcdf_header(raw: bytes) -> dict[str, object]:
    if raw[:4] not in {b"CDF\x01", b"CDF\x02"}:
        kind = "HDF5/NetCDF4" if raw[:8] == b"\x89HDF\r\n\x1a\n" else raw[:8].hex()
        raise ValueError(f"not classic NetCDF: {kind}")
    offset64 = raw[3] == 2
    reader = HeaderReader(raw)
    reader.take(4)
    num_records = reader.u32()
    dim_tag = reader.u32()
    dim_count = reader.u32()
    dimensions = []
    if dim_tag == 0 and dim_count == 0:
        pass
    elif dim_tag == 10:
        for _ in range(dim_count):
            name = reader.name()
            length = reader.u32()
            dimensions.append({"name": name, "declared_length": length})
    else:
        raise ValueError(f"unexpected NetCDF dimension tag {dim_tag}")
    read_attributes(reader)
    variable_tag = reader.u32()
    variable_count = reader.u32()
    variables = {}
    if variable_tag == 0 and variable_count == 0:
        return {"format": "CDF2" if offset64 else "CDF1", "num_records": num_records,
                "dimensions": dimensions, "variables": variables, "header_bytes": reader.position}
    if variable_tag != 11:
        raise ValueError(f"unexpected NetCDF variable tag {variable_tag}")
    for _ in range(variable_count):
        name = reader.name()
        rank = reader.u32()
        dim_ids = [reader.u32() for _ in range(rank)]
        if any(item >= len(dimensions) for item in dim_ids):
            raise ValueError(f"{name}: invalid dimension id")
        read_attributes(reader)
        value_type = reader.u32()
        vsize = reader.u32()
        begin = reader.u64() if offset64 else reader.u32()
        dim_names = [str(dimensions[item]["name"]) for item in dim_ids]
        shape = [
            num_records if int(dimensions[item]["declared_length"]) == 0 else int(dimensions[item]["declared_length"])
            for item in dim_ids
        ]
        variables[name] = {
            "type": value_type, "dim_names": dim_names, "shape": shape,
            "vsize": vsize, "begin": begin,
        }
    return {
        "format": "CDF2" if offset64 else "CDF1", "num_records": num_records,
        "dimensions": dimensions, "variables": variables, "header_bytes": reader.position,
    }


def meta_paths(raw: bytes) -> list[str]:
    text = gzip.decompress(raw).decode("utf-8", "replace")
    result = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        path = line.split(",", 1)[0].strip()
        if path.endswith("_meta.nc"):
            normalized = path if path.startswith("dac/") else f"dac/{path}"
            result.append(normalized)
    if not result:
        raise ValueError("official metadata index exposed no DAC meta paths")
    return sorted(set(result))


def profile_path(meta_path: str) -> tuple[str, str, str]:
    path = PurePosixPath(meta_path)
    if len(path.parts) < 4 or path.parts[0] != "dac":
        raise ValueError(f"unexpected metadata path {meta_path}")
    dac = path.parts[1]
    wmo = path.parent.name
    if path.name != f"{wmo}_meta.nc" or not wmo.isdigit():
        raise ValueError(f"unexpected metadata filename {meta_path}")
    profile = str(path.parent / f"{wmo}_prof.nc")
    return dac, wmo, profile


def select_probes(paths: list[str]) -> list[tuple[str, str, str]]:
    ranked = []
    for path in paths:
        try:
            dac, wmo, profile = profile_path(path)
        except ValueError:
            continue
        rank = hashlib.sha256(profile.encode("ascii")).hexdigest()
        ranked.append((rank, dac, wmo, profile))
    by_dac: defaultdict[str, int] = defaultdict(int)
    selected = []
    for _rank, dac, wmo, profile in sorted(ranked):
        if by_dac[dac] >= MAX_PER_DAC:
            continue
        selected.append((dac, wmo, profile))
        by_dac[dac] += 1
        if len(selected) >= MAX_PROBES:
            break
    return selected


def inspect_candidate(dac: str, wmo: str, path: str) -> dict[str, object]:
    url = urljoin(GDAC_ROOT, path)
    source_bytes = content_length(url)
    if not MIN_SOURCE_BYTES <= source_bytes <= MAX_SOURCE_BYTES:
        raise ValueError(f"source size outside bounds: {source_bytes}")
    raw = curl_bytes(url, HEADER_BYTES, f"0-{HEADER_BYTES - 1}")
    if len(raw) != HEADER_BYTES:
        raise ValueError(f"bounded header response length {len(raw)} != {HEADER_BYTES}")
    header = parse_netcdf_header(raw)
    variables = header["variables"]
    reports = {}
    for name in ("PRES", "TEMP", "PSAL"):
        variable = variables.get(name)
        if not isinstance(variable, dict):
            raise ValueError(f"missing core CTD variable {name}")
        if variable["type"] != NC_FLOAT:
            raise ValueError(f"{name} is not NC_FLOAT: type={variable['type']}")
        if variable["dim_names"] != ["N_PROF", "N_LEVELS"]:
            raise ValueError(f"{name} has unexpected dimensions {variable['dim_names']}")
        shape = variable["shape"]
        if len(shape) != 2 or shape[0] < MIN_PROFILES or shape[1] < MIN_LEVELS:
            raise ValueError(f"{name} shape below floor: {shape}")
        reports[name] = {
            "shape": shape, "value_count": shape[0] * shape[1],
            "numeric_bytes": shape[0] * shape[1] * 4,
            "begin": variable["begin"], "vsize": variable["vsize"],
        }
    shapes = {tuple(item["shape"]) for item in reports.values()}
    if len(shapes) != 1:
        raise ValueError(f"core CTD shapes disagree: {shapes}")
    shape = list(next(iter(shapes)))
    return {
        "dac": dac, "wmo": wmo, "path": path, "url": url,
        "source_bytes": source_bytes, "netcdf_format": header["format"],
        "header_bytes": header["header_bytes"], "profile_count": shape[0],
        "level_count": shape[1], "shape": shape,
        "values_per_variable": shape[0] * shape[1],
        "numeric_bytes_per_variable": shape[0] * shape[1] * 4,
        "primary_numeric_bytes": shape[0] * shape[1] * 4 * 3,
        "variables": reports,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    policy_url, policy_raw, policy_excerpt = policy_evidence()
    (args.output_dir / "argo_data_policy.html").write_bytes(policy_raw)
    index_raw = curl_bytes(META_INDEX_URL, MAX_INDEX_BYTES)
    (args.output_dir / "ar_index_global_meta.txt.gz").write_bytes(index_raw)
    paths = meta_paths(index_raw)
    probes = select_probes(paths)
    if not probes:
        raise SystemExit("metadata index produced no bounded probes")

    candidates = []
    failures = []
    for dac, wmo, path in probes:
        try:
            candidates.append(inspect_candidate(dac, wmo, path))
        except (RuntimeError, ValueError) as error:
            failures.append({"dac": dac, "wmo": wmo, "path": path, "reason": str(error)})
    (args.output_dir / "candidate_failures.json").write_text(
        json.dumps(failures, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output_dir / "float32_candidates.json").write_text(
        json.dumps(candidates, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    columns = (
        "dac", "wmo", "netcdf_format", "profile_count", "level_count",
        "values_per_variable", "numeric_bytes_per_variable", "primary_numeric_bytes",
        "source_bytes", "url",
    )
    with (args.output_dir / "float32_candidates.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(candidates)
    dacs = sorted({str(row["dac"]) for row in candidates})
    summary = {
        "candidate_id": CANDIDATE_ID, "policy_url": policy_url,
        "policy_excerpt": policy_excerpt, "meta_index_url": META_INDEX_URL,
        "indexed_float_count": len(paths), "probes": len(probes),
        "candidate_count": len(candidates), "failure_count": len(failures),
        "candidate_dacs": dacs,
        "candidate_source_bytes": sum(int(row["source_bytes"]) for row in candidates),
        "candidate_primary_numeric_bytes": sum(int(row["primary_numeric_bytes"]) for row in candidates),
        "profile_count": sum(int(row["profile_count"]) for row in candidates),
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if not candidates:
        raise SystemExit("bounded official-GDAC preflight found no native-float32 core CTD file")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, gzip.BadGzipFile) as error:
        raise SystemExit(str(error)) from error
