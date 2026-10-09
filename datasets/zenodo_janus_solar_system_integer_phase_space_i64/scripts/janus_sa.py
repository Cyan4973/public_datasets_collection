#!/usr/bin/env python3
"""Decode REBOUND JANUS SimulationArchive files (Zenodo record 546258).

File layout (written by a REBOUND 3.2.2 development build, banner git hash
b0f792d..., before the 3.4.0 release split the JANUS scale in two):

  * 64-byte ASCII banner "REBOUND Binary File. Version: 3.2.2" + NUL + githash
  * tagged fields: uint32 type, uint32 pad, uint64 size, payload[size]
      4   N (uint32)                       must be 9 (Sun + 8 planets)
      45  SASIZEFIRST (int64)              byte offset of the first snapshot
      46  SASIZESNAPSHOT (int64)           bytes per snapshot, must be 448
      47  SAINTERVAL (double)              archive cadence in simulation time
      51  INTEGRATOR (uint32)              must be 8 = REB_INTEGRATOR_JANUS
      85  PARTICLES (N x 128-byte reb_particle, initial doubles)
      108 JANUS_SCALE (double)             fixed-point scale, here 1e16
      109 JANUS_SAFEMODE (uint32)          must be 0 (archive requires it)
      9999 END (size 0)
  * fixed-size snapshots: double t, double walltime, then N reb_particle_int
    records of six little-endian int64 (x, y, z, vx, vy, vz), each equal to
    the double coordinate multiplied by JANUS_SCALE.

Output: two primary series cut verbatim from each 48-byte body record --
position = bytes [0, 24) (x, y, z), velocity = bytes [24, 48) (vx, vy, vz) --
each shaped [snapshots, 9, 3], plus the auxiliary float64 snapshot time.

Pure standard library; numpy is not used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
from array import array
from pathlib import Path

DATASET_ID = "zenodo_janus_solar_system_integer_phase_space_i64"
POS_SERIES = "janus_solar_system_position_i64"
VEL_SERIES = "janus_solar_system_velocity_i64"
PRIMARY_SERIES = (POS_SERIES, VEL_SERIES)
AUX_SERIES = "janus_snapshot_time_f64"
BANNER_PREFIX = b"REBOUND Binary File. Version: 3.2.2\x00"
N_BODIES = 9
COMPONENTS = 6
SNAPSHOT_BYTES = 16 + N_BODIES * COMPONENTS * 8  # 448
INTEGRATOR_JANUS = 8
FIELD_END = 9999
PARTICLE_STRUCT_BYTES = 128
BODY_NAMES = ["Sun", "Mercury", "Venus", "Earth", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune"]
COMPONENT_NAMES = ["x", "y", "z", "vx", "vy", "vz"]
BODY_RECORD_BYTES = COMPONENTS * 8  # 48
TRIPLE_BYTES = 3 * 8  # 24
# Per-series component names and generous physical bounds in simulation units
# (G = 1, AU, yr/2pi): every body inside 100 AU, every speed below 10.
SERIES_SPEC = {
    POS_SERIES: {"components": ["x", "y", "z"], "bound": 100.0},
    VEL_SERIES: {"components": ["vx", "vy", "vz"], "bound": 10.0},
}
INT64_MAX = 2**63 - 1

if sys.byteorder != "little":  # array('q'/'d') byte copies assume LE host
    raise SystemExit("this decoder requires a little-endian host")


class FormatError(Exception):
    pass


def parse_header(blob: bytes) -> dict:
    if len(blob) < 64 or not blob.startswith(BANNER_PREFIX):
        raise FormatError(f"bad banner {blob[:64]!r}")
    githash = blob[len(BANNER_PREFIX):64].split(b"\x00", 1)[0].decode("ascii", "replace")
    fields: dict[int, bytes] = {}
    off = 64
    while True:
        if off + 16 > len(blob):
            raise FormatError("header runs past end of file")
        ftype, pad, size = struct.unpack_from("<IIQ", blob, off)
        if pad != 0:
            raise FormatError(f"nonzero pad in field header at {off}")
        if off + 16 + size > len(blob) or size > 1 << 20:
            raise FormatError(f"field {ftype} size {size} out of bounds at {off}")
        if ftype in fields:
            raise FormatError(f"duplicate field {ftype}")
        fields[ftype] = blob[off + 16 : off + 16 + size]
        off += 16 + size
        if ftype == FIELD_END:
            if size != 0:
                raise FormatError("END field has payload")
            break

    def get(ftype: int, fmt: str):
        payload = fields.get(ftype)
        if payload is None or len(payload) != struct.calcsize(fmt):
            raise FormatError(f"field {ftype} missing or wrong size")
        return struct.unpack(fmt, payload)[0]

    header = {
        "githash": githash,
        "header_bytes": off,
        "N": get(4, "<I"),
        "G": get(1, "<d"),
        "dt": get(3, "<d"),
        "sa_size_first": get(45, "<q"),
        "sa_size_snapshot": get(46, "<q"),
        "sa_interval": get(47, "<d"),
        "integrator": get(51, "<I"),
        "janus_scale": get(108, "<d"),
        "janus_safe_mode": get(109, "<I"),
    }
    if header["N"] != N_BODIES:
        raise FormatError(f"N={header['N']} != {N_BODIES}")
    if header["integrator"] != INTEGRATOR_JANUS:
        raise FormatError(f"integrator={header['integrator']} is not JANUS")
    if header["sa_size_first"] != off:
        raise FormatError(f"SASIZEFIRST {header['sa_size_first']} != header end {off}")
    if header["sa_size_snapshot"] != SNAPSHOT_BYTES:
        raise FormatError(f"SASIZESNAPSHOT {header['sa_size_snapshot']} != {SNAPSHOT_BYTES}")
    if header["janus_safe_mode"] != 0:
        raise FormatError("JANUS safe_mode set; archive layout undefined")
    if not (header["janus_scale"] > 0 and math.isfinite(header["janus_scale"])):
        raise FormatError(f"bad JANUS scale {header['janus_scale']}")
    if not (header["sa_interval"] > 0 and header["dt"] > 0):
        raise FormatError("nonpositive archive interval or timestep")
    particles = fields.get(85)
    if particles is None or len(particles) != N_BODIES * PARTICLE_STRUCT_BYTES:
        raise FormatError("PARTICLES field missing or wrong size")
    header["masses"] = [
        struct.unpack_from("<d", particles, i * PARTICLE_STRUCT_BYTES + 9 * 8)[0] for i in range(N_BODIES)
    ]
    if abs(header["masses"][0] - 1.0) > 1e-12 or not all(0 < m < 1e-2 for m in header["masses"][1:]):
        raise FormatError(f"unexpected masses {header['masses']}")
    return header


def decode(blob: bytes) -> tuple[dict, bytes, array, array]:
    """Return header, int64 block bytes, t array, walltime array."""
    header = parse_header(blob)
    start = header["sa_size_first"]
    body = len(blob) - start
    if body <= 0 or body % SNAPSHOT_BYTES:
        raise FormatError(f"(size - header) = {body} not a positive multiple of {SNAPSHOT_BYTES}")
    nsnap = body // SNAPSHOT_BYTES
    view = memoryview(blob)
    ints = bytearray(nsnap * (SNAPSHOT_BYTES - 16))
    times = array("d")
    walls = array("d")
    step = SNAPSHOT_BYTES - 16
    for k in range(nsnap):
        off = start + k * SNAPSHOT_BYTES
        t, w = struct.unpack_from("<2d", blob, off)
        times.append(t)
        walls.append(w)
        ints[k * step : (k + 1) * step] = view[off + 16 : off + SNAPSHOT_BYTES]
    header["snapshot_count"] = nsnap
    return header, bytes(ints), times, walls


def split_block(ints: bytes) -> dict[str, bytes]:
    """Cut each 48-byte body record into its verbatim position and velocity triples."""
    if len(ints) % BODY_RECORD_BYTES:
        raise FormatError("int64 block is not a whole number of body records")
    view = memoryview(ints)
    n = len(ints)
    pos = b"".join(view[o : o + TRIPLE_BYTES] for o in range(0, n, BODY_RECORD_BYTES))
    vel = b"".join(view[o + TRIPLE_BYTES : o + BODY_RECORD_BYTES] for o in range(0, n, BODY_RECORD_BYTES))
    return {POS_SERIES: pos, VEL_SERIES: vel}


def check_times(header: dict, times: array, walls: array) -> dict:
    interval = header["sa_interval"]
    dt = header["dt"]
    prev = -math.inf
    min_gap = math.inf
    max_gap = -math.inf
    for t in times:
        if not math.isfinite(t) or t <= prev:
            raise FormatError(f"snapshot time not strictly increasing: {prev} -> {t}")
        if prev != -math.inf:
            gap = t - prev
            min_gap = min(min_gap, gap)
            max_gap = max(max_gap, gap)
        prev = t
    # Archive writes the first step at or after each multiple of the interval.
    if not (interval - 2 * dt <= min_gap and max_gap <= interval + 2 * dt):
        raise FormatError(f"snapshot spacing [{min_gap}, {max_gap}] inconsistent with interval {interval} (dt {dt})")
    if not times[0] > 0:
        raise FormatError(f"first snapshot t={times[0]} not positive")
    # Walltime is bookkeeping only (it may restart); record, do not gate.
    if not all(math.isfinite(w) and w >= 0 for w in walls):
        raise FormatError("non-finite or negative walltime; blob misalignment suspected")
    decreases = sum(1 for a, b in zip(walls, walls[1:]) if b < a)
    return {"t_first": times[0], "t_last": times[-1], "gap_min": min_gap, "gap_max": max_gap,
            "walltime_last_s": walls[-1], "walltime_decreases": decreases}


def int_stats(header: dict, payload: bytes, series: str) -> dict:
    spec = SERIES_SPEC[series]
    values = array("q")
    values.frombytes(payload)
    nsnap = header["snapshot_count"]
    per = N_BODIES * 3
    if len(values) != nsnap * per:
        raise FormatError(f"{series}: int64 block length mismatch")
    scale = header["janus_scale"]
    bound = spec["bound"] * scale
    col_min = [0] * per
    col_max = [0] * per
    for c in range(per):
        col = values[c::per]
        col_min[c] = min(col)
        col_max[c] = max(col)
        name = f"{BODY_NAMES[c // 3]}.{spec['components'][c % 3]}"
        if col_min[c] == col_max[c]:
            raise FormatError(f"{series}: constant column {name}")
        # The frame is not re-centred, so the Sun drifts with the barycentre
        # (restart_0000: ~0.7 AU over 3e8 yr); no tighter Sun bound. Misaligned
        # blobs would decode to values near the int64 limits (~922 AU at 1e16).
        if max(abs(col_min[c]), abs(col_max[c])) > bound:
            raise FormatError(f"{series}: {name} exceeds {spec['bound']} x scale")
    distinct_probe = len(set(values[: min(len(values), 100000)]))
    if distinct_probe < 1000:
        raise FormatError(f"{series}: degenerate integer block (too few distinct values)")
    return {"min": min(col_min), "max": max(col_max), "value_count": len(values)}


def load_files_tsv(path: Path) -> list[dict]:
    rows = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if i == 0 or not line.strip():
            continue
        key, size, md5 = line.split("\t")
        rows.append({"key": key, "size": int(size), "md5": md5})
    if len(rows) != 24:
        raise SystemExit(f"expected 24 pinned files, got {len(rows)}")
    return rows


def cmd_validate(args) -> None:
    path = Path(args.file)
    blob = path.read_bytes()
    header, ints, times, walls = decode(blob)
    tstats = check_times(header, times, walls)
    parts = split_block(ints)
    st = {sid: int_stats(header, parts[sid], sid) for sid in PRIMARY_SERIES}
    print(f"validate=ok file={path.name} snapshots={header['snapshot_count']} header_bytes={header['header_bytes']} "
          f"scale={header['janus_scale']:g} t_last={tstats['t_last']:.6g} "
          f"pos=[{st[POS_SERIES]['min']},{st[POS_SERIES]['max']}] vel=[{st[VEL_SERIES]['min']},{st[VEL_SERIES]['max']}]")


def sample_rel(series: str, key: str, suffix: str = ".bin") -> str:
    return f"samples/{DATASET_ID}/{series}/{Path(key).stem}{suffix}"


def cmd_build(args) -> None:
    data_root = Path(args.data_root)
    downloads = data_root / "downloads" / DATASET_ID
    files = load_files_tsv(Path(args.files))
    rows = []
    stats = {"dataset_id": DATASET_ID, "files": []}
    for spec in files:
        src = downloads / spec["key"]
        blob = src.read_bytes()
        if len(blob) != spec["size"]:
            raise SystemExit(f"{src}: size {len(blob)} != pinned {spec['size']}")
        header, ints, times, walls = decode(blob)
        tstats = check_times(header, times, walls)
        parts = split_block(ints)
        tbytes = times.tobytes()
        common = {"dataset_id": DATASET_ID, "endianness": "little", "element_size_bytes": 8,
                  "source_file": spec["key"], "source_md5": spec["md5"],
                  "snapshot_count": header["snapshot_count"]}
        outputs = []
        for sid in PRIMARY_SERIES:
            payload = parts[sid]
            istats = int_stats(header, payload, sid)
            rel = sample_rel(sid, spec["key"])
            outputs.append((rel, payload))
            rows.append({**common, "series_id": sid, "sample_path": rel,
                         "numeric_kind": "int", "bit_width": 64, "sample_size_bytes": len(payload),
                         "value_count": istats["value_count"],
                         "sample_shape": [header["snapshot_count"], N_BODIES, 3],
                         "min": istats["min"], "max": istats["max"],
                         "sha256": hashlib.sha256(payload).hexdigest()})
        aux_rel = sample_rel(AUX_SERIES, spec["key"])
        outputs.append((aux_rel, tbytes))
        rows.append({**common, "series_id": AUX_SERIES, "sample_path": aux_rel,
                     "numeric_kind": "float", "bit_width": 64, "sample_size_bytes": len(tbytes),
                     "value_count": len(times), "sample_shape": [header["snapshot_count"]],
                     "min": times[0], "max": times[-1],
                     "sha256": hashlib.sha256(tbytes).hexdigest()})
        for rel, payload in outputs:
            out = data_root / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".bin.part")
            tmp.write_bytes(payload)
            tmp.replace(out)
        stats["files"].append({"key": spec["key"], **{k: v for k, v in header.items() if k != "masses"},
                               "masses": header["masses"], **tstats})
        print(f"built {spec['key']} snapshots={header['snapshot_count']} bytes_per_series={len(ints) // 2} "
              f"t_last={tstats['t_last']:.6g}", flush=True)
    scales = {f["janus_scale"] for f in stats["files"]}
    if len(scales) != 1:
        raise SystemExit(f"JANUS scale differs across files: {scales}")
    index = data_root / "index" / DATASET_ID / "samples.jsonl"
    index.parent.mkdir(parents=True, exist_ok=True)
    with index.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats["series_totals"] = {}
    for sid in (*PRIMARY_SERIES, AUX_SERIES):
        sel = [r for r in rows if r["series_id"] == sid]
        stats["series_totals"][sid] = {"samples": len(sel),
                                       "bytes": sum(r["sample_size_bytes"] for r in sel),
                                       "values": sum(r["value_count"] for r in sel)}
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for sid, t in stats["series_totals"].items():
        print(f"build summary series={sid} samples={t['samples']} bytes={t['bytes']} values={t['values']}")


def toml_series_totals(manifest: Path) -> dict:
    import tomllib
    data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    return {s["id"]: (int(s["sample_count"]), int(s["total_size_bytes"])) for s in data["series"]}


def cmd_verify(args) -> None:
    data_root = Path(args.data_root)
    downloads = data_root / "downloads" / DATASET_ID
    files = load_files_tsv(Path(args.files))
    index = data_root / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_key = {(r["series_id"], r["source_file"]): r for r in rows}
    all_series = (*PRIMARY_SERIES, AUX_SERIES)
    if len(by_key) != len(rows) or len(rows) != len(all_series) * len(files):
        raise SystemExit(f"index has {len(rows)} rows, expected {len(all_series) * len(files)} unique")
    totals = {sid: [0, 0, 0] for sid in all_series}  # samples, bytes, values
    seen_hashes = {sid: set() for sid in PRIMARY_SERIES}
    for spec in files:
        src = downloads / spec["key"]
        blob = src.read_bytes()
        if hashlib.md5(blob).hexdigest() != spec["md5"]:
            raise SystemExit(f"{src}: md5 mismatch")
        # Independent re-derivation: walk snapshots and body records by stride
        # straight from SASIZEFIRST rather than reusing the build-time copy.
        header = parse_header(blob)
        start = header["sa_size_first"]
        nsnap, rem = divmod(len(blob) - start, SNAPSHOT_BYTES)
        if rem:
            raise SystemExit(f"{src}: trailing partial snapshot")
        h_block = hashlib.sha256()
        h_ser = {sid: hashlib.sha256() for sid in PRIMARY_SERIES}
        h_t = hashlib.sha256()
        prev_t = -math.inf
        for k in range(nsnap):
            off = start + k * SNAPSHOT_BYTES
            h_t.update(blob[off : off + 8])
            t = struct.unpack_from("<d", blob, off)[0]
            if not t > prev_t:
                raise SystemExit(f"{src}: snapshot {k} time not increasing")
            prev_t = t
            h_block.update(blob[off + 16 : off + SNAPSHOT_BYTES])
            for b in range(N_BODIES):
                rec = off + 16 + b * 48
                h_ser[POS_SERIES].update(blob[rec : rec + 24])
                h_ser[VEL_SERIES].update(blob[rec + 24 : rec + 48])
        expected = {POS_SERIES: (h_ser[POS_SERIES].hexdigest(), nsnap * 27, "int"),
                    VEL_SERIES: (h_ser[VEL_SERIES].hexdigest(), nsnap * 27, "int"),
                    AUX_SERIES: (h_t.hexdigest(), nsnap, "float")}
        payloads = {}
        for sid, (digest, count, kind) in expected.items():
            row = by_key.get((sid, spec["key"]))
            if row is None:
                raise SystemExit(f"missing index row {sid} for {spec['key']}")
            path = data_root / row["sample_path"]
            payload = path.read_bytes()
            if (row["dataset_id"] != DATASET_ID or row["numeric_kind"] != kind or row["bit_width"] != 64
                    or row["endianness"] != "little" or row["element_size_bytes"] != 8):
                raise SystemExit(f"{path}: index typing mismatch")
            if len(payload) != row["sample_size_bytes"] or len(payload) != count * 8 or row["value_count"] != count:
                raise SystemExit(f"{path}: size/count mismatch")
            if hashlib.sha256(payload).hexdigest() != digest or row["sha256"] != digest:
                raise SystemExit(f"{path}: content differs from source re-derivation")
            totals[sid][0] += 1
            totals[sid][1] += len(payload)
            totals[sid][2] += count
            payloads[sid] = payload
        # Re-interleaving position and velocity must reproduce the native block.
        pos_v, vel_v = memoryview(payloads[POS_SERIES]), memoryview(payloads[VEL_SERIES])
        h_re = hashlib.sha256()
        for o in range(0, len(pos_v), 24):
            h_re.update(pos_v[o : o + 24])
            h_re.update(vel_v[o : o + 24])
        if h_re.hexdigest() != h_block.hexdigest():
            raise SystemExit(f"{spec['key']}: re-interleaved pos+vel differs from the native int block")
        summary = []
        for sid in PRIMARY_SERIES:
            row = by_key[(sid, spec["key"])]
            values = array("q")
            values.frombytes(payloads[sid])
            lo, hi = min(values), max(values)
            if lo == hi or lo != row["min"] or hi != row["max"]:
                raise SystemExit(f"{row['sample_path']}: constant or min/max mismatch")
            if row.get("sample_shape") != [nsnap, N_BODIES, 3]:
                raise SystemExit(f"{row['sample_path']}: sample_shape mismatch")
            for c in range(27):
                col = values[c::27]
                if min(col) == max(col):
                    raise SystemExit(f"{row['sample_path']}: constant column {c}")
            digest = hashlib.sha256(payloads[sid]).hexdigest()
            if digest in seen_hashes[sid]:
                raise SystemExit(f"{row['sample_path']}: duplicate of another integration")
            seen_hashes[sid].add(digest)
            summary.append(f"{sid}=[{lo},{hi}]")
        print(f"verified {spec['key']} snapshots={nsnap} " + " ".join(summary), flush=True)
    declared = toml_series_totals(Path(args.manifest))
    if set(declared) != set(all_series):
        raise SystemExit(f"manifest series {sorted(declared)} != {sorted(all_series)}")
    for sid, (count, size, values) in totals.items():
        if declared.get(sid) != (count, size):
            raise SystemExit(f"manifest {sid} declares {declared.get(sid)} but realized {(count, size)}")
        print(f"verify summary series={sid} samples={count} bytes={size} values={values}")


def synth_file(nsnap: int, scale: float = 1e16, interval: float = 100.0, dt: float = 0.01) -> bytes:
    def field(ftype: int, payload: bytes) -> bytes:
        return struct.pack("<IIQ", ftype, 0, len(payload)) + payload

    banner = (BANNER_PREFIX + b"deadbeef").ljust(64, b"\x00")
    parts = [field(0, struct.pack("<d", 0.0)), field(1, struct.pack("<d", 1.0)), field(3, struct.pack("<d", dt)),
             field(4, struct.pack("<I", N_BODIES)), field(46, struct.pack("<q", SNAPSHOT_BYTES)),
             field(47, struct.pack("<d", interval)), field(51, struct.pack("<I", INTEGRATOR_JANUS)),
             field(108, struct.pack("<d", scale)), field(109, struct.pack("<I", 0))]
    particles = bytearray(N_BODIES * PARTICLE_STRUCT_BYTES)
    for i in range(N_BODIES):
        struct.pack_into("<d", particles, i * PARTICLE_STRUCT_BYTES + 72, 1.0 if i == 0 else 1e-6 * (i + 1))
    parts.append(field(85, bytes(particles)))
    pre = banner + b"".join(parts)
    hdr_len = len(pre) + 24 + 16
    pre += field(45, struct.pack("<q", hdr_len)) + field(FIELD_END, b"")
    assert len(pre) == hdr_len
    snaps = bytearray()
    for k in range(nsnap):
        snaps += struct.pack("<2d", interval * (k + 1) + 0.001 * (k % 3), 0.5 * (k + 1))
        for b in range(N_BODIES):
            r = 0.004 if b == 0 else 0.4 * b
            ang = 0.37 * k + b
            snaps += struct.pack("<6q", int(r * math.cos(ang) * scale), int(r * math.sin(ang) * scale),
                                 int(0.01 * r * math.sin(2 * ang) * scale), int(-0.2 * math.sin(ang) * scale),
                                 int(0.2 * math.cos(ang) * scale), int(-(k * 7919 + b) % 100003) * 1000)
    return pre + bytes(snaps)


def cmd_selftest(_args) -> None:
    nsnap = 2000
    blob = synth_file(nsnap)
    header, ints, times, walls = decode(blob)
    assert header["snapshot_count"] == nsnap and header["janus_scale"] == 1e16
    check_times(header, times, walls)
    parts = split_block(ints)
    for sid in PRIMARY_SERIES:
        assert int_stats(header, parts[sid], sid)["value_count"] == nsnap * 27
    pos, vel = array("q"), array("q")
    pos.frombytes(parts[POS_SERIES])
    vel.frombytes(parts[VEL_SERIES])
    # Spot-check every component of a few (snapshot, body) records against an
    # independent unpack at the known source offset.
    for k, b in ((0, 0), (1234, 5), (nsnap - 1, 8)):
        off = header["sa_size_first"] + k * SNAPSHOT_BYTES + 16 + b * 48
        src = struct.unpack_from("<6q", blob, off)
        assert tuple(pos[(k * 9 + b) * 3 : (k * 9 + b) * 3 + 3]) == src[:3]
        assert tuple(vel[(k * 9 + b) * 3 : (k * 9 + b) * 3 + 3]) == src[3:]
    for bad, why in ((blob + b"\x00" * 7, "trailing bytes"),
                     (blob.replace(b"Version: 3.2.2", b"Version: 9.9.9"), "banner"),
                     (blob[: header["sa_size_first"]] + blob[header["sa_size_first"] + 448 * 3 + 16:] + b"\x00" * 16, "misaligned")):
        try:
            h2, i2, t2, w2 = decode(bad)
            check_times(h2, t2, w2)
            p2 = split_block(i2)
            for sid in PRIMARY_SERIES:
                int_stats(h2, p2[sid], sid)
        except FormatError:
            continue
        raise SystemExit(f"selftest: {why} corruption not detected")
    print("selftest=ok")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("validate")
    p.add_argument("file")
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--data-root", required=True)
        p.add_argument("--files", required=True)
        if name == "verify":
            p.add_argument("--manifest", required=True)
    sub.add_parser("selftest")
    args = parser.parse_args()
    try:
        {"validate": cmd_validate, "build": cmd_build, "verify": cmd_verify, "selftest": cmd_selftest}[args.cmd](args)
    except FormatError as exc:
        raise SystemExit(f"FormatError: {exc}")


if __name__ == "__main__":
    main()
