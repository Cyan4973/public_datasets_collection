"""Shared selection and label helpers for the JunoCam perijove lossless colour EDR recipe.

Pure standard library. Used by discover.sh (pin generation), check_payload.py
(download-time validation) and build.py. verify.py deliberately re-implements
the parsing and the selection rule instead of importing this module.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

DATASET_ID = "nasa_pds_juno_junocam_perijove_rgb_framelets_u8"
SERIES_ID = "junocam_perijove_rgb_lossless_dn_u8"
BASE_URL = "https://planetarydata.jpl.nasa.gov/img/data/juno"
VOLUMES = [f"JNOJNC_{n:04d}" for n in range(1, 36)]

LINE_SAMPLES = 1648
FRAMELET_LINES = 128
FILTERS = ("BLUE", "GREEN", "RED")
EXPOSURE_LINES = FRAMELET_LINES * len(FILTERS)  # one exposure = BLUE, GREEN, RED framelets
ORBIT_STRIDE = 3          # every third perijove: PJ03, PJ06, ..., PJ78
MAX_REL_MINUTES = 60      # |relative time to own perijove| <= 60 min
EXCLUDE_RATIONALE = re.compile(r"invalid|partial", re.IGNORECASE)
COMPRESSION = "HUFFMAN"   # lossless on-board compression only (SIS section 2)

# Build/verify exclusion rule for zero-filled telemetry loss (SIS 4.3.2).
MAX_ZERO_LINE_FRACTION = 0.02   # all-zero 1648-sample lines
MAX_MODE_SHARE = 0.50           # most frequent DN share
MIN_DISTINCT_DN = 32

PRODUCT_RE = re.compile(r"^JNCE_(\d{7})_(\d\d)([A-Z])(\d{5})_V(\d\d)$")
REL_RE = re.compile(r"PJ(\d+)([+-])(\d{3})T(\d\d):(\d\d)")


def squash(text: str) -> str:
    return " ".join(text.split())


def parse_index(path: Path) -> list[dict]:
    """Rows of a JunoCam volume INDEX.TAB (comma separated, quoted, 16 columns)."""
    rows = []
    with open(path, encoding="latin-1", newline="") as handle:
        for number, record in enumerate(csv.reader(handle), 1):
            if len(record) != 16:
                raise ValueError(f"{path}: row {number} has {len(record)} columns, expected 16")
            r = [field.strip() for field in record]
            rows.append({
                "volume_field": r[0], "sid": r[1], "data_set_id": r[2], "product_id": r[3],
                "start_time": r[4], "stop_time": r[5], "rationale": squash(r[7]), "target": r[12],
                "path": r[13], "label_md5": r[15].lower(),
            })
    return rows


def relative_minutes(rationale: str, orbit: int) -> int | None:
    """Signed minutes from the product's own perijove, from RATIONALE_DESC, else None."""
    match = REL_RE.search(rationale)
    if not match or int(match.group(1)) != orbit:
        return None
    minutes = (int(match.group(3)) * 24 + int(match.group(4))) * 60 + int(match.group(5))
    return -minutes if match.group(2) == "-" else minutes


def candidates(index_dir: Path) -> list[dict]:
    """Highest-version C/JUPITER EDR products of every third perijove within 60 min of perijove."""
    versions: dict[tuple, list] = {}
    for volume in VOLUMES:
        for row in parse_index(index_dir / f"{volume}_INDEX.TAB"):
            if row["sid"] != "JUNOCAM-EDR":
                continue
            match = PRODUCT_RE.match(row["product_id"])
            if not match:
                raise ValueError(f"unexpected EDR product id {row['product_id']!r} in {volume}")
            key = match.group(1, 2, 3, 4)
            versions.setdefault(key, []).append((int(match.group(5)), volume, row))
    out = []
    for key, entries in versions.items():
        version, volume, row = max(entries, key=lambda item: (item[0], item[1]))
        orbit = int(key[1])
        if key[2] != "C" or row["target"] != "JUPITER" or not row["path"].startswith("DATA/EDR/JUPITER/"):
            continue
        if orbit == 0 or orbit % ORBIT_STRIDE:
            continue
        rel = relative_minutes(row["rationale"], orbit)
        if rel is None or abs(rel) > MAX_REL_MINUTES or EXCLUDE_RATIONALE.search(row["rationale"]):
            continue
        out.append({
            "product_id": row["product_id"], "volume": volume, "orbit": orbit, "version": version,
            "label_path": row["path"], "label_md5": row["label_md5"], "rel_minutes": rel,
            "start_time": row["start_time"], "rationale": row["rationale"],
        })
    out.sort(key=lambda item: (item["orbit"], item["product_id"]))
    return out


def parse_label(text: str) -> dict:
    """Flat PDS3 keyword map; IMAGE-object keywords are prefixed 'IMAGE.'."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    values: dict[str, str] = {}
    obj = None
    key = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line == "END":
            key = None
            continue
        match = re.match(r"^([A-Z0-9_:^]+)\s*=\s*(.*)$", line)
        if match:
            name, value = match.group(1), match.group(2).strip()
            if name == "OBJECT":
                obj, key = value, None
            elif name == "END_OBJECT":
                obj, key = None, None
            else:
                key = f"{obj}.{name}" if obj else name
                values[key] = value
        elif key is not None and (values[key].count('"') % 2 or values[key].count("(") > values[key].count(")")):
            values[key] += " " + line
        else:
            raise ValueError(f"unparsed label line {raw!r}")
    return {k: v.strip().strip('"').strip() for k, v in values.items()}


def label_checks(label: dict, product_id: str, orbit: int) -> list[str]:
    """Return a list of problems; empty means the label matches the recipe's material."""
    problems = []
    expect = {
        "PRODUCT_ID": product_id, "TARGET_NAME": "JUPITER", "INSTRUMENT_ID": "JNC",
        "STANDARD_DATA_PRODUCT_ID": "JUNOCAM-EDR", "DATA_SET_ID": "JUNO-J-JUNOCAM-2-EDR-L0-V1.0",
        "MISSION_PHASE_NAME": "SCIENCE ORBITS", "SAMPLE_BIT_MODE_ID": "SQROOT", "SAMPLING_FACTOR": "1",
        "COMPRESSION_TYPE": COMPRESSION, "RECORD_TYPE": "FIXED_LENGTH", "RECORD_BYTES": str(LINE_SAMPLES),
        "^IMAGE": product_id + ".IMG", "IMAGE.LINE_SAMPLES": str(LINE_SAMPLES),
        "IMAGE.SAMPLE_TYPE": "UNSIGNED_INTEGER", "IMAGE.SAMPLE_BITS": "8", "IMAGE.LINE_PREFIX_BYTES": "0",
        "IMAGE.LINE_SUFFIX_BYTES": "0", "ORBIT_NUMBER": str(orbit),
    }
    for name, want in expect.items():
        if label.get(name) != want:
            problems.append(f"{name}={label.get(name)!r} (want {want!r})")
    filters = tuple(re.findall(r"'([A-Z]+)'", label.get("FILTER_NAME", "")))
    if filters != FILTERS:
        problems.append(f"FILTER_NAME={label.get('FILTER_NAME')!r}")
    try:
        lines = int(label.get("IMAGE.LINES", "0"))
        if lines <= 0 or lines % EXPOSURE_LINES or int(label.get("FILE_RECORDS", "-1")) != lines:
            problems.append(f"LINES={lines} FILE_RECORDS={label.get('FILE_RECORDS')} (LINES must equal FILE_RECORDS and be a multiple of {EXPOSURE_LINES})")
    except ValueError:
        problems.append(f"LINES={label.get('IMAGE.LINES')!r}")
    if not re.fullmatch(r"[0-9a-f]{32}", label.get("IMAGE.MD5_CHECKSUM", "")):
        problems.append("IMAGE.MD5_CHECKSUM missing")
    return problems


def select(cands: list[dict], label_dir: Path) -> list[dict]:
    """Per perijove: the lossless (HUFFMAN) candidate closest to perijove; ties -> lowest product id."""
    best: dict[int, tuple] = {}
    for cand in cands:
        label = parse_label((label_dir / f"{cand['product_id']}.LBL").read_text(encoding="latin-1"))
        if label.get("COMPRESSION_TYPE") != COMPRESSION:
            continue
        if EXCLUDE_RATIONALE.search(label.get("RATIONALE_DESC", "")):
            continue
        problems = label_checks(label, cand["product_id"], cand["orbit"])
        if problems:
            raise ValueError(f"{cand['product_id']}: label deviates: {'; '.join(problems)}")
        rank = (abs(cand["rel_minutes"]), cand["product_id"])
        if cand["orbit"] not in best or rank < best[cand["orbit"]][0]:
            lines = int(label["IMAGE.LINES"])
            best[cand["orbit"]] = (rank, dict(cand, lines=lines, img_size=lines * LINE_SAMPLES,
                                              img_md5=label["IMAGE.MD5_CHECKSUM"].lower(),
                                              tdi=label.get("JNO:TDI_STAGES_COUNT", ""),
                                              exposure=label.get("EXPOSURE_DURATION", ""),
                                              altitude=label.get("SPACECRAFT_ALTITUDE", "")))
    return [best[orbit][1] for orbit in sorted(best)]


def read_tsv(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    return [dict(zip(header, line.split("\t"))) for line in lines[1:] if line.strip()]
