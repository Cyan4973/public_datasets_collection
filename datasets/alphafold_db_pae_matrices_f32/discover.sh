#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="alphafold_db_pae_matrices_f32"
OUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
API_DIR="$OUT_DIR/api"
BASE_URL="https://alphafold.ebi.ac.uk"
API_URL="$BASE_URL/api/prediction"
REUSE_METADATA="${REUSE_METADATA:-0}"

mkdir -p "$OUT_DIR" "$LOG_DIR" "$API_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] metadata discovery start candidate=$CANDIDATE_ID"

LICENSE_PAGE="$OUT_DIR/alphafold_homepage.html"
LICENSE_ASSET="$OUT_DIR/alphafold_main.js"
LICENSE_SOURCE_FILE="$OUT_DIR/license_source_url.txt"
export BASE_URL LICENSE_PAGE OUT_DIR
if [[ "$REUSE_METADATA" == "1" ]]; then
  if [[ ! -s "$LICENSE_PAGE" || ! -s "$LICENSE_ASSET" || ! -s "$LICENSE_SOURCE_FILE" ]]; then
    echo "REUSE_METADATA=1 requires existing homepage, application asset, and source URL" >&2
    exit 1
  fi
  LICENSE_ASSET_URL="$(<"$LICENSE_SOURCE_FILE")"
  echo "reuse license metadata source=$LICENSE_ASSET_URL"
else
  curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
    --retry-all-errors --max-time 180 --max-filesize 5000000 \
    --user-agent "openzl-public-datasets-alphafold-pae-discovery/1.0" \
    --output "$LICENSE_PAGE.part" "$BASE_URL/"
  mv "$LICENSE_PAGE.part" "$LICENSE_PAGE"

  LICENSE_ASSET_URL="$(python3 - <<'PY'
from __future__ import annotations

from html.parser import HTMLParser
import os
from pathlib import Path
from urllib.parse import urljoin


class Scripts(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script":
            return
        source = dict(attrs).get("src")
        if source:
            self.sources.append(source)


parser = Scripts()
parser.feed(Path(os.environ["LICENSE_PAGE"]).read_text(encoding="utf-8", errors="replace"))
main_assets = [source for source in parser.sources if Path(source).name.startswith("main-")]
if len(main_assets) != 1:
    raise SystemExit(f"expected one versioned AlphaFold DB main asset, found {main_assets}")
print(urljoin(os.environ["BASE_URL"] + "/", main_assets[0]))
PY
)"
  curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
    --retry-all-errors --max-time 180 --max-filesize 20000000 \
    --user-agent "openzl-public-datasets-alphafold-pae-discovery/1.0" \
    --output "$LICENSE_ASSET.part" "$LICENSE_ASSET_URL"
  mv "$LICENSE_ASSET.part" "$LICENSE_ASSET"
  printf '%s\n' "$LICENSE_ASSET_URL" > "$LICENSE_SOURCE_FILE"
fi

export LICENSE_ASSET LICENSE_ASSET_URL
python3 - <<'PY'
from __future__ import annotations

import html
import os
from pathlib import Path
import re


paths = [Path(os.environ["LICENSE_PAGE"]), Path(os.environ["LICENSE_ASSET"])]
source = html.unescape(
    "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in paths)
)
plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", source)).strip()
lower = plain.lower()
accepted = (
    "cc by 4.0" in lower
    or "cc-by 4.0" in lower
    or "cc-by-4.0" in lower
    or "creativecommons.org/licenses/by/4.0" in lower
)
if not accepted:
    raise SystemExit(
        "official AlphaFold DB site resources did not expose an explicit CC BY 4.0 statement"
    )
matches = [
    plain[max(0, match.start() - 100) : min(len(plain), match.end() + 180)]
    for match in re.finditer(r"cc[- ]?by(?:[- ]?4\.0)?", lower)
]
print(
    "license_validation=ok license=CC-BY-4.0 "
    f"source={os.environ['LICENSE_ASSET_URL']}"
)
for excerpt in matches[:3]:
    print(f"license_excerpt={excerpt!r}")
PY

REQUESTS="$OUT_DIR/requested_accessions.tsv"
cat > "$REQUESTS" <<'EOF'
accession	selection_reason
P62805	human histone H4; compact chromatin protein
P01308	human insulin precursor; compact secreted hormone
P69905	human haemoglobin alpha; globular oxygen carrier
P00720	bacteriophage T4 lysozyme; compact enzyme
P42212	Aequorea green fluorescent protein; beta barrel
P02945	archaeal bacteriorhodopsin; membrane protein
P00330	yeast alcohol dehydrogenase 1; metabolic enzyme
P04637	human p53; mixed folded and disordered regions
P04040	human catalase; multidomain enzyme
P00734	human prothrombin; modular secreted protein
P0A6Y8	Escherichia coli DnaK; bacterial chaperone
P10636	human tau; long intrinsically disordered protein
P05067	human amyloid precursor protein; membrane precursor
P00533	human EGFR; receptor tyrosine kinase
P0DTC2	SARS-CoV-2 spike glycoprotein; viral trimer subunit
P38398	human BRCA1; long multidomain regulatory protein
EOF

SUCCESS=0
FAILURES=0
while IFS=$'\t' read -r accession _selection_reason; do
  if [[ "$accession" == "accession" ]]; then
    continue
  fi
  target="$API_DIR/$accession.json"
  if [[ "$REUSE_METADATA" == "1" ]]; then
    if [[ -s "$target" ]]; then
      SUCCESS=$((SUCCESS + 1))
      echo "reuse metadata accession=$accession bytes=$(stat -c %s "$target")"
    else
      echo "warning cached_api_metadata_missing accession=$accession" >&2
      FAILURES=$((FAILURES + 1))
    fi
    continue
  fi
  set +e
  curl --fail --silent --show-error --location --retry 3 --retry-delay 2 \
    --retry-all-errors --max-time 180 --max-filesize 2000000 \
    --user-agent "openzl-public-datasets-alphafold-pae-discovery/1.0" \
    --header "Accept: application/json" \
    --output "$target.part" "$API_URL/$accession"
  status=$?
  set -e
  if (( status != 0 )); then
    rm -f "$target.part"
    echo "warning api_query_failed accession=$accession status=$status" >&2
    FAILURES=$((FAILURES + 1))
    continue
  fi
  mv "$target.part" "$target"
  SUCCESS=$((SUCCESS + 1))
  echo "metadata accession=$accession bytes=$(stat -c %s "$target")"
done < "$REQUESTS"
echo "api_queries_complete success=$SUCCESS failures=$FAILURES"

export API_DIR OUT_DIR REQUESTS
python3 - <<'PY'
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import statistics
from urllib.parse import urlparse


API_DIR = Path(os.environ["API_DIR"])
OUT_DIR = Path(os.environ["OUT_DIR"])
REQUESTS = Path(os.environ["REQUESTS"])
MIN_MATRIX_VALUES = 1_000
MAX_MATRIX_BYTES = 64_000_000
MAX_TOTAL_BYTES = 250_000_000


with REQUESTS.open(encoding="utf-8", newline="") as handle:
    requested_rows = list(csv.DictReader(handle, delimiter="\t"))
reasons = {row["accession"]: row["selection_reason"] for row in requested_rows}


def https_url(value: object, field: str, accession: str) -> str:
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{accession}: invalid {field} URL {text!r}")
    return text


candidates: list[dict[str, object]] = []
api_failures: list[str] = []
for accession in reasons:
    path = API_DIR / f"{accession}.json"
    if not path.is_file():
        api_failures.append(accession)
        continue
    try:
        response = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"{accession}: invalid prediction API JSON: {exc}") from exc
    if not isinstance(response, list) or not response:
        raise SystemExit(f"{accession}: prediction API response is empty or not an array")

    matching = [
        row
        for row in response
        if isinstance(row, dict)
        and str(row.get("uniprotAccession") or "").strip() == accession
    ]
    if not matching:
        raise SystemExit(f"{accession}: API response has no matching accession entry")
    canonical = [
        row
        for row in matching
        if str(row.get("entryId") or "").strip() == f"AF-{accession}-F1"
    ]
    if len(canonical) == 1:
        matching = canonical
    elif not canonical:
        annotated = [
            row
            for row in matching
            if str(row.get("uniprotId") or "").strip()
            and str(row.get("gene") or "").strip()
        ]
        if len(annotated) == 1:
            matching = annotated
        else:
            identities = [
                {
                    "entryId": row.get("entryId"),
                    "uniprotId": row.get("uniprotId"),
                    "gene": row.get("gene"),
                    "organismScientificName": row.get("organismScientificName"),
                    "taxId": row.get("taxId"),
                }
                for row in matching
            ]
            raise SystemExit(
                f"{accession}: exact-accession API results are ambiguous: {identities}"
            )
    else:
        raise SystemExit(f"{accession}: multiple canonical AF-{accession}-F1 entries")

    for row in matching:
        entry_id = str(row.get("entryId") or "").strip()
        sequence = str(row.get("uniprotSequence") or "").strip()
        if not entry_id or not sequence or any(not ("A" <= char <= "Z") for char in sequence):
            raise SystemExit(f"{accession}: missing entry identity or canonical sequence")
        start = int(row.get("uniprotStart") or 1)
        end = int(row.get("uniprotEnd") or len(sequence))
        if start < 1 or end < start or end - start + 1 != len(sequence):
            raise SystemExit(
                f"{accession}: sequence bounds contradict sequence length: "
                f"start={start} end={end} length={len(sequence)}"
            )
        length = len(sequence)
        matrix_values = length * length
        output_bytes = matrix_values * 4
        pae_url = https_url(row.get("paeDocUrl"), "paeDocUrl", accession)
        cif_url = https_url(row.get("cifUrl"), "cifUrl", accession)
        version = int(row.get("latestVersion") or 0)
        if version <= 0 or f"_v{version}." not in pae_url:
            raise SystemExit(
                f"{accession}: PAE URL does not encode latestVersion={version}: {pae_url}"
            )
        if matrix_values < MIN_MATRIX_VALUES or output_bytes > MAX_MATRIX_BYTES:
            continue
        candidates.append(
            {
                "accession": accession,
                "entry_id": entry_id,
                "gene": str(row.get("gene") or ""),
                "uniprot_id": str(row.get("uniprotId") or ""),
                "description": str(row.get("uniprotDescription") or ""),
                "organism": str(row.get("organismScientificName") or ""),
                "tax_id": str(row.get("taxId") or ""),
                "sequence_start": start,
                "sequence_end": end,
                "sequence_length": length,
                "matrix_values": matrix_values,
                "decoded_f32_bytes": output_bytes,
                "latest_version": version,
                "model_created_date": str(row.get("modelCreatedDate") or ""),
                "pae_url": pae_url,
                "cif_url": cif_url,
                "selection_reason": reasons[accession],
            }
        )

if len(candidates) < 8:
    raise SystemExit(
        f"only {len(candidates)} bounded PAE candidates resolved; need at least eight"
    )
candidates.sort(key=lambda row: (int(row["sequence_length"]), str(row["entry_id"])))
total_bytes = sum(int(row["decoded_f32_bytes"]) for row in candidates)
if total_bytes > MAX_TOTAL_BYTES:
    raise SystemExit(f"candidate decoded output exceeds bound: {total_bytes}")

columns = (
    "accession",
    "entry_id",
    "gene",
    "uniprot_id",
    "description",
    "organism",
    "tax_id",
    "sequence_start",
    "sequence_end",
    "sequence_length",
    "matrix_values",
    "decoded_f32_bytes",
    "latest_version",
    "model_created_date",
    "pae_url",
    "cif_url",
    "selection_reason",
)
with (OUT_DIR / "candidates.tsv").open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(candidates)

lengths = [int(row["sequence_length"]) for row in candidates]
summary = {
    "candidate_id": "alphafold_db_pae_matrices_f32",
    "license": "CC BY 4.0",
    "license_evidence_url": os.environ.get(
        "LICENSE_ASSET_URL", "https://alphafold.ebi.ac.uk/"
    ),
    "requested_accessions": len(requested_rows),
    "api_query_failures": api_failures,
    "qualified_entries": len(candidates),
    "distinct_organisms": len({str(row["tax_id"]) for row in candidates}),
    "sequence_length_min": min(lengths),
    "sequence_length_median": statistics.median(lengths),
    "sequence_length_max": max(lengths),
    "total_matrix_values": sum(int(row["matrix_values"]) for row in candidates),
    "total_decoded_f32_bytes": total_bytes,
    "payloads_downloaded": 0,
    "next_step": "bounded download and exact matrix-shape/value preflight",
}
(OUT_DIR / "summary.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps(summary, indent=2, sort_keys=True))
for row in candidates:
    print(
        f"candidate accession={row['accession']} entry={row['entry_id']} "
        f"length={row['sequence_length']} matrix_values={row['matrix_values']} "
        f"decoded_bytes={row['decoded_f32_bytes']} organism={row['organism']!r}"
    )
PY

echo "[$(date -Is)] metadata discovery done candidate=$CANDIDATE_ID"
