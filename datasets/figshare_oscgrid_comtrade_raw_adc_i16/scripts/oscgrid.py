#!/usr/bin/env python3
"""Build and verify OscGrid labeled raw COMTRADE int16 voltage/current oscillograms.

Input: the pinned figshare archive Labeled_raw_v1.1.7z (480 COMTRADE cfg/dat
pairs in one LZMA1 solid block). Output: per oscillogram, one channel-major
int16 sample of its standardized voltage channels and one of its standardized
current channels.

Pure standard library. The 7z container is decoded by sevenzip.py.
"""
from __future__ import annotations

import argparse
import array
import collections
import hashlib
import json
import math
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sevenzip  # noqa: E402

DATASET_ID = "figshare_oscgrid_comtrade_raw_adc_i16"
ARCHIVE_NAME = "Labeled_raw_v1.1.7z"
ARCHIVE_SIZE = 94_882_365
MEMBER_PREFIX = "Labeled_raw_v1.1/"
EXPECTED_PAIRS = 480
EXPECTED_FOLDER_UNPACK = 585_730_365
SAMPLE_RATE_HZ = 1600.0
LINE_FREQUENCY_HZ = 50.0
TIMESTAMP_STEP_US = 625  # 1e6 / 1600
INT_TOLERANCE = 1e-6
INT16_MIN = -32768
INT16_MAX = 32767
ALLOWED_CODE_MIN = {-32768, -32767}
ALLOWED_CODE_MAX = {32767}
MAX_DROPPED_RECORDS = 48  # 10% of the 480 labeled oscillograms
MIN_MEDIAN_VALUES = 1000  # repository median-sample floor

SERIES_VOLTAGE = "oscgrid_voltage_codes_i16"
SERIES_CURRENT = "oscgrid_current_codes_i16"
SERIES_ORDER = (SERIES_VOLTAGE, SERIES_CURRENT)

# Standardized OscGrid analog names (AIRI-Institute/oscgrid dict_analog_names.json).
VOLTAGE_NAME = re.compile(r"^U \| (BusBar|CableLine)-(\d+) \| phase: (A|B|C|N|AB|BC|CA)$")
CURRENT_NAME = re.compile(r"^I \| Bus-(\d+) \| phase: (A|B|C|N)$")
# Unit spellings seen in the cfgs; Cyrillic A (U+0410) / Ve (U+0412) occur.
VOLTAGE_UNITS = {"V": "V", "В": "V"}
CURRENT_UNITS = {"A": "A", "А": "A"}
# Code-scaling homogeneity: keep only channels on the terminals' standard
# VT input (a about 0.016 V/code, ~ +/-540 V secondary full scale) and standard
# CT input (a about 0.0092 A/code, ~ +/-300 A full scale), each +/-15%.
# Other input ranges (sensitive earth-fault inputs, other terminal types) are
# different code regimes and are excluded and counted.
VOLTAGE_A_BAND = (0.016 * 0.85, 0.016 * 1.15)
CURRENT_A_BAND = (0.0092 * 0.85, 0.0092 * 1.15)


class Reject(Exception):
    """A record fails a declared filter; the whole oscillogram is dropped."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


@dataclass
class AnalogChannel:
    index: int
    name: str
    phase: str
    ccbm: str
    unit: str
    a: float
    b: float
    skew: float
    code_min: int
    code_max: int
    primary: float
    secondary: float
    ps: str
    series: str | None = None
    unit_norm: str | None = None
    exclusion: str | None = None


@dataclass
class Cfg:
    rev: str
    total: int
    analog: list[AnalogChannel]
    digital_names: list[str]
    line_freq: float
    rates: list[tuple[float, int]]
    file_type: str
    timemult: float

    @property
    def n_analog(self) -> int:
        return len(self.analog)

    @property
    def end_sample(self) -> int:
        return self.rates[0][1]


def _num(text: str, what: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise Reject("cfg_malformed", f"{what}={text!r}") from None
    if not math.isfinite(value):
        raise Reject("cfg_malformed", f"{what}={text!r}")
    return value


def _int(text: str, what: str) -> int:
    value = _num(text, what)
    if value != int(value):
        raise Reject("cfg_malformed", f"{what}={text!r}")
    return int(value)


def parse_cfg(raw: bytes) -> Cfg:
    """Parse a COMTRADE cfg; raise Reject for anything outside the declared scope."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise Reject("cfg_not_utf8") from None
    text = text.lstrip("﻿")
    lines = [line.rstrip("\r") for line in text.split("\n")]
    while lines and not lines[-1].strip():
        lines.pop()

    def fields(i: int) -> list[str]:
        if i >= len(lines):
            raise Reject("cfg_truncated", f"line {i + 1}")
        return [part.strip() for part in lines[i].split(",")]

    head = fields(0)
    rev = head[2] if len(head) >= 3 else ""
    if rev != "1999":
        raise Reject("cfg_rev_not_1999", rev or "missing")
    counts = fields(1)
    if len(counts) != 3 or not counts[1].endswith("A") or not counts[2].endswith("D"):
        raise Reject("cfg_malformed", f"channel counts {lines[1]!r}")
    total = _int(counts[0], "TT")
    n_analog = _int(counts[1][:-1], "##A")
    n_digital = _int(counts[2][:-1], "##D")
    if total != n_analog + n_digital or n_analog < 1:
        raise Reject("cfg_malformed", f"channel counts {lines[1]!r}")
    analog: list[AnalogChannel] = []
    for k in range(n_analog):
        f = fields(2 + k)
        if len(f) != 13:
            raise Reject("cfg_malformed", f"analog line {k + 1} has {len(f)} fields")
        channel = AnalogChannel(
            index=_int(f[0], "An"),
            name=f[1],
            phase=f[2],
            ccbm=f[3],
            unit=f[4],
            a=_num(f[5], "a"),
            b=_num(f[6], "b"),
            skew=_num(f[7], "skew"),
            code_min=_int(f[8], "min"),
            code_max=_int(f[9], "max"),
            primary=_num(f[10], "primary"),
            secondary=_num(f[11], "secondary"),
            ps=f[12].upper(),
        )
        if channel.index != k + 1:
            raise Reject("cfg_malformed", f"analog index {channel.index} at position {k + 1}")
        analog.append(channel)
    digital_names: list[str] = []
    for k in range(n_digital):
        f = fields(2 + n_analog + k)
        if len(f) < 3:
            raise Reject("cfg_malformed", f"digital line {k + 1}")
        digital_names.append(f[1])
    pos = 2 + n_analog + n_digital
    line_freq = _num(fields(pos)[0], "lf")
    nrates = _int(fields(pos + 1)[0], "nrates")
    if nrates < 1:
        raise Reject("cfg_nrates_not_1", str(nrates))
    rates = []
    for k in range(nrates):
        f = fields(pos + 2 + k)
        if len(f) != 2:
            raise Reject("cfg_malformed", f"rate line {lines[pos + 2 + k]!r}")
        rates.append((_num(f[0], "samp"), _int(f[1], "endsamp")))
    pos += 2 + nrates
    fields(pos)  # start date/time
    fields(pos + 1)  # trigger date/time
    file_type = fields(pos + 2)[0].upper()
    timemult = _num(fields(pos + 3)[0], "timemult")
    return Cfg(rev, total, analog, digital_names, line_freq, rates, file_type, timemult)


def check_scope(cfg: Cfg) -> None:
    if cfg.file_type != "ASCII":
        raise Reject("cfg_file_type_not_ascii", cfg.file_type)
    if cfg.line_freq != LINE_FREQUENCY_HZ:
        raise Reject("cfg_line_frequency_not_50", str(cfg.line_freq))
    if len(cfg.rates) != 1:
        raise Reject("cfg_nrates_not_1", str(len(cfg.rates)))
    if cfg.rates[0][0] != SAMPLE_RATE_HZ:
        raise Reject("cfg_sample_rate_not_1600", str(cfg.rates[0][0]))
    if cfg.end_sample < 1:
        raise Reject("cfg_malformed", "endsamp < 1")
    if cfg.timemult != 1.0:
        raise Reject("cfg_timemult_not_1", str(cfg.timemult))
    for ch in cfg.analog:
        if ch.code_min not in ALLOWED_CODE_MIN or ch.code_max not in ALLOWED_CODE_MAX:
            raise Reject("cfg_code_range_not_int16", f"{ch.name}: {ch.code_min}..{ch.code_max}")


def classify_channels(cfg: Cfg) -> None:
    """Assign each analog channel to a primary series or record why it is excluded."""
    for ch in cfg.analog:
        if VOLTAGE_NAME.match(ch.name):
            unit = VOLTAGE_UNITS.get(ch.unit)
            if unit is None:
                ch.exclusion = f"voltage_name_unit_{ch.unit or 'blank'}"
            elif not VOLTAGE_A_BAND[0] <= ch.a <= VOLTAGE_A_BAND[1]:
                ch.exclusion = "voltage_scale_outside_standard_vt_input_band"
            else:
                ch.series, ch.unit_norm = SERIES_VOLTAGE, unit
        elif CURRENT_NAME.match(ch.name):
            unit = CURRENT_UNITS.get(ch.unit)
            if unit is None:
                ch.exclusion = f"current_name_unit_{ch.unit or 'blank'}"
            elif not CURRENT_A_BAND[0] <= ch.a <= CURRENT_A_BAND[1]:
                ch.exclusion = "current_scale_outside_standard_ct_input_band"
            else:
                ch.series, ch.unit_norm = SERIES_CURRENT, unit
        elif ch.name.startswith(("U_raw |", "I_raw |")):
            ch.exclusion = "nontraditional_sensor_raw_suffix"
        elif ch.name.startswith(("I | dif-", "I | braking-")):
            ch.exclusion = "relay_computed_differential_or_braking"
        elif "ML" in ch.name:
            ch.exclusion = "ml_label_signal_in_analog_section"
        else:
            ch.exclusion = "nonstandard_analog_name"


def parse_dat_rowmajor(raw: bytes, cfg: Cfg) -> tuple[array.array, dict]:
    """Return analog codes as a row-major int16 array (rows x n_analog) plus stats."""
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        raise Reject("dat_not_ascii") from None
    lines = text.split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    n_rows = cfg.end_sample
    if len(lines) != n_rows:
        raise Reject("dat_row_count_mismatch", f"{len(lines)} rows, cfg endsamp {n_rows}")
    n_analog = cfg.n_analog
    n_fields = 2 + n_analog + len(cfg.digital_names)
    flat = array.array("h")
    artifacts = 0
    max_dev = 0.0
    ts_offgrid = 0
    for row_number, line in enumerate(lines, 1):
        parts = line.rstrip("\r").split(",")
        if len(parts) != n_fields:
            raise Reject("dat_field_count_mismatch", f"row {row_number}: {len(parts)} != {n_fields}")
        try:
            if int(parts[0]) != row_number:
                raise Reject("dat_sample_number_mismatch", f"row {row_number}: {parts[0]!r}")
        except ValueError:
            raise Reject("dat_sample_number_mismatch", f"row {row_number}: {parts[0]!r}") from None
        try:
            if int(parts[1]) != (row_number - 1) * TIMESTAMP_STEP_US:
                ts_offgrid += 1
        except ValueError:
            ts_offgrid += 1
        tokens = parts[2 : 2 + n_analog]
        try:
            values = list(map(int, tokens))
        except ValueError:
            values = []
            for token in tokens:
                try:
                    values.append(int(token))
                    continue
                except ValueError:
                    pass
                try:
                    real = float(token)
                except ValueError:
                    raise Reject("dat_analog_not_numeric", f"row {row_number}: {token!r}") from None
                if not math.isfinite(real):
                    raise Reject("dat_analog_not_finite", f"row {row_number}: {token!r}")
                code = round(real)
                deviation = abs(real - code)
                if deviation >= INT_TOLERANCE:
                    raise Reject("dat_analog_not_integral", f"row {row_number}: {token!r}")
                max_dev = max(max_dev, deviation)
                artifacts += 1
                values.append(code)
        try:
            flat.extend(values)
        except OverflowError:
            raise Reject("dat_analog_outside_int16", f"row {row_number}") from None
    if ts_offgrid:
        raise Reject("dat_timestamp_off_1600hz_grid", f"{ts_offgrid} rows")
    for j, ch in enumerate(cfg.analog):
        column = flat[j::n_analog]
        low, high = min(column), max(column)
        if low < ch.code_min or high > ch.code_max:
            raise Reject("dat_analog_outside_cfg_range", f"{ch.name}: {low}..{high}")
    return flat, {"float_artifact_tokens": artifacts, "max_integral_deviation": max_dev}


def channel_major(flat: array.array, n_analog: int, indices: list[int]) -> array.array:
    out = array.array("h")
    for j in indices:
        out.extend(flat[j::n_analog])
    return out


def to_le_bytes(values: array.array) -> bytes:
    if sys.byteorder != "little":
        values = array.array("h", values)
        values.byteswap()
    return values.tobytes()


@dataclass
class RecordPlan:
    stem: str
    cfg: Cfg | None = None
    reject: Reject | None = None
    cfg_crc: int | None = None
    dat_crc: int | None = None
    dat_size: int = 0


@dataclass
class Census:
    reasons: collections.Counter = field(default_factory=collections.Counter)
    exclusions: collections.Counter = field(default_factory=collections.Counter)
    excluded_names: collections.Counter = field(default_factory=collections.Counter)
    units: collections.Counter = field(default_factory=collections.Counter)


def scan_archive(archive_path: Path) -> tuple[sevenzip.Archive, sevenzip.Reader, dict[str, RecordPlan]]:
    read, size = sevenzip.file_reader(str(archive_path))
    if size != ARCHIVE_SIZE:
        raise SystemExit(f"archive size {size} != pinned {ARCHIVE_SIZE}")
    archive = sevenzip.open_archive(read, size)
    folders = archive.streams.folders
    if len(folders) != 1 or folders[0].unpack_size != EXPECTED_FOLDER_UNPACK:
        raise SystemExit("unexpected 7z folder layout")
    plans: dict[str, RecordPlan] = {}
    for entry in archive.entries:
        if not entry.has_stream:
            continue
        if not entry.name.startswith(MEMBER_PREFIX) or "/" in entry.name[len(MEMBER_PREFIX) :]:
            raise SystemExit(f"unexpected member path {entry.name!r}")
        stem, _, ext = entry.name[len(MEMBER_PREFIX) :].rpartition(".")
        if ext not in ("cfg", "dat") or not re.fullmatch(r"[0-9a-f]{32}", stem):
            raise SystemExit(f"unexpected member name {entry.name!r}")
        plan = plans.setdefault(stem, RecordPlan(stem))
        if ext == "cfg":
            if plan.cfg_crc is not None:
                raise SystemExit(f"duplicate cfg {stem}")
            plan.cfg_crc = entry.crc
        else:
            if plan.dat_crc is not None:
                raise SystemExit(f"duplicate dat {stem}")
            plan.dat_crc = entry.crc
            plan.dat_size = entry.size
    unpaired = [s for s, p in plans.items() if p.cfg_crc is None or p.dat_crc is None]
    if unpaired or len(plans) != EXPECTED_PAIRS:
        raise SystemExit(f"expected {EXPECTED_PAIRS} cfg/dat pairs, got {len(plans)} ({len(unpaired)} unpaired)")
    return archive, read, plans


def collect_cfgs(archive: sevenzip.Archive, read: sevenzip.Reader, plans: dict[str, RecordPlan]) -> int:
    """Pass 1: decode the solid block, CRC-check every member, parse every cfg."""
    members = 0
    for entry, content in sevenzip.iter_members(read, archive):
        members += 1
        if entry.name.endswith(".cfg"):
            plan = plans[entry.name[len(MEMBER_PREFIX) : -4]]
            try:
                cfg = parse_cfg(content)
                check_scope(cfg)
                classify_channels(cfg)
                plan.cfg = cfg
            except Reject as exc:
                plan.reject = exc
    return members


def iter_dats(archive: sevenzip.Archive, read: sevenzip.Reader, plans: dict[str, RecordPlan]):
    """Pass 2: decode the solid block again and yield (plan, dat bytes) for in-scope records."""
    for entry, content in sevenzip.iter_members(read, archive):
        if entry.name.endswith(".dat"):
            plan = plans[entry.name[len(MEMBER_PREFIX) : -4]]
            if plan.reject is None:
                yield plan, content


def record_outputs(plan: RecordPlan, flat: array.array) -> dict[str, tuple[list[AnalogChannel], array.array]]:
    cfg = plan.cfg
    assert cfg is not None
    outputs = {}
    for series in SERIES_ORDER:
        channels = [ch for ch in cfg.analog if ch.series == series]
        if channels:
            outputs[series] = (channels, channel_major(flat, cfg.n_analog, [ch.index - 1 for ch in channels]))
    return outputs


def channel_meta(ch: AnalogChannel) -> dict:
    return {
        "cfg_index": ch.index,
        "name": ch.name,
        "unit": ch.unit_norm,
        "unit_raw": ch.unit,
        "a": ch.a,
        "b": ch.b,
        "skew": ch.skew,
        "code_min": ch.code_min,
        "code_max": ch.code_max,
        "primary": ch.primary,
        "secondary": ch.secondary,
        "ps": ch.ps,
    }


def build(args: argparse.Namespace) -> None:
    data_root = Path(args.data_root)
    samples_dir = Path(args.samples_dir)
    index_path = Path(args.index)
    stats_path = Path(args.stats)
    for series in SERIES_ORDER:
        target = samples_dir / series
        target.mkdir(parents=True, exist_ok=True)
        for stale in target.glob("*.bin"):
            stale.unlink()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    archive, read, plans = scan_archive(Path(args.archive))
    members = collect_cfgs(archive, read, plans)
    print(f"pass1 members={members} records={len(plans)}", flush=True)

    census = Census()
    rows: dict[str, list[dict]] = {series: [] for series in SERIES_ORDER}
    seen_digest: dict[str, str] = {}
    skipped_constant: list[dict] = []
    skipped_duplicate: list[dict] = []
    artifacts_total = 0
    max_dev_total = 0.0
    constant_channels = 0
    kept_records: set[str] = set()
    done = 0
    for plan, content in iter_dats(archive, read, plans):
        cfg = plan.cfg
        assert cfg is not None
        try:
            flat, dat_stats = parse_dat_rowmajor(content, cfg)
        except Reject as exc:
            plan.reject = exc
            continue
        artifacts_total += dat_stats["float_artifact_tokens"]
        max_dev_total = max(max_dev_total, dat_stats["max_integral_deviation"])
        for series, (channels, values) in record_outputs(plan, flat).items():
            n = cfg.end_sample
            for k in range(len(channels)):
                segment = values[k * n : (k + 1) * n]
                if min(segment) == max(segment):
                    constant_channels += 1
            if min(values) == max(values):
                skipped_constant.append({"record": plan.stem, "series": series})
                continue
            payload = to_le_bytes(values)
            digest = hashlib.sha256(payload).hexdigest()
            if digest in seen_digest:
                skipped_duplicate.append({"record": plan.stem, "series": series, "duplicate_of": seen_digest[digest]})
                continue
            seen_digest[digest] = plan.stem
            out_path = samples_dir / series / f"{plan.stem}.bin"
            out_path.write_bytes(payload)
            kept_records.add(plan.stem)
            rows[series].append(
                {
                    "dataset_id": DATASET_ID,
                    "series_id": series,
                    "sample_path": str(out_path.relative_to(data_root)),
                    "numeric_kind": "int",
                    "bit_width": 16,
                    "endianness": "little",
                    "element_size_bytes": 2,
                    "sample_size_bytes": len(payload),
                    "value_count": len(values),
                    "shape": [len(channels), cfg.end_sample],
                    "axes": ["analog_channel", "time_sample_1600hz"],
                    "record": plan.stem,
                    "source_cfg": f"{MEMBER_PREFIX}{plan.stem}.cfg",
                    "source_dat": f"{MEMBER_PREFIX}{plan.stem}.dat",
                    "source_dat_crc32": f"{plan.dat_crc:08x}",
                    "sample_rate_hz": SAMPLE_RATE_HZ,
                    "line_frequency_hz": cfg.line_freq,
                    "min": min(values),
                    "max": max(values),
                    "sha256": digest,
                    "channels": [channel_meta(ch) for ch in channels],
                }
            )
        done += 1
        if done % 50 == 0:
            print(f"pass2 parsed={done}", flush=True)

    for plan in plans.values():
        if plan.reject is not None:
            census.reasons[plan.reject.reason] += 1
        elif plan.cfg is not None:
            for ch in plan.cfg.analog:
                if ch.series:
                    census.units[f"{ch.series}:{ch.unit}"] += 1
                else:
                    census.exclusions[ch.exclusion] += 1
                    census.excluded_names[re.sub(r"\d+", "#", ch.name)] += 1
    dropped = sorted(
        ({"record": p.stem, "reason": p.reject.reason, "detail": p.reject.detail} for p in plans.values() if p.reject),
        key=lambda item: item["record"],
    )
    if len(dropped) > MAX_DROPPED_RECORDS:
        raise SystemExit(f"{len(dropped)} records dropped (> {MAX_DROPPED_RECORDS}): {dict(census.reasons)}")

    with index_path.open("w", encoding="utf-8") as handle:
        for series in SERIES_ORDER:
            for row in sorted(rows[series], key=lambda r: r["record"]):
                handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    parsed = [p for p in plans.values() if p.reject is None]
    series_stats = {}
    for series in SERIES_ORDER:
        values = [r["value_count"] for r in rows[series]]
        values.sort()
        emitted_channels = [c for r in rows[series] for c in r["channels"]]
        series_stats[series] = {
            "samples": len(values),
            "values": sum(values),
            "bytes": 2 * sum(values),
            "channels": len(emitted_channels),
            "median_values": values[len(values) // 2] if values else 0,
            "min_values": values[0] if values else 0,
            "max_values": values[-1] if values else 0,
            "min_code": min((r["min"] for r in rows[series]), default=None),
            "max_code": max((r["max"] for r in rows[series]), default=None),
            "low_amplitude_samples_peak_below_64_codes": sum(
                1 for r in rows[series] if max(abs(r["min"]), abs(r["max"])) < 64
            ),
            "full_scale_samples": sum(1 for r in rows[series] if r["min"] <= -32767 or r["max"] >= 32767),
            "scale_a_min": min((c["a"] for c in emitted_channels), default=None),
            "scale_a_max": max((c["a"] for c in emitted_channels), default=None),
            "ps_flags": dict(collections.Counter(c["ps"] for c in emitted_channels)),
            "units": dict(collections.Counter(c["unit"] for c in emitted_channels)),
            "channel_name_patterns": dict(
                sorted(collections.Counter(re.sub(r"\d+", "#", c["name"]) for c in emitted_channels).items())
            ),
        }
    stats = {
        "dataset_id": DATASET_ID,
        "archive": ARCHIVE_NAME,
        "records_in_archive": len(plans),
        "records_parsed": len(parsed),
        "records_dropped": len(dropped),
        "drop_reasons": dict(sorted(census.reasons.items())),
        "dropped": dropped,
        "records_emitted": len(kept_records),
        "records_without_voltage": sum(1 for p in parsed if not any(c.series == SERIES_VOLTAGE for c in p.cfg.analog)),
        "records_without_current": sum(1 for p in parsed if not any(c.series == SERIES_CURRENT for c in p.cfg.analog)),
        "excluded_channel_reasons": dict(sorted(census.exclusions.items())),
        "excluded_channel_name_patterns": dict(sorted(census.excluded_names.items())),
        "kept_channel_units": dict(sorted(census.units.items())),
        "constant_channels_kept": constant_channels,
        "skipped_constant_samples": skipped_constant,
        "skipped_duplicate_samples": skipped_duplicate,
        "float_artifact_tokens": artifacts_total,
        "max_integral_deviation": max_dev_total,
        "series": series_stats,
    }
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in stats.items() if k not in ("dropped",)}, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------- verify


class VerifyReject(Exception):
    pass


def verify_parse_dat(raw: bytes, cfg: Cfg) -> list[list[int]]:
    """Independent re-parse of every analog column via float(), with the same
    record-level rules as build: exact row count, sample numbers 1..N,
    timestamps on the 625 us grid, integral codes within the cfg min/max."""
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        raise VerifyReject("dat_not_ascii") from None
    n_analog = cfg.n_analog
    n_fields = 2 + n_analog + len(cfg.digital_names)
    lows = [ch.code_min for ch in cfg.analog]
    highs = [ch.code_max for ch in cfg.analog]
    columns: list[list[int]] = [[] for _ in range(n_analog)]
    count = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        count += 1
        cells = line.split(",")
        if len(cells) != n_fields:
            raise VerifyReject(f"field count {len(cells)} != {n_fields} at row {count}")
        try:
            if int(cells[0]) != count or int(cells[1]) != (count - 1) * TIMESTAMP_STEP_US:
                raise VerifyReject(f"sample number/timestamp off grid at row {count}")
            reals = [float(cell) for cell in cells[2 : 2 + n_analog]]
        except ValueError:
            raise VerifyReject(f"non-numeric cell at row {count}") from None
        for j, real in enumerate(reals):
            if not math.isfinite(real):
                raise VerifyReject(f"non-finite analog value at row {count}")
            code = int(math.floor(real + 0.5))
            if abs(real - code) >= INT_TOLERANCE:
                raise VerifyReject(f"non-integral analog value {cells[2 + j]!r}")
            if not (lows[j] <= code <= highs[j] and INT16_MIN <= code <= INT16_MAX):
                raise VerifyReject(f"analog value {code} outside cfg range")
            columns[j].append(code)
    if count != cfg.end_sample:
        raise VerifyReject(f"{count} rows != endsamp {cfg.end_sample}")
    return columns


def verify(args: argparse.Namespace) -> None:
    data_root = Path(args.data_root)
    samples_dir = Path(args.samples_dir)
    index_rows = [json.loads(line) for line in Path(args.index).read_text(encoding="utf-8").splitlines() if line.strip()]
    stats = json.loads(Path(args.stats).read_text(encoding="utf-8"))
    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    by_key = {(row["series_id"], row["record"]): row for row in index_rows}
    if len(by_key) != len(index_rows):
        raise SystemExit("verify: duplicate (series, record) index rows")
    on_disk = {
        (series, path.stem) for series in SERIES_ORDER for path in (samples_dir / series).glob("*.bin")
    }
    if on_disk != set(by_key):
        raise SystemExit(f"verify: sample files and index rows differ ({len(on_disk)} vs {len(by_key)})")

    archive, read, plans = scan_archive(Path(args.archive))
    collect_cfgs(archive, read, plans)
    rederived_drops = {s for s, p in plans.items() if p.reject is not None}
    stats_drops = {item["record"] for item in stats["dropped"]}

    checked: set[tuple[str, str]] = set()
    digests: dict[str, tuple[str, str]] = {}
    for plan, content in iter_dats(archive, read, plans):
        cfg = plan.cfg
        assert cfg is not None
        try:
            columns = verify_parse_dat(content, cfg)
        except VerifyReject:
            rederived_drops.add(plan.stem)
            if any((s, plan.stem) in by_key for s in SERIES_ORDER):
                raise SystemExit(f"verify: record {plan.stem} fails the record rules but has samples") from None
            continue
        for series in SERIES_ORDER:
            keep = [ch.index - 1 for ch in cfg.analog if ch.series == series]
            key = (series, plan.stem)
            if not keep:
                if key in by_key:
                    raise SystemExit(f"verify: {key} has a sample but no channels")
                continue
            expected = array.array("h")
            for j in keep:
                expected.extend(columns[j])
            if min(expected) == max(expected):
                if key in by_key:
                    raise SystemExit(f"verify: constant sample emitted for {key}")
                continue
            payload = to_le_bytes(expected)
            digest = hashlib.sha256(payload).hexdigest()
            if digest in digests and key not in by_key:
                continue  # duplicate payload skipped by build
            row = by_key.get(key)
            if row is None:
                raise SystemExit(f"verify: missing sample for {key}")
            path = data_root / row["sample_path"]
            actual = path.read_bytes()
            if actual != payload:
                raise SystemExit(f"verify: sample bytes differ for {key}")
            if (
                row["sha256"] != digest
                or row["value_count"] != len(expected)
                or row["sample_size_bytes"] != len(actual)
                or row["shape"] != [len(keep), cfg.end_sample]
                or row["min"] != min(expected)
                or row["max"] != max(expected)
                or [c["cfg_index"] for c in row["channels"]] != [j + 1 for j in keep]
            ):
                raise SystemExit(f"verify: index metadata mismatch for {key}")
            if digest in digests:
                raise SystemExit(f"verify: duplicate payload {key} == {digests[digest]}")
            digests[digest] = key
            checked.add(key)
    if checked != set(by_key):
        raise SystemExit(f"verify: {len(set(by_key) - checked)} index rows were not re-derived")
    if rederived_drops != stats_drops:
        raise SystemExit(
            f"verify: re-derived drop set ({len(rederived_drops)}) != build drop set ({len(stats_drops)})"
        )
    if len(rederived_drops) > MAX_DROPPED_RECORDS:
        raise SystemExit(f"verify: {len(rederived_drops)} dropped records exceed {MAX_DROPPED_RECORDS}")

    totals = collections.defaultdict(lambda: [0, 0])
    for row in index_rows:
        totals[row["series_id"]][0] += 1
        totals[row["series_id"]][1] += row["sample_size_bytes"]
        if row["numeric_kind"] != "int" or row["bit_width"] != 16 or row["endianness"] != "little":
            raise SystemExit("verify: index dtype fields wrong")
    for series in manifest["series"]:
        sid = series["id"]
        if [series["sample_count"], series["total_size_bytes"]] != totals.get(sid, [0, 0]):
            raise SystemExit(
                f"verify: manifest {sid} declares {series['sample_count']} samples / {series['total_size_bytes']} B, "
                f"realized {totals.get(sid, [0, 0])}"
            )
    for series in SERIES_ORDER:
        counts = sorted(r["value_count"] for r in index_rows if r["series_id"] == series)
        if not counts or counts[len(counts) // 2] < MIN_MEDIAN_VALUES:
            raise SystemExit(f"verify: {series} median sample below {MIN_MEDIAN_VALUES} values")
    summary = {sid: {"samples": v[0], "bytes": v[1]} for sid, v in sorted(totals.items())}
    print(json.dumps({"verify": "ok", "rederived_samples": len(checked), "series": summary}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "verify"])
    parser.add_argument("--archive", required=True)
    parser.add_argument("--samples-dir", required=True)
    parser.add_argument("--index", required=True)
    parser.add_argument("--stats", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--manifest")
    args = parser.parse_args()
    if args.command == "build":
        build(args)
    else:
        if not args.manifest:
            parser.error("verify needs --manifest")
        verify(args)


if __name__ == "__main__":
    main()
