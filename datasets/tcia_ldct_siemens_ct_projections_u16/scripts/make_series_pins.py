#!/usr/bin/env python3
"""Regenerate series_pins.tsv from one NBIA getSeries listing.

This documents how the 100 pinned series were resolved during authoring:

    curl -o series.json \
      'https://services.cancerimagingarchive.net/nbia-api/services/v1/getSeries?Collection=LDCT-and-Projection-data'
    python3 scripts/make_series_pins.py series.json > series_pins.tsv

Selection rule: Manufacturer == 'SIEMENS', SeriesDescription exactly
'Full dose projections', Modality 'CT', PatientID matching ^[CL][0-9]{3}$
(public chest and liver subjects; head 'N' subjects are NIH-controlled and
excluded), and LicenseURI exactly the CC BY 4.0 deed. 'Low dose projections'
(simulated by noise insertion), all GE series, and every reconstructed image
series are excluded by the description/manufacturer filter.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

LICENSE_URI = "https://creativecommons.org/licenses/by/4.0/"
BODY_PART = {"C": "CHEST", "L": "ABDOMEN"}


def main() -> int:
    rows = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    selected = []
    for row in rows:
        if row.get("Collection") != "LDCT-and-Projection-data":
            continue
        if row.get("Manufacturer") != "SIEMENS" or row.get("SeriesDescription") != "Full dose projections":
            continue
        patient = str(row.get("PatientID", ""))
        if not re.fullmatch(r"[CL][0-9]{3}", patient):
            continue
        if row.get("Modality") != "CT" or row.get("LicenseURI") != LICENSE_URI:
            raise SystemExit(f"unexpected modality/license for {patient}")
        if row.get("BodyPartExamined") != BODY_PART[patient[0]]:
            raise SystemExit(f"unexpected body part for {patient}: {row.get('BodyPartExamined')!r}")
        selected.append(row)
    selected.sort(key=lambda row: row["PatientID"])
    if len(selected) != 100 or len({row["PatientID"] for row in selected}) != 100:
        raise SystemExit(f"expected 100 distinct series, found {len(selected)}")
    print("patient_id\tbody_part\tseries_instance_uid\tstudy_instance_uid\timage_count\tfile_size_bytes")
    for row in selected:
        print(
            f"{row['PatientID']}\t{row['BodyPartExamined']}\t{row['SeriesInstanceUID']}\t"
            f"{row['StudyInstanceUID']}\t{int(row['ImageCount'])}\t{int(row['FileSize'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
