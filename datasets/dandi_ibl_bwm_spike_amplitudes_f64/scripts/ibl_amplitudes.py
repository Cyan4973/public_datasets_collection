#!/usr/bin/env python3
"""Plan, inventory and build the IBL Brain-Wide Map spike-amplitude samples.

Subcommands (all standard library, no network access; download.sh does every
fetch with curl and calls these to decide what to fetch next):

  meta-plan   walk the HDF5 metadata of each pinned session over locally cached
              64 KiB blocks; exit 3 with block_requests.tsv listing the blocks
              still needed, or exit 0 after writing layout.json per session and
              data_ranges.tsv (exact byte ranges of every compressed chunk of
              units/spike_amplitudes_uV and units/spike_amplitudes_uV_index)
  inventory   validate the license/asset metadata, every cached block and range,
              inflate every chunk, check the chunk grid, decoded size and index,
              and record the SHA-256 of every fetched range
  build       emit one little-endian float64 sample per kept unit plus the index
"""

from __future__ import annotations

import argparse
import array
import csv
import hashlib
import json
import math
import shutil
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nwb_hdf5 as H  # noqa: E402
from scale_test import float32_scale_test  # noqa: E402

DATASET_ID = "dandi_ibl_bwm_spike_amplitudes_f64"
SERIES_ID = "ibl_unit_spike_amplitudes_uv_f64"
DANDISET = "DANDI:000409"
VERSION = "0.260309.1324"
LICENSE = ["spdx:CC-BY-4.0"]
CHUNK_LENGTH = 1_250_000
MIN_SPIKES = 1000
AMP_PATH = "/units/spike_amplitudes_uV"
INDEX_PATH = "/units/spike_amplitudes_uV_index"
AMP_DESCRIPTION = "Peak amplitude of each spike for each unit in microvolts."
INDEX_DESCRIPTION = "Index for VectorData 'spike_amplitudes_uV'"
S3_PREFIX = "https://dandiarchive.s3.amazonaws.com/blobs/"
EXIT_NEED_BLOCKS = 3
# Realized output of the first build (2026-10-05), enforced on every rebuild.
EXPECTED_SAMPLES = 1321
EXPECTED_VALUES = 57_416_236
EXPECTED_AGGREGATE_SHA256 = "0ac190be63de4d8ddcad0208bf8ccbbef068a2c0eabf6e0f4323f1131aca1f9f"


# --------------------------------------------------------------------- pins
def blob_url(blob_id: str) -> str:
    return f"{S3_PREFIX}{blob_id[:3]}/{blob_id[3:6]}/{blob_id}"


def load_sessions(recipe_dir: Path) -> list[dict[str, object]]:
    with (recipe_dir / "sessions.tsv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    integer_fields = ("order", "size_bytes", "units", "spikes", "amp_chunks", "amp_stored_bytes",
                      "index_stored_bytes", "kept_units", "kept_spikes")
    sessions = []
    for row in rows:
        session: dict[str, object] = dict(row)
        for key in integer_fields:
            session[key] = int(row[key])
        session["url"] = blob_url(str(row["blob_id"]))
        sessions.append(session)
    if [s["order"] for s in sessions] != list(range(1, len(sessions) + 1)):
        raise SystemExit("sessions.tsv order column must be 1..n")
    if len({s["lab"] for s in sessions}) != len(sessions):
        raise SystemExit("sessions.tsv must hold one session per lab")
    return sessions


def session_dir(download_dir: Path, session: dict[str, object]) -> Path:
    return download_dir / "sessions" / str(session["asset_id"])


def label(session: dict[str, object]) -> str:
    return f"{session['subject_id']}_ses-{str(session['session_eid'])[:8]}"


# ----------------------------------------------------------- HDF5 metadata
def read_layout(raw, session: dict[str, object]) -> dict[str, object]:
    """Resolve and validate everything the recipe needs from one NWB file.

    ``raw`` is a BlockStore; MissingBlock propagates to the caller.
    """
    size = int(session["size_bytes"])
    h5 = H.H5File(raw, size)
    root = h5.attributes(h5.messages(h5.root_header))
    if root.get("neurodata_type") != "NWBFile" or root.get("namespace") != "core":
        raise ValueError(f"root is not an NWBFile: {root}")
    strings = {}
    for key, path in (("lab", "/general/lab"), ("institution", "/general/institution"),
                      ("session_eid", "/general/session_id"),
                      ("subject_id", "/general/subject/subject_id"),
                      ("nwb_identifier", "/identifier")):
        strings[key] = h5.scalar_string(h5.resolve(path))
    for key, value in strings.items():
        if value != session[key]:
            raise ValueError(f"{session['asset_id']}: {key} is {value!r}, pinned {session[key]!r}")
    units = h5.resolve("/units")
    units_attrs = h5.attributes(h5.messages(units))
    if units_attrs.get("neurodata_type") != "Units":
        raise ValueError("/units is not an NWB Units table")
    colnames = units_attrs.get("colnames") or []
    if "spike_amplitudes_uV" not in colnames:
        raise ValueError("spike_amplitudes_uV is not a Units column")
    if "Neuropixels 1.0" not in str(units_attrs.get("description", "")):
        raise ValueError("Units description no longer names Neuropixels 1.0 probes")

    amp = h5.dataset(h5.resolve(AMP_PATH))
    spikes, amp_chunk = H.validate_1d_deflate(amp, H.H5T_IEEE_F64LE, 8)
    if amp["attributes"].get("description") != AMP_DESCRIPTION:
        raise ValueError(f"amplitude description changed: {amp['attributes'].get('description')!r}")
    if amp["attributes"].get("neurodata_type") != "VectorData":
        raise ValueError("amplitude column is not VectorData")
    if amp_chunk != CHUNK_LENGTH:
        raise ValueError(f"amplitude chunk length {amp_chunk} != {CHUNK_LENGTH}")
    amp_plan = H.chunk_plan_1d(h5.chunks(int(amp["chunk_btree"]), 1), spikes, amp_chunk)

    index = h5.dataset(h5.resolve(INDEX_PATH))
    unit_count, index_chunk = H.validate_1d_deflate(index, H.H5T_STD_U32LE, 4)
    if index["attributes"].get("neurodata_type") != "VectorIndex":
        raise ValueError("amplitude index is not a VectorIndex")
    if index["attributes"].get("description") != INDEX_DESCRIPTION:
        raise ValueError("amplitude index description changed")
    index_plan = H.chunk_plan_1d(h5.chunks(int(index["chunk_btree"]), 1), unit_count, index_chunk)

    ids = h5.dataset(h5.resolve("/units/id"))
    if tuple(ids["shape"]) != (unit_count,):
        raise ValueError(f"/units/id shape {ids['shape']} != index length {unit_count}")

    layout = {
        "asset_id": session["asset_id"],
        "nwb_version": root.get("nwb_version"),
        **strings,
        "spikes": spikes,
        "units": unit_count,
        "amp_chunk_length": amp_chunk,
        "amp_deflate_level": amp["filters"][0][2][0],
        "amp_chunks": amp_plan,
        "index_chunk_length": index_chunk,
        "index_chunks": index_plan,
    }
    check_layout_pins(layout, session)
    return layout


def check_layout_pins(layout: dict[str, object], session: dict[str, object]) -> None:
    spikes = int(layout["spikes"])
    amp_chunks = list(layout["amp_chunks"])
    expected_chunks = -(-spikes // CHUNK_LENGTH)
    checks = {
        "spikes": (spikes, session["spikes"]),
        "units": (layout["units"], session["units"]),
        "amp_chunks": (len(amp_chunks), session["amp_chunks"]),
        "amp_chunks_ceil": (len(amp_chunks), expected_chunks),
        "amp_stored_bytes": (sum(c["stored_bytes"] for c in amp_chunks), session["amp_stored_bytes"]),
        "index_chunks": (len(layout["index_chunks"]), 1),
        "index_stored_bytes": (sum(c["stored_bytes"] for c in layout["index_chunks"]),
                               session["index_stored_bytes"]),
    }
    for key, (found, pinned) in checks.items():
        if int(found) != int(pinned):
            raise ValueError(f"{session['asset_id']}: {key} is {found}, pinned {pinned}")
    for chunk in list(amp_chunks) + list(layout["index_chunks"]):
        end = int(chunk["address"]) + int(chunk["stored_bytes"])
        if int(chunk["address"]) < 96 or end > int(session["size_bytes"]):
            raise ValueError(f"chunk outside file: {chunk}")


# ---------------------------------------------------------------- meta-plan
def command_meta_plan(args: argparse.Namespace) -> int:
    sessions = load_sessions(args.recipe_dir)
    requests = []
    ranges = []
    for session in sessions:
        sdir = session_dir(args.download_dir, session)
        store = H.BlockStore(sdir / "meta", int(session["size_bytes"]))
        try:
            layout = read_layout(store, session)
        except H.MissingBlock as missing:
            start, end = store.block_span(missing.index)
            requests.append([session["asset_id"], missing.index, start, end - 1,
                             session["url"], session["size_bytes"], session["dandi_etag"]])
            continue
        except ValueError as error:
            raise SystemExit(f"metadata validation failed for {session['asset_id']}: {error}")
        layout["metadata_blocks"] = sorted(store.used)
        (sdir / "layout.json").write_text(json.dumps(layout, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        for kind, key in (("index", "index_chunks"), ("amp", "amp_chunks")):
            for chunk in layout[key]:
                start = int(chunk["address"])
                end = start + int(chunk["stored_bytes"]) - 1
                relative = f"sessions/{session['asset_id']}/chunks/{kind}_{int(chunk['element_offset']):09d}.bin"
                ranges.append([session["asset_id"], kind, chunk["element_offset"], start, end,
                               end - start + 1, session["url"], session["size_bytes"],
                               session["dandi_etag"], relative])
    write_tsv(args.download_dir / "block_requests.tsv",
              ["asset_id", "block", "start", "end", "url", "total", "etag"], requests)
    if requests:
        print(f"meta_plan need_blocks={len(requests)}")
        return EXIT_NEED_BLOCKS
    write_tsv(args.download_dir / "data_ranges.tsv",
              ["asset_id", "kind", "element_offset", "start", "end", "length", "url", "total", "etag",
               "local_path"], ranges)
    total = sum(int(row[5]) for row in ranges)
    print(f"meta_plan complete sessions={len(sessions)} data_ranges={len(ranges)} data_bytes={total}")
    return 0


def write_tsv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


# --------------------------------------------------------------- inventory
def validate_version(path: Path) -> None:
    meta = json.loads(path.read_text(encoding="utf-8"))
    if meta.get("identifier") != DANDISET or meta.get("version") != VERSION:
        raise SystemExit(f"dandiset identity changed: {meta.get('identifier')} {meta.get('version')}")
    if meta.get("license") != LICENSE:
        raise SystemExit(f"dandiset license is {meta.get('license')}, expected {LICENSE}")
    statuses = [item.get("status") for item in meta.get("access", [])]
    if statuses != ["dandi:OpenAccess"]:
        raise SystemExit(f"dandiset access is {statuses}, expected dandi:OpenAccess")
    if meta.get("name") != "IBL - Brain Wide Map":
        raise SystemExit(f"dandiset name changed: {meta.get('name')!r}")


def validate_asset(path: Path, session: dict[str, object]) -> None:
    meta = json.loads(path.read_text(encoding="utf-8"))
    digest = meta.get("digest", {})
    problems = []
    if meta.get("identifier") != session["asset_id"]:
        problems.append("identifier")
    if meta.get("path") != session["asset_path"]:
        problems.append("path")
    if int(meta.get("contentSize", -1)) != int(session["size_bytes"]):
        problems.append("contentSize")
    if digest.get("dandi:dandi-etag") != session["dandi_etag"]:
        problems.append("dandi-etag")
    if digest.get("dandi:sha2-256") != session["dandi_sha256"]:
        problems.append("sha2-256")
    if session["url"] not in meta.get("contentUrl", []):
        problems.append("contentUrl")
    if meta.get("encodingFormat") != "application/x-nwb":
        problems.append("encodingFormat")
    if [item.get("status") for item in meta.get("access", [])] != ["dandi:OpenAccess"]:
        problems.append("access")
    participants = meta.get("wasAttributedTo", [])
    if len(participants) != 1 or participants[0].get("identifier") != session["subject_id"]:
        problems.append("participant")
    elif "Mus musculus" not in str(participants[0].get("species", {}).get("name", "")):
        problems.append("species")
    if problems:
        raise SystemExit(f"asset metadata mismatch for {session['asset_id']}: {problems}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_index(chunk_path: Path, layout: dict[str, object]) -> list[int]:
    chunk = layout["index_chunks"][0]
    payload = chunk_path.read_bytes()
    if len(payload) != int(chunk["stored_bytes"]):
        raise ValueError(f"index chunk size mismatch: {chunk_path}")
    data = H.inflate_exact(payload, int(layout["index_chunk_length"]) * 4)
    units = int(layout["units"])
    values = list(struct.unpack(f"<{units}I", data[: units * 4]))
    if any(b < a for a, b in zip(values, values[1:])) or values[0] < 0:
        raise ValueError("spike_amplitudes_uV_index is not monotone non-decreasing")
    if values[-1] != int(layout["spikes"]):
        raise ValueError(f"last index entry {values[-1]} != spike count {layout['spikes']}")
    return values


def command_check_metadata(args: argparse.Namespace) -> int:
    sessions = load_sessions(args.recipe_dir)
    validate_version(args.download_dir / "metadata" / "dandiset_version.json")
    for session in sessions:
        validate_asset(args.download_dir / "metadata" / f"asset_{session['asset_id']}.json", session)
    print(f"metadata_ok dandiset={DANDISET} version={VERSION} license={LICENSE[0]} sessions={len(sessions)}")
    return 0


def command_inventory(args: argparse.Namespace) -> int:
    sessions = load_sessions(args.recipe_dir)
    validate_version(args.download_dir / "metadata" / "dandiset_version.json")
    ranges = read_tsv(args.download_dir / "data_ranges.tsv")
    inventory_rows = []
    summary = []
    for session in sessions:
        validate_asset(args.download_dir / "metadata" / f"asset_{session['asset_id']}.json", session)
        sdir = session_dir(args.download_dir, session)
        store = H.BlockStore(sdir / "meta", int(session["size_bytes"]))
        try:
            layout = read_layout(store, session)
        except (H.MissingBlock, ValueError) as error:
            raise SystemExit(f"metadata re-validation failed for {session['asset_id']}: {error}")
        recorded = json.loads((sdir / "layout.json").read_text(encoding="utf-8"))
        recorded.pop("metadata_blocks", None)
        if json.loads(json.dumps(layout, sort_keys=True)) != recorded:
            raise SystemExit(f"layout.json for {session['asset_id']} does not match the cached metadata")
        for block in sorted(store.used):
            path = store.block_path(block)
            start, end = store.block_span(block)
            inventory_rows.append([session["asset_id"], "meta", start, end - 1, end - start,
                                   str(path.relative_to(args.download_dir)), sha256_file(path)])
        session_ranges = [row for row in ranges if row["asset_id"] == session["asset_id"]]
        if len(session_ranges) != len(layout["amp_chunks"]) + len(layout["index_chunks"]):
            raise SystemExit(f"data_ranges.tsv incomplete for {session['asset_id']}")
        for row in session_ranges:
            path = args.download_dir / row["local_path"]
            if not path.is_file() or path.stat().st_size != int(row["length"]):
                raise SystemExit(f"missing or truncated range {row['local_path']}; re-run download.sh")
        index_rows = [row for row in session_ranges if row["kind"] == "index"]
        index = load_index(args.download_dir / index_rows[0]["local_path"], layout)
        decoded_valid = 0
        for chunk, row in zip(layout["amp_chunks"], [r for r in session_ranges if r["kind"] == "amp"]):
            if int(row["element_offset"]) != int(chunk["element_offset"]) or int(row["start"]) != int(chunk["address"]):
                raise SystemExit(f"data_ranges.tsv disagrees with the chunk B-tree for {session['asset_id']}")
            path = args.download_dir / row["local_path"]
            try:
                H.inflate_exact(path.read_bytes(), CHUNK_LENGTH * 8)
            except ValueError as error:
                path.unlink()
                raise SystemExit(f"corrupt chunk {row['local_path']} removed ({error}); re-run download.sh")
            decoded_valid += int(chunk["valid_elements"]) * 8
        if decoded_valid != 8 * int(layout["spikes"]):
            raise SystemExit(f"decoded size {decoded_valid} != 8 x {layout['spikes']}")
        counts = [index[0]] + [b - a for a, b in zip(index, index[1:])]
        kept = [c for c in counts if c >= MIN_SPIKES]
        if len(kept) != int(session["kept_units"]) or sum(kept) != int(session["kept_spikes"]):
            raise SystemExit(f"kept units/spikes {len(kept)}/{sum(kept)} differ from pins for {session['asset_id']}")
        for row in session_ranges:
            path = args.download_dir / row["local_path"]
            inventory_rows.append([session["asset_id"], row["kind"], row["start"], row["end"], row["length"],
                                   row["local_path"], sha256_file(path)])
        summary.append({"asset_id": session["asset_id"], "lab": session["lab"], "spikes": layout["spikes"],
                        "units": layout["units"], "amp_chunks": len(layout["amp_chunks"]),
                        "kept_units": len(kept), "kept_spikes": sum(kept)})
        print(f"inventory_ok asset={session['asset_id']} lab={session['lab']} spikes={layout['spikes']} "
              f"units={layout['units']} chunks={len(layout['amp_chunks'])} kept_units={len(kept)}")
    write_tsv(args.download_dir / "range_sha256.tsv",
              ["asset_id", "kind", "start", "end", "length", "local_path", "sha256"], inventory_rows)
    total = sum(int(row[4]) for row in inventory_rows)
    (args.download_dir / "download_inventory.json").write_text(
        json.dumps({"sessions": summary, "ranges": len(inventory_rows), "range_bytes": total}, indent=1) + "\n",
        encoding="utf-8")
    print(f"inventory complete ranges={len(inventory_rows)} range_bytes={total}")
    return 0


# ------------------------------------------------------------------- build
class ChunkStream:
    """Sequential reader of the logical float64 vector, one chunk in memory."""

    def __init__(self, download_dir: Path, session: dict[str, object], layout: dict[str, object]) -> None:
        self.paths = []
        self.chunks = list(layout["amp_chunks"])
        for chunk in self.chunks:
            self.paths.append(download_dir / "sessions" / str(session["asset_id"]) / "chunks"
                              / f"amp_{int(chunk['element_offset']):09d}.bin")
        self.current = -1
        self.data = b""
        self.decoded = set()
        self.valid_bytes = 0

    def _load(self, index: int) -> None:
        if index == self.current:
            return
        if index in self.decoded:
            raise ValueError("non-sequential chunk access")
        chunk = self.chunks[index]
        payload = self.paths[index].read_bytes()
        if len(payload) != int(chunk["stored_bytes"]):
            raise ValueError(f"chunk size mismatch {self.paths[index]}")
        full = H.inflate_exact(payload, CHUNK_LENGTH * 8)
        self.data = full[: int(chunk["valid_elements"]) * 8]
        self.current = index
        self.decoded.add(index)
        self.valid_bytes += len(self.data)

    def read(self, start: int, end: int) -> bytes:
        out = bytearray()
        position = start
        while position < end:
            index = position // CHUNK_LENGTH
            self._load(index)
            base = index * CHUNK_LENGTH
            take_end = min(end, base + CHUNK_LENGTH)
            out += self.data[(position - base) * 8 : (take_end - base) * 8]
            position = take_end
        return bytes(out)

    def finish(self) -> None:
        for index in range(len(self.chunks)):
            if index not in self.decoded:
                self._load(index)


def sample_stats(raw: bytes) -> dict[str, object]:
    values = array.array("d")
    values.frombytes(raw)
    if sys.byteorder != "little":
        values.byteswap()
    nonfinite = sum(1 for v in values if not math.isfinite(v))
    if nonfinite:
        raise ValueError(f"{nonfinite} non-finite amplitudes")
    narrowed = array.array("f", values)
    f32_exact = sum(1 for a, b in zip(values, narrowed) if a == b)
    lcm_bits, max_err = float32_scale_test(values)
    return {
        "min": min(values),
        "max": max(values),
        "distinct_values": len(set(values)),
        "nonpositive_values": sum(1 for v in values if v <= 0.0),
        "float32_exact_values": f32_exact,
        "f32_ratio_lcm_bits": lcm_bits,
        "f32_ratio_max_rel_err": max_err,
    }


def command_build(args: argparse.Namespace) -> int:
    sessions = load_sessions(args.recipe_dir)
    data_root = args.data_root
    download_dir = data_root / "downloads" / DATASET_ID
    out_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_dir = data_root / "index" / DATASET_ID
    filtered_dir = data_root / "filtered" / DATASET_ID
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    index_dir.mkdir(parents=True, exist_ok=True)
    filtered_dir.mkdir(parents=True, exist_ok=True)
    checksums = {row["local_path"]: row["sha256"] for row in read_tsv(download_dir / "range_sha256.tsv")}
    rows = []
    session_stats = []
    seen_hashes: dict[str, str] = {}
    for session in sessions:
        sdir = session_dir(download_dir, session)
        store = H.BlockStore(sdir / "meta", int(session["size_bytes"]))
        layout = read_layout(store, session)
        for block in sorted(store.used):
            relative = str(store.block_path(block).relative_to(download_dir))
            if checksums.get(relative) != sha256_file(store.block_path(block)):
                raise SystemExit(f"metadata block checksum mismatch: {relative}")
        chunk_dir = sdir / "chunks"
        for path in sorted(chunk_dir.glob("*.bin")):
            relative = str(path.relative_to(download_dir))
            if checksums.get(relative) != sha256_file(path):
                raise SystemExit(f"range checksum mismatch: {relative}")
        index = load_index(chunk_dir / "index_000000000.bin", layout)
        stream = ChunkStream(download_dir, session, layout)
        bounds = [0] + index
        kept = dropped = dropped_spikes = 0
        consistent = 0
        max_lcm_bits = 0
        for row_number in range(int(layout["units"])):
            start, end = bounds[row_number], bounds[row_number + 1]
            raw = stream.read(start, end)
            count = end - start
            if count < MIN_SPIKES:
                dropped += 1
                dropped_spikes += count
                continue
            stats = sample_stats(raw)
            if stats["distinct_values"] < 2:
                raise SystemExit(f"constant amplitude vector: {label(session)} unit {row_number}")
            digest = hashlib.sha256(raw).hexdigest()
            name = f"{label(session)}_unit{row_number:04d}.bin"
            if digest in seen_hashes:
                raise SystemExit(f"duplicate sample {name} == {seen_hashes[digest]}")
            seen_hashes[digest] = name
            (out_dir / name).write_bytes(raw)
            kept += 1
            if stats["f32_ratio_lcm_bits"] <= 24 and stats["f32_ratio_max_rel_err"] < 1e-15:
                consistent += 1
            max_lcm_bits = max(max_lcm_bits, int(stats["f32_ratio_lcm_bits"]))
            rows.append({
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": f"samples/{DATASET_ID}/{SERIES_ID}/{name}",
                "numeric_kind": "float",
                "bit_width": 64,
                "endianness": "little",
                "element_size_bytes": 8,
                "sample_size_bytes": len(raw),
                "value_count": count,
                "lab": session["lab"],
                "subject_id": session["subject_id"],
                "session_eid": session["session_eid"],
                "asset_id": session["asset_id"],
                "unit_row": row_number,
                "ragged_start": start,
                **stats,
                "sha256": digest,
            })
        stream.finish()
        if stream.valid_bytes != 8 * int(layout["spikes"]):
            raise SystemExit(f"decoded {stream.valid_bytes} bytes != 8 x {layout['spikes']}")
        if kept != int(session["kept_units"]):
            raise SystemExit(f"kept {kept} units, pinned {session['kept_units']}")
        session_stats.append({
            "asset_id": session["asset_id"],
            "lab": session["lab"],
            "subject_id": session["subject_id"],
            "session_eid": session["session_eid"],
            "units": layout["units"],
            "spikes": layout["spikes"],
            "amp_chunks": len(layout["amp_chunks"]),
            "kept_units": kept,
            "kept_spikes": int(layout["spikes"]) - dropped_spikes,
            "dropped_units": dropped,
            "dropped_spikes": dropped_spikes,
            "f32_scale_consistent_units": consistent,
            "max_f32_ratio_lcm_bits": max_lcm_bits,
        })
        print(f"session {label(session)} lab={session['lab']} units={layout['units']} kept={kept} "
              f"dropped={dropped} dropped_spikes={dropped_spikes} f32_scale_consistent={consistent}/{kept}")
    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    aggregate = hashlib.sha256("".join(row["sha256"] + "\n" for row in rows).encode()).hexdigest()
    totals = {
        "samples": len(rows),
        "values": sum(row["value_count"] for row in rows),
        "bytes": sum(row["sample_size_bytes"] for row in rows),
        "min": min(row["min"] for row in rows),
        "max": max(row["max"] for row in rows),
        "float32_exact_values": sum(row["float32_exact_values"] for row in rows),
        "nonpositive_values": sum(row["nonpositive_values"] for row in rows),
        "f32_scale_consistent_units": sum(s["f32_scale_consistent_units"] for s in session_stats),
        "aggregate_sha256": aggregate,
    }
    (filtered_dir / "ingest_stats.json").write_text(
        json.dumps({"sessions": session_stats, "totals": totals}, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")
    print("build totals " + json.dumps(totals, sort_keys=True))
    if (totals["samples"], totals["values"], aggregate) != (EXPECTED_SAMPLES, EXPECTED_VALUES,
                                                            EXPECTED_AGGREGATE_SHA256):
        raise SystemExit(f"realized output differs from the pinned build: samples={totals['samples']} "
                         f"values={totals['values']} aggregate={aggregate}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("check-metadata", "meta-plan", "inventory"):
        item = sub.add_parser(name)
        item.add_argument("--download-dir", type=Path, required=True)
        item.add_argument("--recipe-dir", type=Path, required=True)
    item = sub.add_parser("build")
    item.add_argument("--data-root", type=Path, required=True)
    item.add_argument("--recipe-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "check-metadata":
        return command_check_metadata(args)
    if args.command == "meta-plan":
        return command_meta_plan(args)
    if args.command == "inventory":
        return command_inventory(args)
    return command_build(args)


if __name__ == "__main__":
    raise SystemExit(main())
