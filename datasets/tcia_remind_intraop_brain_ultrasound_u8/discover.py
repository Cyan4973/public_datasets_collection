#!/usr/bin/env python3
"""Resolve the pinned ReMIND US_pre_dura volumes (documentation tool).

Not run by download.sh. Reproduces `pinned_series.tsv` from the NBIA ReMIND
US series listing (~270 KB JSON, fetched by discover.sh) plus, per selected
series, one tiny getSOPInstanceUIDs call and one header-only prefix read of
getSingleImage. The server ignores Range, so no Range header is sent: the
plain GET stream is cut after HEADER_PROBE_BYTES and the connection closed.

Selection, applied to the listing:
  1. Collection ReMIND, Modality US, SeriesDescription US_pre_dura (the
     pre-durotomy sweep; US_pre_imri and US_post_dura sweeps are excluded so
     every volume comes from the same surgical stage), ImageCount 1, CC BY 4.0,
     PixelMed NRRDToDicom conversion, ThirdPartyAnalysis NO;
  2. one series per PatientID (all 104 patients have exactly one);
  3. patients in ascending PatientID order; take the longest prefix whose
     cumulative DICOM FileSize stays <= 1,000,000,000 bytes (FileSize bounds
     the voxel bytes from above, so primary output stays under the cap);
  4. every selected header must validate the pinned schema (us_dicom.py).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
import us_dicom  # noqa: E402

BASE = "https://services.cancerimagingarchive.net/nbia-api/services/v1"
HEADER_PROBE_BYTES = 1 << 20
BYTE_BUDGET = 1_000_000_000


def eligible(row: dict) -> bool:
    return (
        row["Collection"] == "ReMIND"
        and row["Modality"] == "US"
        and row["SeriesDescription"] == us_dicom.SERIES_DESCRIPTION
        and int(row["ImageCount"]) == 1
        and row["LicenseURI"] == "https://creativecommons.org/licenses/by/4.0/"
        and row["Manufacturer"] == "PixelMed"
        and row["ManufacturerModelName"] == "com.pixelmed.convert.NRRDToDicom"
        and row["ThirdPartyAnalysis"] == "NO"
    )


def curl_json(url: str) -> object:
    out = subprocess.run(
        ["curl", "-fsSL", "--retry", "5", "--retry-delay", "2", "--max-time", "60", url],
        check=True, capture_output=True,
    ).stdout
    return json.loads(out)


def header_prefix(series: str, sop: str) -> bytes:
    url = f"{BASE}/getSingleImage?SeriesInstanceUID={series}&SOPInstanceUID={sop}"
    proc = subprocess.Popen(["curl", "-sSL", "--max-time", "300", url], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
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
    args = parser.parse_args()
    rows = json.loads(args.listing.read_text(encoding="utf-8"))
    candidates = [row for row in rows if eligible(row)]
    patients = sorted({row["PatientID"] for row in candidates})
    if len(patients) != len(candidates):
        raise SystemExit("expected exactly one US_pre_dura series per patient")
    by_patient = {row["PatientID"]: row for row in candidates}
    print(f"listing_rows={len(rows)} eligible_series={len(candidates)} patients={len(patients)}", file=sys.stderr)
    selected, cumulative = [], 0
    for patient in patients:
        size = int(by_patient[patient]["FileSize"])
        if cumulative + size > BYTE_BUDGET:
            break
        cumulative += size
        selected.append(by_patient[patient])
    print(f"selected={len(selected)} cumulative_file_bytes={cumulative}", file=sys.stderr)
    pins = []
    for row in selected:
        series = row["SeriesInstanceUID"]
        sops = curl_json(f"{BASE}/getSOPInstanceUIDs?SeriesInstanceUID={series}")
        if not isinstance(sops, list) or len(sops) != 1:
            raise SystemExit(f"{series}: expected one SOP instance, got {sops!r}")
        sop = sops[0]["SOPInstanceUID"]
        prefix = header_prefix(series, sop)
        top = us_dicom.parse_header(prefix)
        facts = us_dicom.validate_header(top, None, int(row["FileSize"]))
        expected = (row["PatientID"], row["StudyInstanceUID"], series, sop)
        actual = (facts["patient_id"], facts["study_instance_uid"], facts["series_instance_uid"], facts["sop_instance_uid"])
        if actual != expected:
            raise SystemExit(f"identity mismatch {actual} != {expected}")
        offset = facts["pixel_value_offset"]
        pins.append({
            "ordinal": str(len(pins) + 1),
            "patient_id": row["PatientID"],
            "study_instance_uid": row["StudyInstanceUID"],
            "series_instance_uid": series,
            "sop_instance_uid": sop,
            "file_size": str(row["FileSize"]),
            "header_bytes": str(offset),
            "header_sha256": us_dicom.header_digest(prefix, offset),
            "frames": str(facts["frames"]),
            "rows": str(facts["rows"]),
            "columns": str(facts["columns"]),
            "pixel_spacing_mm": facts["pixel_spacing_mm"],
            "spacing_between_slices_mm": facts["spacing_between_slices_mm"],
        })
        print(f"pin {len(pins):02d} patient={row['PatientID']} size={row['FileSize']} header={offset} "
              f"shape={facts['frames']}x{facts['rows']}x{facts['columns']}", file=sys.stderr)
    if len(pins) != us_dicom.EXPECTED_VOLUMES:
        raise SystemExit(f"selection produced {len(pins)} volumes, parser expects {us_dicom.EXPECTED_VOLUMES}")
    lines = ["\t".join(us_dicom.PIN_COLUMNS)]
    lines += ["\t".join(pin[key] for key in us_dicom.PIN_COLUMNS) for pin in pins]
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"pinned={len(pins)} out={args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
