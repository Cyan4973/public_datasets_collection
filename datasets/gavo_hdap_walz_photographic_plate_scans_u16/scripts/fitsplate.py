"""Shared FITS primary-header parsing and header-regime checks for HDAP Walz plates.

Pure standard library. Used by discover.py, download.sh (check-file) and build.py.
verify.py deliberately carries its own independent parser.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

BLOCK = 2880
CARD = 80
TELESCOP = "72cm Walz Reflektor"
MAX_HEADER_BLOCKS = 64


class RegimeError(ValueError):
    pass


def _card_value(raw: str):
    body = raw[10:]
    stripped = body.lstrip()
    if stripped.startswith("'"):
        # FITS string: '' is an escaped quote; value ends at the first lone quote.
        out = []
        i = 1
        while i < len(stripped):
            ch = stripped[i]
            if ch == "'":
                if i + 1 < len(stripped) and stripped[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                break
            out.append(ch)
            i += 1
        return "".join(out).rstrip()
    value = stripped.split("/", 1)[0].strip()
    if value in ("T", "F"):
        return value == "T"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def parse_primary_header(blob: bytes) -> tuple[dict, int]:
    """Return (cards, header_bytes). Raises RegimeError if END is not found."""
    cards: dict = {}
    for offset in range(0, min(len(blob), BLOCK * MAX_HEADER_BLOCKS), CARD):
        chunk = blob[offset : offset + CARD]
        if len(chunk) < CARD:
            break
        try:
            raw = chunk.decode("ascii")
        except UnicodeDecodeError as exc:
            raise RegimeError(f"non-ASCII header card at byte {offset}") from exc
        key = raw[:8].rstrip()
        if key == "END" and raw[3:].strip() == "":
            header_bytes = (offset // BLOCK + 1) * BLOCK
            return cards, header_bytes
        if raw[8:10] == "= " and key and key not in cards:
            cards[key] = _card_value(raw)
    raise RegimeError("END card not found in header blocks")


def check_regime(cards: dict, header_bytes: int, file_size: int, pin: dict | None = None) -> dict:
    """Validate the primary-HDU-only uint16 plate regime; return geometry facts."""
    def need(key, expected):
        if cards.get(key) != expected:
            raise RegimeError(f"{key}={cards.get(key)!r}, expected {expected!r}")

    need("SIMPLE", True)
    need("BITPIX", 16)
    need("NAXIS", 2)
    need("BZERO", 32768)
    need("BSCALE", 1)
    if "BLANK" in cards:
        raise RegimeError(f"unexpected BLANK={cards['BLANK']!r}")
    if "NAXIS3" in cards:
        raise RegimeError("unexpected NAXIS3")
    if cards.get("TELESCOP") != TELESCOP:
        raise RegimeError(f"TELESCOP={cards.get('TELESCOP')!r}")
    obj = str(cards.get("OBJECT", ""))
    if not obj.startswith("Moon"):
        raise RegimeError(f"OBJECT={obj!r} is not a lunar plate")
    naxis1 = cards.get("NAXIS1")
    naxis2 = cards.get("NAXIS2")
    if not isinstance(naxis1, int) or not isinstance(naxis2, int) or naxis1 < 1000 or naxis2 < 1000:
        raise RegimeError(f"bad NAXIS1/NAXIS2 {naxis1!r}/{naxis2!r}")
    data_bytes = naxis1 * naxis2 * 2
    pad = (-data_bytes) % BLOCK
    if header_bytes + data_bytes + pad != file_size:
        raise RegimeError(
            f"file size {file_size} != header {header_bytes} + data {data_bytes} + pad {pad}"
            " (extension HDUs or truncation)"
        )
    if pin is not None:
        if naxis1 != int(pin["naxis1"]) or naxis2 != int(pin["naxis2"]):
            raise RegimeError(f"geometry {naxis1}x{naxis2} != pinned {pin['naxis1']}x{pin['naxis2']}")
        if header_bytes != int(pin["header_bytes"]):
            raise RegimeError(f"header_bytes {header_bytes} != pinned {pin['header_bytes']}")
        if str(cards.get("DATE-OBS")) != pin["fits_date_obs"]:
            raise RegimeError(f"DATE-OBS {cards.get('DATE-OBS')!r} != pinned {pin['fits_date_obs']}")
    return {
        "naxis1": naxis1,
        "naxis2": naxis2,
        "header_bytes": header_bytes,
        "data_bytes": data_bytes,
        "pad_bytes": pad,
        "date_obs": str(cards.get("DATE-OBS")),
        "object": obj,
    }


def header_sha256(blob: bytes, header_bytes: int) -> str:
    return hashlib.sha256(blob[:header_bytes]).hexdigest()


def read_sources(path: Path) -> list[dict]:
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln and not ln.startswith("#")]
    head = lines[0].split("\t")
    rows = [dict(zip(head, ln.split("\t"))) for ln in lines[1:]]
    for row in rows:
        if len(row) != len(head):
            raise SystemExit(f"malformed sources row: {row}")
    return rows


def check_file(path: Path, pin: dict) -> dict:
    """Full semantic check of one downloaded plate file against its pin."""
    size = path.stat().st_size
    if size != int(pin["size_bytes"]):
        raise RegimeError(f"{path.name}: size {size} != pinned {pin['size_bytes']}")
    with path.open("rb") as handle:
        head = handle.read(BLOCK * MAX_HEADER_BLOCKS)
    cards, header_bytes = parse_primary_header(head)
    facts = check_regime(cards, header_bytes, size, pin)
    if str(cards.get("PLATE-ID", "")).strip() not in ("", pin["plate_id"]):
        raise RegimeError(f"PLATE-ID {cards.get('PLATE-ID')!r} != {pin['plate_id']}")
    hsha = header_sha256(head, header_bytes)
    if hsha != pin["header_sha256"]:
        raise RegimeError(f"{path.name}: header sha256 {hsha} != pinned {pin['header_sha256']}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(8 * 1024 * 1024):
            digest.update(block)
    facts["sha256"] = digest.hexdigest()
    return facts


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 4 or sys.argv[1] != "check-file":
        raise SystemExit("usage: fitsplate.py check-file <fits> <plate_id>  (reads ../sources.tsv)")
    src = Path(__file__).resolve().parent.parent / "sources.tsv"
    pins = {row["plate_id"]: row for row in read_sources(src)}
    try:
        facts = check_file(Path(sys.argv[2]), pins[sys.argv[3]])
    except RegimeError as exc:
        raise SystemExit(f"REJECT {sys.argv[3]}: {exc}")
    print(f"ok {sys.argv[3]} {facts['naxis1']}x{facts['naxis2']} date_obs={facts['date_obs']} sha256={facts['sha256']}")
