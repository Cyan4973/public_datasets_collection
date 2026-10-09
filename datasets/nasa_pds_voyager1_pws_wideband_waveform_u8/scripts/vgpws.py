"""Shared Voyager 1 PWS waveform frame decoding for download checks and build.

verify.py deliberately does not import this module.

Frame layout (VGPW_1001 Cmmmmmnn.DAT, PDS3 detached label):
  record 1            engineering header; ASCII "VOYAGER-1 PWS  p/mmmmm:nn <SCET>" at byte 249 (1-based)
  records 2..N        1024 bytes = 220-byte WF_ROW_PREFIX (FDS_LINE_COUNT MSB u16 at bytes 23-24)
                      + 800 waveform bytes (bytes 221-1020) holding 1600 4-bit samples, high nibble first
                      + 4 spare bytes

Line rule (shared with verify.py, re-implemented there):
  * FDS_LINE_COUNT outside 1..800, or not greater than the last in-order line count -> drop (bad_line)
  * all 800 waveform bytes zero -> drop (zero_fill: missing line filled by the archive)
  * waveform bytes identical to the last kept line -> drop (repeat: after 1992-11-03
    only one line in five is returned and the archive repeats it five times)
  * otherwise keep; emit samples 17..1600 (bytes 229-1020). The first 16 samples (8 bytes) of each line
    are dropped on every line because DATASET.CAT says they are usually invalid during the Jupiter
    encounter and recommends skipping them; applying it everywhere keeps a fixed 1584-sample line.
Frame rule: emitted only if kept_lines >= 50, >= 6 distinct codes, and the most common code <= 80%.
"""
from __future__ import annotations

import re

DATASET_ID = "nasa_pds_voyager1_pws_wideband_waveform_u8"
SERIES_ID = "vg1_pws_wideband_4bit_code_u8"
DATA_SET_ID = "VG1-J/S/SS-PWS-1-EDR-WFRM-60MS-V1.0"
RECORD_BYTES = 1024
WF_START = 220          # 0-based start of the 800 waveform bytes
WF_BYTES = 800
SKIP_BYTES = 8          # first 16 samples of each line
SAMPLES_PER_LINE = 2 * (WF_BYTES - SKIP_BYTES)
MIN_KEPT_LINES = 50
MIN_DISTINCT = 6
MAX_MODE_FRACTION = 0.80

HI = bytes(b >> 4 for b in range(256))
LO = bytes(b & 0x0F for b in range(256))


def label_kv(text: str) -> dict[str, str]:
    kv: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("/*"):
            k, v = line.split("=", 1)
            k = k.strip()
            if k and k not in kv:
                kv[k] = v.strip()
    return kv


def check_label(text: str, product_id: str, dat_size: int, start_time: str) -> dict:
    kv = label_kv(text)
    want = {
        "RECORD_TYPE": "FIXED_LENGTH",
        "RECORD_BYTES": "1024",
        "DATA_SET_ID": f'"{DATA_SET_ID}"',
        "INSTRUMENT_HOST_ID": "VG1",
        "PRODUCT_ID": f'"{product_id}"',
        "START_TIME": start_time,
        "INSTRUMENT_ID": "PWS",
        "SECTION_ID": "WFRM",
        "START_BYTE": "221",
        "START_BIT": "1",
        "ITEM_BITS": "4",
        "OFFSET": "-7.5",
        "VALID_MINIMUM": "0",
        "VALID_MAXIMUM": "15",
        "SAMPLING_PARAMETER_INTERVAL": "0.06",
    }
    for k, v in want.items():
        if kv.get(k) != v:
            raise SystemExit(f"{product_id}: label {k}={kv.get(k)!r}, expected {v!r}")
    if not re.search(r"BIT_DATA_TYPE\s*=\s*UNSIGNED_INTEGER", text):
        raise SystemExit(f"{product_id}: label lacks BIT_DATA_TYPE UNSIGNED_INTEGER")
    if not re.search(r"SAMPLING_PARAMETER_INTERVAL\s*=\s*0\.00003472222", text):
        raise SystemExit(f"{product_id}: label lacks 28.8 kHz sample interval")
    file_records = int(kv["FILE_RECORDS"])
    if file_records * RECORD_BYTES != dat_size:
        raise SystemExit(f"{product_id}: FILE_RECORDS {file_records} * 1024 != DAT size {dat_size}")
    return {"file_records": file_records, "data_lines": int(kv.get("DATA_LINES", "-1")),
            "mission_phase": kv.get("MISSION_PHASE_NAME", "").strip('"')}


def header_label(data: bytes) -> str:
    return data[248:300].split(b"\0", 1)[0].decode("ascii", "replace").strip()


def unpack(chunk: bytes) -> bytes:
    out = bytearray(2 * len(chunk))
    out[0::2] = chunk.translate(HI)
    out[1::2] = chunk.translate(LO)
    return bytes(out)


def extract(data: bytes) -> tuple[bytes, dict]:
    if len(data) % RECORD_BYTES or len(data) < 2 * RECORD_BYTES:
        raise SystemExit(f"DAT size {len(data)} is not >= 2 records of 1024 bytes")
    if not header_label(data).startswith("VOYAGER-1 PWS"):
        raise SystemExit(f"header ASCII label {header_label(data)!r} is not Voyager 1 PWS")
    mv = memoryview(data)
    parts = []
    stats = {"data_records": 0, "kept_lines": 0, "bad_line": 0, "zero_fill": 0, "repeat": 0}
    prev_line = 0
    prev_wf = None
    for off in range(RECORD_BYTES, len(data), RECORD_BYTES):
        stats["data_records"] += 1
        line = (data[off + 22] << 8) | data[off + 23]
        if line < 1 or line > 800 or line <= prev_line:
            stats["bad_line"] += 1
            continue
        prev_line = line
        wf = bytes(mv[off + WF_START:off + WF_START + WF_BYTES])
        if not any(wf):
            stats["zero_fill"] += 1
            continue
        if wf == prev_wf:
            stats["repeat"] += 1
            continue
        prev_wf = wf
        stats["kept_lines"] += 1
        parts.append(wf[SKIP_BYTES:])
    return unpack(b"".join(parts)), stats


def frame_rule(payload: bytes, kept_lines: int) -> str:
    """Return '' if the frame is emitted, else the exclusion reason."""
    if kept_lines < MIN_KEPT_LINES:
        return f"kept_lines {kept_lines} < {MIN_KEPT_LINES}"
    counts = [payload.count(bytes([c])) for c in range(16)]
    distinct = sum(1 for c in counts if c)
    if distinct < MIN_DISTINCT:
        return f"distinct codes {distinct} < {MIN_DISTINCT}"
    mode = max(counts) / len(payload)
    if mode > MAX_MODE_FRACTION:
        return f"mode fraction {mode:.4f} > {MAX_MODE_FRACTION}"
    return ""
