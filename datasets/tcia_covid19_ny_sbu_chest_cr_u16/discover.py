#!/usr/bin/env python3
"""Resolve the 48 pinned COVID-19-NY-SBU chest CR series (documentation tool).

Not run by download.sh. Reproduces `pinned_series.tsv` from the NBIA CR
series listing (~9.9 MB JSON, fetched by discover.sh) plus, per selected
series, one tiny getSOPInstanceUIDs call and one header-only prefix read of
getSingleImage (the server ignores Range, so the stream is cut after
HEADER_PROBE_BYTES with the connection closed).

Selection, applied to the listing:
  1. Collection COVID-19-NY-SBU, Modality CR, ImageCount 1, CC BY 4.0,
     ThirdPartyAnalysis NO;
  2. Manufacturer CARESTREAM HEALTH, ManufacturerModelName DRX-REVOLUTION,
     BodyPartExamined CHEST, SeriesDescription AP;
  3. StudyDesc starts with "CHEST AP " and does not mention INFANT (drops the
     pediatric, over-penetrated and trauma one-offs);
  4. FileSize - 2544*3056*2 between 2,048 and 4,096 bytes: the full-field
     2544x3056 size bucket (other buckets are collimation-cropped matrices);
  5. one series per PatientID: the lexicographically smallest
     SeriesInstanceUID;
  6. patients ordered by sha256("tcia_covid19_ny_sbu_chest_cr_u16:" +
     PatientID); walk that order, keep a patient only when the live header
     validates the pinned regime (exact Rows/Columns, 12-bit, MONOCHROME2,
     identity rescale, lossless, Pixel Data last), stop at 48.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
import cr_dicom  # noqa: E402

BASE = "https://services.cancerimagingarchive.net/nbia-api/services/v1"
HEADER_PROBE_BYTES = 16384
STUDY_DESC_PREFIX = "CHEST AP "


def eligible(row: dict) -> bool:
    header = int(row["FileSize"]) - cr_dicom.PIXEL_BYTES
    return (
        row["Collection"] == "COVID-19-NY-SBU"
        and row["Modality"] == "CR"
        and int(row["ImageCount"]) == 1
        and row["LicenseURI"] == "https://creativecommons.org/licenses/by/4.0/"
        and row["ThirdPartyAnalysis"] == "NO"
        and row["Manufacturer"] == "CARESTREAM HEALTH"
        and row["ManufacturerModelName"] == "DRX-REVOLUTION"
        and row["BodyPartExamined"] == "CHEST"
        and row["SeriesDescription"] == "AP"
        and row["StudyDesc"].startswith(STUDY_DESC_PREFIX)
        and "INFANT" not in row["StudyDesc"]
        and 2048 <= header <= 4096
    )


def curl_json(url: str) -> object:
    out = subprocess.run(
        ["curl", "-fsSL", "--retry", "5", "--retry-delay", "2", "--max-time", "60", url],
        check=True, capture_output=True,
    ).stdout
    return json.loads(out)


def header_prefix(series: str, sop: str) -> bytes:
    url = f"{BASE}/getSingleImage?SeriesInstanceUID={series}&SOPInstanceUID={sop}"
    proc = subprocess.Popen(["curl", "-sSL", "--max-time", "120", url], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert proc.stdout is not None
    chunks, size = [], 0
    while size < HEADER_PROBE_BYTES:
        chunk = proc.stdout.read(HEADER_PROBE_BYTES - size)
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    proc.kill()
    proc.wait()
    return b"".join(chunks)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listing", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--count", type=int, default=cr_dicom.EXPECTED_IMAGES)
    args = parser.parse_args()
    rows = json.loads(args.listing.read_text(encoding="utf-8"))
    candidates = [row for row in rows if eligible(row)]
    per_patient: dict[str, dict] = {}
    for row in sorted(candidates, key=lambda r: r["SeriesInstanceUID"]):
        per_patient.setdefault(row["PatientID"], row)
    order = sorted(per_patient, key=lambda p: hashlib.sha256(f"{cr_dicom.DATASET_ID}:{p}".encode()).hexdigest())
    print(f"listing_rows={len(rows)} eligible_series={len(candidates)} eligible_patients={len(order)}", file=sys.stderr)
    pins, rejected = [], []
    for patient in order:
        if len(pins) == args.count:
            break
        row = per_patient[patient]
        series = row["SeriesInstanceUID"]
        sops = curl_json(f"{BASE}/getSOPInstanceUIDs?SeriesInstanceUID={series}")
        if not isinstance(sops, list) or len(sops) != 1:
            rejected.append((patient, "sop count"))
            continue
        sop = sops[0]["SOPInstanceUID"]
        prefix = header_prefix(series, sop)
        try:
            top = cr_dicom.parse_header(prefix)
            facts = cr_dicom.validate_header(top, None, int(row["FileSize"]))
        except cr_dicom.DicomError as exc:
            rejected.append((patient, str(exc)))
            print(f"reject patient={patient} series={series}: {exc}", file=sys.stderr)
            continue
        expected = (patient, row["StudyInstanceUID"], series, sop, row["SoftwareVersions"])
        actual = (facts["patient_id"], facts["study_instance_uid"], facts["series_instance_uid"], facts["sop_instance_uid"], facts["software_versions"])
        if actual != expected:
            rejected.append((patient, f"identity mismatch {actual}"))
            continue
        offset = facts["pixel_value_offset"]
        pins.append({
            "ordinal": str(len(pins) + 1),
            "patient_id": patient,
            "study_instance_uid": row["StudyInstanceUID"],
            "series_instance_uid": series,
            "sop_instance_uid": sop,
            "file_size": str(row["FileSize"]),
            "header_bytes": str(offset),
            "header_sha256": cr_dicom.header_digest(prefix, offset),
            "software_versions": row["SoftwareVersions"],
            "study_desc": row["StudyDesc"],
        })
        print(f"pin {len(pins):02d} patient={patient} size={row['FileSize']} header={offset}", file=sys.stderr)
    if len(pins) != args.count:
        raise SystemExit(f"only {len(pins)} series validated")
    lines = ["\t".join(cr_dicom.PIN_COLUMNS)]
    lines += ["\t".join(pin[key] for key in cr_dicom.PIN_COLUMNS) for pin in pins]
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"pinned={len(pins)} rejected={len(rejected)} out={args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
