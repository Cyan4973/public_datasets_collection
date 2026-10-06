#!/usr/bin/env python3
"""Download-time semantic check of one pinned IRIS level-1 FUV FITS file.

usage: check_payload.py <fits_path> <sources.tsv> <filename>

Checks the exact pinned size, MD5 (= S3 ETag of the single-part object) and
full-object SHA-1 (= x-amz-checksum-sha1), the FITS HDU chain (empty primary +
one RICE_1 tile-compressed BINTABLE ending at the file size), the header regime
(level-1 FUV unsummed full readout, LIGHT, int16, 4144 x 1096, BLANK -32768),
DATASUM and the HDU CHECKSUM, and the pinned header facts (OBSID, FSN, T_OBS,
DATAVALS, DATAMIN, DATAMAX, DATAMEDN, DATASUM). Prints the file SHA-256.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import iris_fits  # noqa: E402


def main() -> None:
    path, sources, filename = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    with sources.open(newline="") as fh:
        pins = [r for r in csv.DictReader(fh, delimiter="\t") if r["filename"] == filename]
    if len(pins) != 1:
        raise SystemExit(f"{filename}: not pinned exactly once in sources.tsv")
    pin = pins[0]
    blob = path.read_bytes()
    if len(blob) != int(pin["size_bytes"]):
        raise SystemExit(f"{filename}: size {len(blob)} != pinned {pin['size_bytes']}")
    if hashlib.md5(blob).hexdigest() != pin["md5_etag"]:
        raise SystemExit(f"{filename}: MD5 != pinned S3 ETag {pin['md5_etag']}")
    if base64.b64encode(hashlib.sha1(blob).digest()).decode() != pin["sha1_b64"]:
        raise SystemExit(f"{filename}: SHA-1 != pinned x-amz-checksum-sha1 {pin['sha1_b64']}")
    sha256 = hashlib.sha256(blob).hexdigest()
    if pin.get("sha256") and pin["sha256"] != sha256:
        raise SystemExit(f"{filename}: SHA-256 != pinned {pin['sha256']}")

    _primary, table, hdr_off, data_off, nbytes = iris_fits.hdu_layout(blob)
    problems = iris_fits.regime_problems(table)
    if problems:
        raise SystemExit(f"{filename}: header regime: {'; '.join(problems)}")
    end = data_off + iris_fits.padded(nbytes)
    if end != len(blob):
        raise SystemExit(f"{filename}: compressed HDU ends at {end}, file has {len(blob)} bytes")
    datasum = iris_fits.ones_complement_sum(blob[data_off:end])
    if str(datasum) != str(table.get("DATASUM")):
        raise SystemExit(f"{filename}: DATASUM mismatch")
    if iris_fits.ones_complement_sum(blob[hdr_off:data_off], datasum) != 0xFFFFFFFF:
        raise SystemExit(f"{filename}: HDU CHECKSUM does not verify")
    facts = {"obsid": table["ISQOLTID"], "fsn": table["FSN"], "t_obs": table["T_OBS"],
             "datavals": table["DATAVALS"], "datamin": table["DATAMIN"],
             "datamax": table["DATAMAX"], "datamedn": table["DATAMEDN"],
             "datasum": table["DATASUM"]}
    for key, value in facts.items():
        if str(value) != str(pin[key]):
            raise SystemExit(f"{filename}: header {key}={value!r} != pinned {pin[key]!r}")
    date = pin["key"].split("/level1/")[1][:10].replace("/", "-")
    if date != pin["date"] or not filename.startswith("iris" + date.replace("-", "")):
        raise SystemExit(f"{filename}: key path date does not match the pin")
    print(sha256)


if __name__ == "__main__":
    main()
