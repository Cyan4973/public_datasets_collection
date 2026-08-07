#!/usr/bin/env python3
"""Download, build, inspect, and verify pinned Svalbard MALA GPR profiles."""
from __future__ import annotations

from array import array
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import zipfile
import zlib


DATASET_ID = "zenodo_gpr_rd3_i16"
SERIES_ID = "svalbard_gpr_radargram_i16"
RECORD_ID = 6_856_164
RECORD_TITLE = "GPR snow depth survey over Svalbard Glaciers"
RECORD_API = f"https://zenodo.org/api/records/{RECORD_ID}"
USER_AGENT = "openzl-public-datasets-gpr-rd3/1.0"
SAMPLES_PER_TRACE = 1024
ARCHIVES = {
    "GPR_Longyearbreen_20180401.zip": (13_693_641, "6f90028a1ab79c92415be9fea8188430"),
    "GPR_Maritbreen_Philipbreen_20180327.zip": (25_126_662, "b9debb7a5ddcc2afa827229c8c23f55a"),
    "GPR_Slakbreen_20180330.zip": (43_518_498, "6269a1de328e03e53d650ccb6fc6806d"),
    "GPR_Holtedahlfonna_20180324.zip": (41_095_332, "b86e744409b5132b6045470dfcfda21c"),
}

# archive, stem, compressed bytes, payload bytes, CRC32, trace count,
# RAD SHA256, RD3 SHA256
PROFILES = (
    ("GPR_Longyearbreen_20180401.zip", "LONGYR_0001_A1", 5_054_150, 8_863_744, "228b71fb", 4328, "8d7bfc92a52958bb95584c74c66cd1bcc0258285c73bfad93d310e2d2d192126", "4561cce3beda61750010d2980b18b6458969c42b031f915aad5892ea164f1c45"),
    ("GPR_Longyearbreen_20180401.zip", "LONGYR_0002_A1", 8_607_081, 14_860_288, "d67e3112", 7256, "d95e3895f4113c2cde25e2823424f421187bcecbdc6728d4fcbb8a9a64a99009", "c3880e90176846d755fbe72e1d4549a342158581acd833ca6a51729c5e2a8291"),
    ("GPR_Maritbreen_Philipbreen_20180327.zip", "MAR_PHI_0002_A1", 25_078_741, 41_904_128, "94db4e29", 20461, "32cf10cc9c9a5d5c2c1755d1faeb2bd54e3e47ff42b20742e8e4f073ff393b91", "623b72cebcf746e557f3083b40c8a0ce8d81cb8e7eccfd91b8e7b900f40fcc5a"),
    ("GPR_Slakbreen_20180330.zip", "SLAK_0001_A1", 16_644_335, 28_948_480, "fa3759d0", 14135, "b898e9b8cc62343b828f4ec62917353bdd1147e48cbc8a16deb09747f5a30572", "d7a8483d0e9badfe26f726b0b29f454301ca135dc944bb5d587facba8c1a33ad"),
    ("GPR_Slakbreen_20180330.zip", "SLAK_0002_A1", 6_854_255, 11_622_400, "f181d11e", 5675, "57c1d09cd2ffbfd363a4c9edb39ebf217125078d3dc2296dbd26a9f8bcc6083b", "479e6c39786b51dcf0f02b73dcdc58c9320061f372dd81a21752eee5f6ef599e"),
    ("GPR_Slakbreen_20180330.zip", "SLAK_0003_A1", 2_364_445, 4_077_568, "3518bbd5", 1991, "84ace74ec3d24d8ae9b44c228ea3c97c6e38e1824bf0af0068208029b85eec32", "06d5a7b79f13198f966f37bd30ddea7d50322354700b8bb92aad201335231d6b"),
    ("GPR_Slakbreen_20180330.zip", "SLAK_0004_A1", 5_038_643, 8_775_680, "13386ed0", 4285, "61c68cbc93cbb9b1ba8acff9b3345884d596b1085bcab788993f02b0e127d52e", "827417af5b2dc6bd5bd2c1249302ad5ca7485a707c9e1942d14bcc7d000fc29d"),
    ("GPR_Slakbreen_20180330.zip", "SLAK_0005_A1", 2_077_142, 3_682_304, "2a618856", 1798, "bf4b90f75fb65990ca4cebdb909553016087b8af6647ff0c69f9632321b85f6d", "9028119f4cb0f28ffc7d1af5ac674c40a0c7aeb834786066086c3e83d2046d59"),
    ("GPR_Slakbreen_20180330.zip", "SLAK_0006_A1", 4_508_781, 8_026_112, "0fcdcd94", 3919, "9ec51d73808b8f304eacf753690a9e2f5663dc4e9881a28c95db8f648c47f8e9", "f96fb70c8321c252c20bf11c5696d1867a3b99a9d045e67b0b862f1a754e8c20"),
    ("GPR_Slakbreen_20180330.zip", "SLAK_0007_A1", 1_555_152, 2_779_136, "ac1238d8", 1357, "6608c147889e491406cdd27b35739c2e63e21ebc2c1fcb3a504debccccc820db", "692a10b96d0233d4aabc4d5fa47a32f91413508ba69c72c63678675e411edee2"),
    ("GPR_Slakbreen_20180330.zip", "SLAK_0008_A1", 4_374_982, 7_825_408, "5e5da658", 3821, "da205364a851dd6d13d6c5d32ff7b900bc56b76070ff4277e4962b8d623ea2e9", "5c9647dfcd77f04d235ec52a53b3b5773e26ce9e1e8844c9bef061d70c86fe68"),
    ("GPR_Holtedahlfonna_20180324.zip", "HDF_0001_A1", 41_028_445, 60_624_896, "606989ab", 29602, "0ce35d03cd6ebcf87e4da7e924fe4f69550e35ced52383bee10b50df453c8487", "9fb9a88139af7bb8c0688cf25f9d094ed006eb9a122bce63586862b5f835377f"),
)


def file_hash(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def curl(url: str, output: Path, maximum: int, timeout: int = 1800) -> None:
    command = [
        "curl", "--fail", "--silent", "--show-error", "--location",
        "--retry", "5", "--retry-delay", "2", "--max-time", str(timeout),
        "--max-filesize", str(maximum), "--user-agent", USER_AGENT,
        "--output", str(output), url,
    ]
    result = subprocess.run(command, check=False)
    if result.returncode:
        raise SystemExit(f"curl failed with exit status {result.returncode}: {url}")


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
    items = {str(item.get("key", "")): item for item in files if isinstance(item, dict)}
    for archive, (size, md5) in ARCHIVES.items():
        item = items.get(archive)
        if item is None or int(item.get("size", 0)) != size or item.get("checksum") != f"md5:{md5}":
            raise SystemExit(f"pinned archive identity changed: {archive}")
    return items


def parse_rad(raw: bytes) -> dict[str, str]:
    fields = {}
    for line in raw.decode("cp1252", "strict").replace("\x00", "").splitlines():
        match = re.match(r"^\s*([^:=]+?)\s*[:=]\s*(.*?)\s*$", line)
        if match:
            fields[re.sub(r"\s+", " ", match.group(1).strip()).upper()] = match.group(2).strip()
    return fields


def valid_extracted(download_dir: Path, profile: tuple[object, ...]) -> bool:
    _archive, stem, _compressed, size, _crc, traces, rad_sha, rd3_sha = profile
    rd3_path = download_dir / f"{stem}.rd3"
    rad_path = download_dir / f"{stem}.rad"
    if not rd3_path.is_file() or rd3_path.stat().st_size != size or file_hash(rd3_path) != rd3_sha:
        return False
    if not rad_path.is_file() or file_hash(rad_path) != rad_sha:
        return False
    fields = parse_rad(rad_path.read_bytes())
    return fields.get("SAMPLES") == "1024" and fields.get("LAST TRACE") == str(traces) and fields.get("SHORT FLAG") == "1"


def download(args: argparse.Namespace) -> None:
    args.download_dir.mkdir(parents=True, exist_ok=True)
    metadata_part = args.download_dir / f"record_{RECORD_ID}.json.part"
    curl(RECORD_API, metadata_part, 20_000_000, 180)
    record = json.loads(metadata_part.read_text(encoding="utf-8"))
    items = validate_record(record)
    os.replace(metadata_part, args.download_dir / f"record_{RECORD_ID}.json")

    for archive, (size, md5) in ARCHIVES.items():
        selected = [profile for profile in PROFILES if profile[0] == archive]
        if all(valid_extracted(args.download_dir, profile) for profile in selected):
            print(f"verified cached extracted profiles from {archive}")
            continue
        item = items[archive]
        links = item.get("links", {})
        url = str(links.get("self") or links.get("download") or "") if isinstance(links, dict) else ""
        if not url:
            raise SystemExit(f"missing URL for {archive}")
        archive_path = args.download_dir / archive
        if not archive_path.is_file() or archive_path.stat().st_size != size or file_hash(archive_path, "md5") != md5:
            part = archive_path.with_suffix(".zip.part")
            part.unlink(missing_ok=True)
            print(f"downloading {archive} ({size} bytes)")
            curl(url, part, size + 1)
            if part.stat().st_size != size or file_hash(part, "md5") != md5:
                raise SystemExit(f"downloaded archive identity mismatch: {archive}")
            os.replace(part, archive_path)
        with zipfile.ZipFile(archive_path) as source:
            pair_stems = {
                str(Path(name).with_suffix("")) for name in source.namelist()
                if Path(name).suffix.lower() == ".rd3" and str(Path(name).with_suffix("")) + ".rad" in source.namelist()
            }
            expected_stems = {str(profile[1]) for profile in selected}
            if pair_stems != expected_stems:
                raise SystemExit(f"exact RD3/RAD pair inventory changed: {archive}")
            for profile in selected:
                _archive, stem, compressed, size_bytes, crc, _traces, rad_sha, rd3_sha = profile
                rd3_info = source.getinfo(f"{stem}.rd3")
                if (rd3_info.compress_type, rd3_info.compress_size, rd3_info.file_size, f"{rd3_info.CRC:08x}") != (zipfile.ZIP_DEFLATED, compressed, size_bytes, crc):
                    raise SystemExit(f"pinned RD3 ZIP identity changed: {stem}")
                rd3 = source.read(rd3_info)
                rad = source.read(f"{stem}.rad")
                if hashlib.sha256(rd3).hexdigest() != rd3_sha or hashlib.sha256(rad).hexdigest() != rad_sha:
                    raise SystemExit(f"pinned extracted identity changed: {stem}")
                for suffix, raw in (("rd3", rd3), ("rad", rad)):
                    target = args.download_dir / f"{stem}.{suffix}"
                    part = target.with_suffix(target.suffix + ".part")
                    part.write_bytes(raw)
                    os.replace(part, target)

    inventory = []
    for profile in PROFILES:
        archive, stem, compressed, size, crc, traces, rad_sha, rd3_sha = profile
        if not valid_extracted(args.download_dir, profile):
            raise SystemExit(f"extracted profile failed validation: {stem}")
        inventory.append({
            "archive_name": archive, "archive_size": ARCHIVES[archive][0], "archive_md5": ARCHIVES[archive][1],
            "stem": stem, "rd3_compressed_size": compressed, "rd3_uncompressed_size": size,
            "rd3_crc32": crc, "trace_count": traces, "samples_per_trace": SAMPLES_PER_TRACE,
            "rad_sha256": rad_sha, "rd3_sha256": rd3_sha,
        })
    (args.download_dir / "source_inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n")
    print(f"validated {len(inventory)} profiles totaling {sum(int(x[3]) for x in PROFILES)} numeric bytes")


def local_record(download_dir: Path) -> None:
    path = download_dir / f"record_{RECORD_ID}.json"
    if not path.is_file():
        raise SystemExit("missing Zenodo metadata; run download.sh")
    validate_record(json.loads(path.read_text(encoding="utf-8")))


def decode_i16le(raw: bytes) -> array:
    values = array("h")
    values.frombytes(raw)
    if sys.byteorder != "little":
        values.byteswap()
    return values


def scan(download_dir: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    local_record(download_dir)
    reports = []
    profile_hashes: set[str] = set()
    prior_trace_hashes: set[bytes] = set()
    all_distinct_values: set[int] = set()
    for profile in PROFILES:
        archive, stem, _compressed, size, _crc, trace_count, rad_sha, rd3_sha = profile
        rd3_path = download_dir / f"{stem}.rd3"
        rad_path = download_dir / f"{stem}.rad"
        raw = rd3_path.read_bytes() if rd3_path.is_file() else b""
        rad = rad_path.read_bytes() if rad_path.is_file() else b""
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != rd3_sha or hashlib.sha256(rad).hexdigest() != rad_sha:
            raise SystemExit(f"missing or mismatched pinned source: {stem}")
        fields = parse_rad(rad)
        if fields.get("SAMPLES") != "1024" or fields.get("LAST TRACE") != str(trace_count) or fields.get("SHORT FLAG") != "1":
            raise SystemExit(f"RAD short/geometry declaration changed: {stem}")
        if len(raw) != trace_count * SAMPLES_PER_TRACE * 2 or rd3_sha in profile_hashes:
            raise SystemExit(f"RD3 geometry mismatch or duplicate profile: {stem}")
        profile_hashes.add(rd3_sha)
        values = decode_i16le(raw)
        all_distinct_values.update(values)
        trace_hashes: set[bytes] = set()
        minimum_distinct = SAMPLES_PER_TRACE
        minimum_transitions = SAMPLES_PER_TRACE
        constant_traces = 0
        for index in range(trace_count):
            value_start = index * SAMPLES_PER_TRACE
            value_end = value_start + SAMPLES_PER_TRACE
            trace_values = values[value_start:value_end]
            distinct = len(set(trace_values))
            transitions = sum(left != right for left, right in zip(trace_values, trace_values[1:]))
            minimum_distinct = min(minimum_distinct, distinct)
            minimum_transitions = min(minimum_transitions, transitions)
            constant_traces += distinct == 1
            byte_start, byte_end = value_start * 2, value_end * 2
            trace_hashes.add(hashlib.sha256(raw[byte_start:byte_end]).digest())
        within_duplicates = trace_count - len(trace_hashes)
        cross_duplicates = len(trace_hashes & prior_trace_hashes)
        if constant_traces or within_duplicates or cross_duplicates:
            raise SystemExit(f"constant or duplicate traces in {stem}")
        prior_trace_hashes.update(trace_hashes)
        reports.append({
            "archive_name": archive, "stem": stem, "output_name": f"{stem}_i16le.bin",
            "trace_count": trace_count, "samples_per_trace": SAMPLES_PER_TRACE,
            "value_count": len(values), "payload_bytes": len(raw), "minimum": min(values), "maximum": max(values),
            "zero_values": values.count(0), "minimum_saturation_values": values.count(-32768),
            "maximum_saturation_values": values.count(32767), "distinct_values": len(set(values)),
            "flattened_transitions": sum(left != right for left, right in zip(values, values[1:])),
            "minimum_trace_distinct_values": minimum_distinct, "minimum_trace_transitions": minimum_transitions,
            "constant_traces": constant_traces, "unique_trace_payloads": len(trace_hashes),
            "within_profile_duplicate_traces": within_duplicates,
            "trace_payloads_duplicated_from_prior_profiles": cross_duplicates,
            "sha256": rd3_sha, "zlib_ratio": round(len(zlib.compress(raw, 9)) / len(raw), 9),
            "antenna": fields.get("ANTENNAS", ""), "time_window": fields.get("TIMEWINDOW", ""),
        })
    ratios = [float(report["zlib_ratio"]) for report in reports]
    total_values = sum(int(report["value_count"]) for report in reports)
    total_zero = sum(int(report["zero_values"]) for report in reports)
    summary = {
        "dataset_id": DATASET_ID, "series_id": SERIES_ID, "record_id": RECORD_ID, "license": "cc-by-4.0",
        "profile_count": len(reports), "total_traces": sum(int(r["trace_count"]) for r in reports),
        "samples_per_trace": SAMPLES_PER_TRACE, "value_count": total_values,
        "total_size_bytes": sum(int(r["payload_bytes"]) for r in reports),
        "global_minimum": min(int(r["minimum"]) for r in reports), "global_maximum": max(int(r["maximum"]) for r in reports),
        "global_distinct_values": len(all_distinct_values), "zero_values": total_zero,
        "zero_fraction": round(total_zero / total_values, 9),
        "minimum_saturation_values": sum(int(r["minimum_saturation_values"]) for r in reports),
        "maximum_saturation_values": sum(int(r["maximum_saturation_values"]) for r in reports),
        "minimum_trace_distinct_values": min(int(r["minimum_trace_distinct_values"]) for r in reports),
        "minimum_trace_transitions": min(int(r["minimum_trace_transitions"]) for r in reports),
        "unique_profile_payloads": len(profile_hashes), "unique_trace_payloads": len(prior_trace_hashes),
        "within_profile_duplicate_traces": sum(int(r["within_profile_duplicate_traces"]) for r in reports),
        "cross_profile_duplicate_traces": sum(int(r["trace_payloads_duplicated_from_prior_profiles"]) for r in reports),
        "minimum_zlib_ratio": min(ratios), "median_zlib_ratio": statistics.median(ratios),
        "maximum_zlib_ratio": max(ratios), "profiles": reports,
    }
    expected = {
        "profile_count": 12, "total_traces": 98628, "value_count": 100995072,
        "total_size_bytes": 201990144, "global_minimum": -32768, "global_maximum": 32767,
        "global_distinct_values": 65365, "zero_values": 42752, "zero_fraction": 0.000423308,
        "minimum_saturation_values": 834, "maximum_saturation_values": 34,
        "minimum_trace_distinct_values": 269, "minimum_trace_transitions": 931,
        "unique_profile_payloads": 12, "unique_trace_payloads": 98628,
        "within_profile_duplicate_traces": 0, "cross_profile_duplicate_traces": 0,
        "minimum_zlib_ratio": 0.579121753, "median_zlib_ratio": 0.5925526745,
        "maximum_zlib_ratio": 0.681207321,
    }
    for key, value in expected.items():
        if summary[key] != value:
            raise SystemExit(f"aggregate source statistic changed for {key}: {summary[key]} != {value}")
    return reports, summary


def public_summary(summary: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in summary.items() if key != "profiles"}


def inspect(args: argparse.Namespace) -> None:
    _reports, summary = scan(args.download_dir)
    print(json.dumps(public_summary(summary), indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    reports, summary = scan(args.download_dir)
    series_dir = args.samples_dir / SERIES_ID
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True)
    rows = []
    for report in reports:
        source = args.download_dir / f"{report['stem']}.rd3"
        output = series_dir / str(report["output_name"])
        shutil.copyfile(source, output)
        rows.append({
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "role": "primary",
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "source_sample": f"downloads/{DATASET_ID}/{report['stem']}.rd3",
            "source_control_sample": f"downloads/{DATASET_ID}/{report['stem']}.rad",
            "numeric_kind": "int", "bit_width": 16, "endianness": "little", "element_size_bytes": 2,
            "value_count": report["value_count"], "sample_size_bytes": report["payload_bytes"],
            "sample_format": "raw homogeneous signed-int16 MALA GPR radargram",
            "sample_geometry": "2d_gpr_trace_time_sample_radargram", "sample_rank": 2,
            "sample_shape": [report["trace_count"], SAMPLES_PER_TRACE],
            "sample_axes": ["survey_trace", "two_way_travel_time_sample"],
            "natural_record_kind": "complete_gpr_survey_transect",
            "antenna": report["antenna"], "time_window": report["time_window"],
            "minimum": report["minimum"], "maximum": report["maximum"], "sha256": report["sha256"],
        })
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(public_summary(summary), indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    reports, summary = scan(args.download_dir)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or ingest stats; run build.sh")
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != len(reports):
        raise SystemExit("unexpected index row count")
    expected_outputs = set()
    for row, report in zip(rows, reports, strict=True):
        if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID or row.get("sample_shape") != [report["trace_count"], SAMPLES_PER_TRACE]:
            raise SystemExit(f"index identity or shape mismatch: {report['stem']}")
        if row.get("numeric_kind") != "int" or row.get("bit_width") != 16 or row.get("endianness") != "little":
            raise SystemExit(f"indexed representation mismatch: {report['stem']}")
        output = args.data_root / str(row["sample_path"])
        expected_outputs.add(output.resolve())
        if not output.is_file() or output.stat().st_size != report["payload_bytes"] or file_hash(output) != report["sha256"]:
            raise SystemExit(f"output is not byte-identical to RD3 source: {report['stem']}")
    actual_outputs = {path.resolve() for path in (args.data_root / "samples" / DATASET_ID).glob("*/*.bin")}
    if actual_outputs != expected_outputs or json.loads(args.stats.read_text(encoding="utf-8")) != summary:
        raise SystemExit("sample inventory or stored statistics changed")
    print(json.dumps({
        "dataset_id": DATASET_ID, "verified_samples": len(rows), "verified_traces": summary["total_traces"],
        "verified_values": summary["value_count"], "verified_bytes": summary["total_size_bytes"],
    }, indent=2, sort_keys=True))


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
