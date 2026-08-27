#!/usr/bin/env python3
"""Discover bounded official USGS ShakeMap raster products."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from urllib.parse import urlencode


CATALOG_API = "https://earthquake.usgs.gov/fdsnws/event/1/query"
USER_AGENT = "openzl-public-datasets-usgs-shakemap-f32-discovery/1.0"
START_TIME = "2010-01-01"
END_TIME = "2026-01-01"
MIN_MAGNITUDE = 7.0
CATALOG_LIMIT = 2_000
MAX_DETAIL_REQUESTS = 100
MAX_RESPONSE_BYTES = 30_000_000
MIN_RASTER_BYTES = 100_000
MAX_RASTER_BYTES = 500_000_000


def curl_json(url: str) -> dict[str, object]:
    command = [
        "curl",
        "--fail-with-body",
        "--silent",
        "--show-error",
        "--location",
        "--retry",
        "5",
        "--retry-all-errors",
        "--retry-delay",
        "3",
        "--connect-timeout",
        "30",
        "--max-time",
        "180",
        "--max-filesize",
        str(MAX_RESPONSE_BYTES),
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
        body = result.stdout.decode("utf-8", errors="replace").strip()[:1_000]
        suffix = f" response={body}" if body else ""
        raise RuntimeError(
            f"curl failed rc={result.returncode}: {detail}{suffix}"
        )
    if len(result.stdout) > MAX_RESPONSE_BYTES:
        raise RuntimeError("USGS metadata response exceeded safety cap")
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise RuntimeError("USGS metadata response is not a JSON object")
    return value


def event_time(milliseconds: object) -> str:
    try:
        timestamp = int(milliseconds) / 1_000
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def catalog_url() -> str:
    return CATALOG_API + "?" + urlencode(
        {
            "format": "geojson",
            "starttime": START_TIME,
            "endtime": END_TIME,
            "minmagnitude": MIN_MAGNITUDE,
            "orderby": "magnitude",
            "limit": CATALOG_LIMIT,
        }
    )


def product_contents(product: dict[str, object]) -> dict[str, object]:
    value = product.get("contents", {})
    return value if isinstance(value, dict) else {}


def preferred_shakemap(detail: dict[str, object]) -> dict[str, object] | None:
    properties = detail.get("properties", {})
    products = properties.get("products", {}) if isinstance(properties, dict) else {}
    shakemaps = products.get("shakemap", []) if isinstance(products, dict) else []
    if not isinstance(shakemaps, list):
        return None
    candidates = [
        product
        for product in shakemaps
        if isinstance(product, dict) and product.get("status") != "DELETE"
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda product: (
            int(product.get("preferredWeight", 0) or 0),
            int(product.get("updateTime", 0) or 0),
        ),
    )


def raster_content(product: dict[str, object]) -> tuple[str, dict[str, object]] | None:
    matches = [
        (key, value)
        for key, value in product_contents(product).items()
        if str(key).lower().endswith("raster.zip") and isinstance(value, dict)
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def score(row: dict[str, object]) -> int:
    value = 0
    magnitude = float(row["magnitude"])
    size = int(row["raster_size_bytes"])
    value += min(int((magnitude - 7.0) * 10), 20)
    if row["product_status"] == "UPDATE":
        value += 4
    if int(row["preferred_weight"]) >= 100:
        value += 5
    if 1_000_000 <= size <= 100_000_000:
        value += 8
    elif size <= 250_000_000:
        value += 4
    source = str(row["product_source"])
    if source in {"us", "ak", "ci", "nc", "hv"}:
        value += 3
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    events_dir = args.output_dir / "events"
    events_dir.mkdir(parents=True, exist_ok=True)

    catalog = curl_json(catalog_url())
    features = catalog.get("features", [])
    if not isinstance(features, list):
        raise SystemExit("USGS catalog features payload is not a list")
    eligible = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties", {})
        if not isinstance(properties, dict):
            continue
        types = str(properties.get("types", ""))
        detail_url = str(properties.get("detail", ""))
        if ",shakemap," not in types or not detail_url.startswith("https://"):
            continue
        eligible.append(feature)
    eligible.sort(
        key=lambda feature: (
            -float(feature.get("properties", {}).get("mag") or 0),
            -int(feature.get("properties", {}).get("time") or 0),
            str(feature.get("id", "")),
        )
    )
    eligible = eligible[:MAX_DETAIL_REQUESTS]

    rows: list[dict[str, object]] = []
    errors: list[str] = []
    for feature in eligible:
        event_id = str(feature.get("id", ""))
        properties = feature.get("properties", {})
        detail_url = str(properties.get("detail", ""))
        try:
            detail = curl_json(detail_url)
        except Exception as error:
            errors.append(f"{event_id}: {error}")
            continue
        (events_dir / f"{event_id}.json").write_text(
            json.dumps(detail, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        product = preferred_shakemap(detail)
        if product is None:
            continue
        raster = raster_content(product)
        if raster is None:
            continue
        content_key, content = raster
        url = str(content.get("url", ""))
        try:
            size = int(content.get("length", 0))
        except (TypeError, ValueError):
            continue
        if (
            not MIN_RASTER_BYTES <= size <= MAX_RASTER_BYTES
            or not url.startswith("https://")
        ):
            continue
        row = {
            "score": 0,
            "event_id": event_id,
            "event_time_utc": event_time(properties.get("time")),
            "magnitude": float(properties.get("mag") or 0),
            "place": str(properties.get("place", "")),
            "event_detail_url": detail_url,
            "product_source": str(product.get("source", "")),
            "product_code": str(product.get("code", "")),
            "product_status": str(product.get("status", "")),
            "preferred_weight": int(product.get("preferredWeight", 0) or 0),
            "product_update_time": event_time(product.get("updateTime")),
            "content_key": content_key,
            "raster_size_bytes": size,
            "raster_content_type": str(content.get("contentType", "")),
            "raster_url": url,
        }
        row["score"] = score(row)
        rows.append(row)

    rows.sort(
        key=lambda row: (
            -int(row["score"]),
            int(row["raster_size_bytes"]),
            str(row["event_id"]),
        )
    )
    fields = (
        "score",
        "event_id",
        "event_time_utc",
        "magnitude",
        "place",
        "product_source",
        "product_code",
        "product_status",
        "preferred_weight",
        "product_update_time",
        "content_key",
        "raster_size_bytes",
        "raster_content_type",
        "raster_url",
        "event_detail_url",
    )
    with (args.output_dir / "candidates.tsv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "catalog_url": catalog_url(),
        "catalog_feature_count": len(features),
        "events_advertising_shakemap": len(eligible),
        "detail_request_cap": MAX_DETAIL_REQUESTS,
        "candidate_raster_products": len(rows),
        "errors": errors,
        "top_candidates": rows[:30],
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {key: value for key, value in summary.items() if key != "top_candidates"},
            indent=2,
            sort_keys=True,
        )
    )
    print(f"candidate_table={args.output_dir / 'candidates.tsv'}")
    if not rows:
        raise SystemExit("no bounded USGS ShakeMap raster products discovered")


if __name__ == "__main__":
    main()
