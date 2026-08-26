#!/usr/bin/env python3
# Bounded discovery for the official USGS geomagnetism service.
from __future__ import annotations

import html
import json
import math
import os
from pathlib import Path
import re
import statistics
import subprocess
import urllib.parse


OUT_DIR = Path(os.environ["OUT_DIR"])
RESPONSE_DIR = OUT_DIR / "responses"
RIGHTS_DIR = OUT_DIR / "rights"
BASE_URL = "https://geomag.usgs.gov/ws/data/"
USER_AGENT = "openzl-public-datasets-usgs-geomag-f32-discovery/1.0"
STATIONS = ("BOU", "CMO", "FRD", "HON")
START = "2024-05-10T00:00:00Z"
END = "2024-05-10T06:00:00Z"
QUERY_VARIANTS = (
    ("xyzf_adjusted", "X,Y,Z,F", "adjusted"),
    ("hdzf_adjusted", "H,D,Z,F", "adjusted"),
    ("xyzf_variation", "X,Y,Z,F", "variation"),
)
RIGHTS_URLS = (
    "https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits",
    "https://www.usgs.gov/faqs/are-usgs-products-copyrighted",
    "https://geomag.usgs.gov/",
)
RIGHTS_TERMS = (
    "public domain",
    "not copyrighted",
    "free of copyright",
    "freely available",
    "without restriction",
)
MAX_RESPONSE_BYTES = 4_000_000
MIN_COMPONENT_VALUES = 100


def curl(url: str, limit: int) -> bytes:
    command = [
        "curl",
        "--fail-with-body",
        "--silent",
        "--show-error",
        "--location",
        "--retry",
        "2",
        "--retry-delay",
        "2",
        "--max-time",
        "90",
        "--max-filesize",
        str(limit),
        "--user-agent",
        USER_AGENT,
        url,
    ]
    result = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        body = result.stdout.decode("utf-8", errors="replace").strip()[:1000]
        suffix = f" response={body}" if body else ""
        raise RuntimeError(f"curl failed rc={result.returncode}: {detail}{suffix}")
    if len(result.stdout) > limit:
        raise RuntimeError(f"response exceeded {limit}-byte bound")
    return result.stdout


def flatten_text(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"(?is)<script\b.*?</script>|<style\b.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def numeric_values(value: object) -> list[float]:
    if not isinstance(value, list):
        return []
    result: list[float] = []
    for item in value:
        if item is None:
            continue
        if isinstance(item, bool):
            return []
        try:
            number = float(item)
        except (TypeError, ValueError):
            return []
        if math.isfinite(number) and abs(number) < 9.0e4:
            result.append(number)
    return result


def find_components(payload: object) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []

    def visit(value: object, path: tuple[str, ...]) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, path + (str(key),))
            return
        if not isinstance(value, list) or not value:
            return

        values = numeric_values(value)
        if len(values) >= MIN_COMPONENT_VALUES:
            found.append(
                {
                    "path": ".".join(path),
                    "count": len(values),
                    "missing_or_sentinel": len(value) - len(values),
                    "distinct": len(set(values)),
                    "minimum": min(values),
                    "maximum": max(values),
                }
            )
            return

        if all(isinstance(item, dict) for item in value):
            keys = sorted({str(key) for item in value for key in item})
            for key in keys:
                column = [item.get(key) for item in value]
                column_values = numeric_values(column)
                if len(column_values) >= MIN_COMPONENT_VALUES:
                    found.append(
                        {
                            "path": ".".join(path + (key,)),
                            "count": len(column_values),
                            "missing_or_sentinel": len(column) - len(column_values),
                            "distinct": len(set(column_values)),
                            "minimum": min(column_values),
                            "maximum": max(column_values),
                        }
                    )
            for index, item in enumerate(value):
                label = str(item.get("id") or item.get("name") or index)
                visit(item, path + (label,))

    visit(payload, ())
    unique: dict[str, dict[str, object]] = {}
    for item in found:
        unique[str(item["path"])] = item
    return [unique[key] for key in sorted(unique)]


def find_time_arrays(payload: object) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []

    def visit(value: object, path: tuple[str, ...]) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, path + (str(key),))
        elif isinstance(value, list) and len(value) >= MIN_COMPONENT_VALUES:
            strings = [item for item in value if isinstance(item, str)]
            if len(strings) >= MIN_COMPONENT_VALUES and sum("T" in item for item in strings) >= MIN_COMPONENT_VALUES:
                result.append(
                    {
                        "path": ".".join(path),
                        "count": len(strings),
                        "first": strings[0],
                        "last": strings[-1],
                    }
                )

    visit(payload, ())
    return result


def query_url(station: str, elements: str, data_type: str) -> str:
    params = {
        "id": station,
        "starttime": START,
        "endtime": END,
        "elements": elements,
        "sampling_period": "60",
        "type": data_type,
        "format": "json",
    }
    return BASE_URL + "?" + urllib.parse.urlencode(params)


def inspect_query(station: str, variant: str, elements: str, data_type: str) -> dict[str, object]:
    url = query_url(station, elements, data_type)
    local_path = RESPONSE_DIR / f"{station.lower()}_{variant}.json"
    row: dict[str, object] = {
        "station": station,
        "variant": variant,
        "elements": elements,
        "data_type": data_type,
        "url": url,
        "status": "error",
    }
    try:
        raw = curl(url, MAX_RESPONSE_BYTES)
        local_path.write_bytes(raw)
        payload = json.loads(raw)
        components = find_components(payload)
        times = find_time_arrays(payload)
        useful = [item for item in components if int(item["distinct"]) > 1]
        row.update(
            {
                "status": "qualified" if len(useful) >= 3 and times else "schema_unqualified",
                "bytes": len(raw),
                "top_level_type": type(payload).__name__,
                "top_level_keys": sorted(payload) if isinstance(payload, dict) else [],
                "time_arrays": times,
                "numeric_components": components,
                "nonconstant_components": len(useful),
                "response_file": local_path.name,
            }
        )
    except Exception as exc:  # continue across official endpoint variants
        row["error"] = str(exc)
    return row


def inspect_rights() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, url in enumerate(RIGHTS_URLS):
        row: dict[str, object] = {"url": url, "status": "error", "matches": []}
        try:
            raw = curl(url, 5_000_000)
            path = RIGHTS_DIR / f"rights_{index + 1}.html"
            path.write_bytes(raw)
            text = flatten_text(raw)
            lower = text.lower()
            matches = []
            for term in RIGHTS_TERMS:
                position = lower.find(term)
                if position >= 0:
                    start = max(0, position - 180)
                    end = min(len(text), position + len(term) + 280)
                    matches.append(text[start:end])
            row.update(
                {
                    "status": "fetched",
                    "bytes": len(raw),
                    "matches": matches,
                    "response_file": path.name,
                }
            )
        except Exception as exc:
            row["error"] = str(exc)
        rows.append(row)
    return rows


RESPONSE_DIR.mkdir(parents=True, exist_ok=True)
RIGHTS_DIR.mkdir(parents=True, exist_ok=True)

rights = inspect_rights()
queries: list[dict[str, object]] = []
for station in STATIONS:
    station_succeeded = False
    for variant, elements, data_type in QUERY_VARIANTS:
        row = inspect_query(station, variant, elements, data_type)
        queries.append(row)
        print(
            f"station={station} variant={variant} status={row['status']} "
            f"components={row.get('nonconstant_components', 0)} bytes={row.get('bytes', 0)}"
        )
        if row["status"] == "qualified":
            station_succeeded = True
            break
    if not station_succeeded:
        print(f"station={station} no_qualified_variant=1")

qualified = [row for row in queries if row["status"] == "qualified"]
rights_matches = sum(len(row.get("matches", [])) for row in rights)
counts = [
    int(component["count"])
    for row in qualified
    for component in row.get("numeric_components", [])
    if int(component["distinct"]) > 1
]
summary = {
    "candidate_id": "usgs_geomag_observatory_minute_f32",
    "probe_interval": {"start": START, "end": END, "sampling_period_seconds": 60},
    "stations_requested": list(STATIONS),
    "qualified_station_queries": len(qualified),
    "qualified_stations": sorted({str(row["station"]) for row in qualified}),
    "rights_pages_with_matches": sum(bool(row.get("matches")) for row in rights),
    "rights_match_count": rights_matches,
    "median_qualified_component_values": statistics.median(counts) if counts else 0,
    "queries": queries,
    "rights": rights,
}
(OUT_DIR / "summary.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)

print(
    "summary "
    f"qualified_station_queries={len(qualified)} "
    f"qualified_stations={','.join(summary['qualified_stations']) or 'none'} "
    f"rights_pages_with_matches={summary['rights_pages_with_matches']} "
    f"rights_match_count={rights_matches}"
)
print(f"summary_path={OUT_DIR / 'summary.json'}")

if len(summary["qualified_stations"]) < 2:
    raise SystemExit("preflight failed: fewer than two observatories exposed qualified numeric data")
if rights_matches == 0:
    raise SystemExit("preflight incomplete: no explicit reuse-language match found on fetched USGS pages")
