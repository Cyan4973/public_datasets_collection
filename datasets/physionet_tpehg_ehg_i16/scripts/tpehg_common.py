"""Shared constants and WFDB header parsing for the TPEHG DB recipe.

Used by validate_download.py and tpehg_build.py. tpehg_verify.py deliberately
does not import this module so that verification re-derives everything with
its own parser and decoder.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path


DATASET_ID = "physionet_tpehg_ehg_i16"
NATURAL_RECORD_KIND = "complete_tpehg_recording_unfiltered_bipolar_channel"
SHA256SUMS_SHA256 = "6da37c0d996bf7706964f291282861449ccb84005500a1c16aefda3d8fcdbf3e"

EXPECTED_RECORDS = 300
EXPECTED_SHA256_ENTRIES = 606
EXPECTED_DAT_BYTES = 255_741_624
EXPECTED_HEA_BYTES = 302_194
EXPECTED_TOTAL_FRAMES = 10_655_901
EXPECTED_SAMPLES = 900
EXPECTED_PRIMARY_VALUES = 31_967_703
EXPECTED_PRIMARY_BYTES = 63_935_406

# The release holds two ADC code-lattice regimes of the same quantity, which
# coincide exactly with the header sampling-frequency string. Each regime is
# its own primary series, so no series mixes lattices.
#  - '20.000000' (174 records): full 16-bit codes, low 4 bits spread over all
#    16 residues (two most common residues hold <= 0.157 of values).
#  - '20.000110' (126 records): every value lies on two adjacent residues
#    mod 16, i.e. about 12-bit effective resolution scaled by 16.
SERIES_BY_FREQUENCY = {
    "20.000000": {
        "series_id": "tpehg_ehg_unfiltered_adc_step1_i16",
        "lattice": "step1",
        "records": 174,
        "values": 18_356_100,
    },
    "20.000110": {
        "series_id": "tpehg_ehg_unfiltered_adc_step16_i16",
        "lattice": "step16",
        "records": 126,
        "values": 13_611_603,
    },
}
MAX_STEP1_MOD16_TOP2_FRACTION = 0.5

SIGNAL_COUNT = 12
BYTES_PER_FRAME = SIGNAL_COUNT * 2
ALLOWED_FREQUENCIES = tuple(SERIES_BY_FREQUENCY)
SIGNAL_NAMES = (
    "1", "1_DOCFILT-4-0.08-4", "1_DOCFILT-4-0.3-3", "1_DOCFILT-4-0.3-4",
    "2", "2_DOCFILT-4-0.08-4", "2_DOCFILT-4-0.3-3", "2_DOCFILT-4-0.3-4",
    "3", "3_DOCFILT-4-0.08-4", "3_DOCFILT-4-0.3-3", "3_DOCFILT-4-0.3-4",
)
# Unfiltered bipolar channels kept as primary: signal index -> channel name.
PRIMARY_SIGNALS = {0: "1", 4: "2", 8: "3"}
BIPOLAR_LEADS = {"1": "S1=E2-E1", "2": "S2=E2-E3", "3": "S3=E4-E3"}

RECORD_PATTERN = re.compile(r"tpehgdb/(tpehg[0-9]{3,4})")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mod16_profile(values) -> tuple[int, bool, float]:
    """Return (distinct residues mod 16, residues adjacent, top-2 share)."""
    residues = Counter(value & 15 for value in values)
    keys = sorted(residues)
    adjacent = len(keys) == 1 or (len(keys) == 2 and (keys[1] - keys[0]) in (1, 15))
    top2 = round(sum(count for _, count in residues.most_common(2)) / len(values), 6)
    return len(keys), adjacent, top2


def lattice_ok(lattice: str, profile: tuple[int, bool, float]) -> bool:
    residue_count, adjacent, top2 = profile
    if lattice == "step1":
        return residue_count == 16 and top2 <= MAX_STEP1_MOD16_TOP2_FRACTION
    if lattice == "step16":
        return residue_count <= 2 and adjacent
    return False


def read_sha256sums(path: Path) -> dict[str, str]:
    sums: dict[str, str] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64}) +(\S+)", line.strip())
        if not match:
            raise ValueError(f"malformed SHA256SUMS line: {line!r}")
        if match.group(2) in sums:
            raise ValueError(f"duplicate SHA256SUMS entry: {match.group(2)}")
        sums[match.group(2)] = match.group(1)
    return sums


def read_records(path: Path) -> list[str]:
    """Return record ids (e.g. tpehg1007) in official RECORDS order."""
    ids = []
    for line in path.read_text(encoding="ascii").splitlines():
        if not line.strip():
            continue
        match = RECORD_PATTERN.fullmatch(line.strip())
        if not match:
            raise ValueError(f"unexpected RECORDS entry: {line!r}")
        ids.append(match.group(1))
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate RECORDS entries")
    return ids


def parse_header(path: Path, record_id: str) -> dict[str, object]:
    """Parse and validate one TPEHG WFDB header; comment lines are ignored."""
    text = path.read_text(encoding="ascii")
    lines = [line for line in text.splitlines() if line.strip() and not line.startswith("#")]
    if len(lines) != SIGNAL_COUNT + 1:
        raise ValueError(f"{record_id}: expected {SIGNAL_COUNT} signal lines")
    record_fields = lines[0].split()
    if len(record_fields) != 4 or record_fields[0] != record_id:
        raise ValueError(f"{record_id}: unexpected record line {lines[0]!r}")
    if int(record_fields[1]) != SIGNAL_COUNT:
        raise ValueError(f"{record_id}: signal count {record_fields[1]}")
    frequency = record_fields[2]
    if frequency not in ALLOWED_FREQUENCIES:
        raise ValueError(f"{record_id}: unexpected sampling frequency {frequency}")
    frames = int(record_fields[3])
    if frames <= 0:
        raise ValueError(f"{record_id}: non-positive frame count")
    signals = []
    for index, line in enumerate(lines[1:]):
        fields = line.split()
        if len(fields) != 9:
            raise ValueError(f"{record_id}: unexpected signal line {line!r}")
        filename, fmt, gain, resolution, zero, initial, checksum, block, name = fields
        if (
            filename != f"{record_id}.dat"
            or fmt != "16"
            or gain != "13107/mV"
            or resolution != "16"
            or zero != "0"
            or block != "0"
            or name != SIGNAL_NAMES[index]
        ):
            raise ValueError(f"{record_id}: signal {index} deviates from the TPEHG layout: {line!r}")
        signals.append({
            "index": index,
            "name": name,
            "initial_value": int(initial),
            "checksum": int(checksum),
        })
    return {
        "record_id": record_id,
        "frequency": frequency,
        "frames": frames,
        "signals": signals,
    }
