#!/usr/bin/env bash
# Metadata-only discovery of public native-float32 TESS SPOC light curves.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="nasa_tess_lightcurves_f32"
OUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
MAST_API="https://mast.stsci.edu/api/v0/invoke"
DOWNLOAD_API="https://mast.stsci.edu/api/v0.1/Download/file"
MAX_OBSERVATIONS="${TESS_MAX_OBSERVATIONS:-96}"
MAX_PRODUCTS="${TESS_MAX_PRODUCTS:-64}"
RA="${TESS_DISCOVERY_RA:-90.0}"
DEC="${TESS_DISCOVERY_DEC:--66.5607}"
RADIUS="${TESS_DISCOVERY_RADIUS_DEG:-0.20}"

mkdir -p "$OUT_DIR/api" "$OUT_DIR/headers" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discovery start candidate=$CANDIDATE_ID"

fetch_page() {
  local target="$1" url="$2"
  echo "fetch_page url=$url"
  curl --globoff --fail-with-body --silent --show-error --location \
    --retry 3 --retry-all-errors --connect-timeout 30 --max-time 120 \
    --max-filesize 5000000 --user-agent "openzl-public-datasets/1.0" \
    --output "$target.part" "$url"
  [[ -s "$target.part" ]] || { echo "empty page response: $url" >&2; exit 1; }
  mv "$target.part" "$target"
}

fetch_page "$OUT_DIR/mast_tess_page.html" \
  "https://archive.stsci.edu/missions-and-data/tess"
fetch_page "$OUT_DIR/nasa_media_usage_guidelines.html" \
  "https://www.nasa.gov/nasa-brand-center/images-and-media/"

export OUT_DIR MAST_API DOWNLOAD_API MAX_OBSERVATIONS MAX_PRODUCTS RA DEC RADIUS
python3 - <<'PY'
from __future__ import annotations

from collections import defaultdict
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.parse


OUT_DIR = Path(os.environ["OUT_DIR"])
MAST_API = os.environ["MAST_API"]
DOWNLOAD_API = os.environ["DOWNLOAD_API"]
MAX_OBSERVATIONS = int(os.environ["MAX_OBSERVATIONS"])
MAX_PRODUCTS = int(os.environ["MAX_PRODUCTS"])
RA = float(os.environ["RA"])
DEC = float(os.environ["DEC"])
RADIUS = float(os.environ["RADIUS"])
USER_AGENT = "openzl-public-datasets-tess-f32-discovery/1.0"


def curl_post(request: dict[str, object]) -> dict[str, object]:
    result = subprocess.run(
        [
            "curl", "--fail", "--silent", "--show-error", "--location",
            "--retry", "3", "--retry-all-errors", "--connect-timeout", "30",
            "--max-time", "180", "--max-filesize", "20000000",
            "--user-agent", USER_AGENT, "--data-urlencode",
            "request=" + json.dumps(request, separators=(",", ":")), MAST_API,
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode(errors="replace").strip())
    try:
        response = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"MAST returned non-JSON response: {result.stdout[:200]!r}") from exc
    if str(response.get("status", "")).upper() not in {"COMPLETE", "EXECUTING"}:
        raise RuntimeError(f"MAST request failed: {response.get('status')} {response.get('msg')}")
    return response


def range_probe(uri: str, target: Path) -> bytes:
    url = DOWNLOAD_API + "?" + urllib.parse.urlencode({"uri": uri})
    result = subprocess.run(
        [
            "curl", "--globoff", "--fail", "--silent", "--show-error", "--location",
            "--retry", "3", "--retry-all-errors", "--connect-timeout", "30",
            "--max-time", "180", "--range", "0-65535", "--max-filesize", "100000",
            "--user-agent", USER_AGENT, url,
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode(errors="replace").strip())
    if not 2880 <= len(result.stdout) <= 100_000:
        raise RuntimeError(f"unexpected range response size: {len(result.stdout)}")
    target.write_bytes(result.stdout)
    return result.stdout


def parse_header(data: bytes, start: int) -> tuple[dict[str, str], int]:
    cards: dict[str, str] = {}
    end = None
    for offset in range(start, len(data) - 79, 80):
        card = data[offset : offset + 80].decode("ascii", errors="strict")
        key = card[:8].strip()
        if key == "END":
            end = offset + 80
            break
        if card[8:10] == "= ":
            cards[key] = card[10:80].split("/", 1)[0].strip().strip("'").strip()
    if end is None:
        raise ValueError("FITS END card not found")
    return cards, ((end + 2879) // 2880) * 2880


def table_schema(data: bytes) -> dict[str, object]:
    primary, primary_end = parse_header(data, 0)
    if primary.get("SIMPLE", "").upper() != "T":
        raise ValueError("primary HDU does not declare SIMPLE=T")
    if int(primary.get("NAXIS", "0")) != 0:
        raise ValueError("unexpected primary image payload")
    table, _ = parse_header(data, primary_end)
    if table.get("XTENSION", "").upper() != "BINTABLE":
        raise ValueError("first extension is not BINTABLE")
    fields = int(table.get("TFIELDS", "0"))
    columns = {}
    for index in range(1, fields + 1):
        name = table.get(f"TTYPE{index}", "").upper()
        if name:
            columns[name] = {
                "index": index,
                "tform": table.get(f"TFORM{index}", "").upper(),
                "unit": table.get(f"TUNIT{index}", ""),
            }
    return {
        "row_count": int(table.get("NAXIS2", "0")),
        "row_size_bytes": int(table.get("NAXIS1", "0")),
        "columns": columns,
    }


cone_request = {
    "service": "Mast.Caom.Cone",
    "params": {"ra": RA, "dec": DEC, "radius": RADIUS},
    "format": "json",
    "pagesize": 5000,
    "page": 1,
    "removenullcolumns": True,
}
cone = curl_post(cone_request)
(OUT_DIR / "api" / "cone.json").write_text(json.dumps(cone, indent=2, sort_keys=True) + "\n")
observations = []
for row in cone.get("data", []):
    if not isinstance(row, dict):
        continue
    if str(row.get("obs_collection", "")).upper() != "TESS":
        continue
    if str(row.get("dataproduct_type", "")).lower() != "timeseries":
        continue
    if str(row.get("provenance_name", "")).upper() != "SPOC":
        continue
    if str(row.get("dataRights", row.get("data_rights", ""))).upper() != "PUBLIC":
        continue
    if row.get("obsid") is None:
        continue
    observations.append(row)
observations.sort(
    key=lambda row: (
        str(row.get("target_name", "")),
        int(row.get("sequence_number", 0) or 0),
        str(row.get("obsid", "")),
    )
)
if not observations:
    fields = sorted(cone.get("data", [{}])[0]) if cone.get("data") else []
    raise SystemExit(f"no public TESS SPOC time-series observations; returned_fields={fields}")

selected_observations = []
per_target: defaultdict[str, int] = defaultdict(int)
for row in observations:
    target = str(row.get("target_name", ""))
    if not target or per_target[target] >= 8:
        continue
    selected_observations.append(row)
    per_target[target] += 1
    if len(selected_observations) >= MAX_OBSERVATIONS:
        break

product_rows: list[dict[str, object]] = []
for observation in selected_observations:
    obsid = str(observation["obsid"])
    request = {
        "service": "Mast.Caom.Products",
        "params": {"obsid": obsid},
        "format": "json",
        "pagesize": 200,
        "page": 1,
        "removenullcolumns": True,
    }
    response = curl_post(request)
    (OUT_DIR / "api" / f"products_{obsid}.json").write_text(
        json.dumps(response, indent=2, sort_keys=True) + "\n"
    )
    candidates = []
    for product in response.get("data", []):
        if not isinstance(product, dict):
            continue
        filename = str(product.get("productFilename", ""))
        uri = str(product.get("dataURI", ""))
        subgroup = str(product.get("productSubGroupDescription", "")).upper()
        product_type = str(product.get("productType", "")).upper()
        size = int(product.get("size", 0) or 0)
        if (
            filename.lower().endswith("_lc.fits")
            and uri.startswith("mast:TESS/product/")
            and subgroup == "LC"
            and product_type == "SCIENCE"
            and 100_000 <= size <= 50_000_000
        ):
            candidates.append(product)
    for product in sorted(candidates, key=lambda item: str(item.get("dataURI", "")))[:1]:
        product_rows.append({
            "obsid": obsid,
            "target_name": str(observation.get("target_name", "")),
            "sequence_number": int(observation.get("sequence_number", 0) or 0),
            "data_rights": str(observation.get("dataRights", observation.get("data_rights", ""))),
            "data_uri": str(product["dataURI"]),
            "filename": str(product["productFilename"]),
            "size_bytes": int(product.get("size", 0) or 0),
        })
product_rows.sort(key=lambda row: (str(row["target_name"]), int(row["sequence_number"]), str(row["data_uri"])))

qualified = []
for row in product_rows:
    if len(qualified) >= MAX_PRODUCTS:
        break
    probe_path = OUT_DIR / "headers" / (str(row["filename"]) + ".head")
    try:
        data = range_probe(str(row["data_uri"]), probe_path)
        schema = table_schema(data)
        pdcsap = schema["columns"].get("PDCSAP_FLUX")
        quality = schema["columns"].get("QUALITY")
        qualifies = (
            schema["row_count"] >= 1_000
            and isinstance(pdcsap, dict)
            and pdcsap.get("tform") in {"E", "1E"}
            and isinstance(quality, dict)
            and quality.get("tform") in {"J", "1J"}
        )
        row.update({
            "probe_size_bytes": len(data),
            "probe_sha256": hashlib.sha256(data).hexdigest(),
            "row_count": schema["row_count"],
            "row_size_bytes": schema["row_size_bytes"],
            "pdcsap_column": pdcsap,
            "quality_column": quality,
            "qualifies": qualifies,
        })
        if qualifies:
            qualified.append(row)
    except Exception as exc:
        row.update({"qualifies": False, "reason": str(exc)})
    print(json.dumps(row, sort_keys=True))

columns = (
    "obsid", "target_name", "sequence_number", "data_rights", "data_uri",
    "filename", "size_bytes", "row_count", "row_size_bytes",
    "pdcsap_tform", "quality_tform", "probe_size_bytes", "probe_sha256",
)
with (OUT_DIR / "candidates.tsv").open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(
        handle,
        fieldnames=columns,
        delimiter="\t",
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in qualified:
        writer.writerow({
            **row,
            "pdcsap_tform": row["pdcsap_column"]["tform"],
            "quality_tform": row["quality_column"]["tform"],
        })

policy_files = {}
for name in ("mast_tess_page.html", "nasa_media_usage_guidelines.html"):
    path = OUT_DIR / name
    raw = path.read_bytes()
    policy_files[name] = {"size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
summary = {
    "candidate_id": "nasa_tess_lightcurves_f32",
    "cone": {"ra": RA, "dec": DEC, "radius_degrees": RADIUS},
    "returned_observations": len(cone.get("data", [])),
    "public_spoc_timeseries_observations": len(observations),
    "observations_queried_for_products": len(selected_observations),
    "lc_products_found": len(product_rows),
    "qualified_native_f32_lightcurves": len(qualified),
    "qualified_source_bytes": sum(int(row["size_bytes"]) for row in qualified),
    "source_table_rows": sum(int(row["row_count"]) for row in qualified),
    "distinct_targets": len({str(row["target_name"]) for row in qualified}),
    "policy_files": policy_files,
}
(OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
print(json.dumps(summary, indent=2, sort_keys=True))
if len(qualified) < 10:
    raise SystemExit(f"only {len(qualified)} native-float32 public light curves qualified")
PY

echo "[$(date -Is)] discovery done candidate=$CANDIDATE_ID"
