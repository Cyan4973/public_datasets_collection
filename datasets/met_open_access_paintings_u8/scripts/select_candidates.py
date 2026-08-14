#!/usr/bin/env python3
"""Select the curated public-domain European paintings from discovery metadata."""
from __future__ import annotations

import csv
import html
import json
import os
from pathlib import Path
import re


discovery_dir = Path(os.environ["DISCOVERY_DIR"])
object_dir = Path(os.environ["OBJECT_DIR"])
policy_path = discovery_dir / "open_access_policy.html"
policy_text = html.unescape(re.sub(r"<[^>]+>", " ", policy_path.read_text(encoding="utf-8"))).lower()
policy_text = re.sub(r"\s+", " ", policy_text)
required_policy_phrases = ("open access", "public domain")
missing = [phrase for phrase in required_policy_phrases if phrase not in policy_text]
if "creative commons zero" not in policy_text and "cc0" not in policy_text:
    missing.append("Creative Commons Zero or CC0")
if missing:
    raise SystemExit(f"Met policy evidence missing phrases: {missing}")

rows = list(csv.DictReader((discovery_dir / "candidate_ids.tsv").open(encoding="utf-8"), delimiter="\t"))
selected: list[dict[str, object]] = []
used_ids: set[int] = set()
rejections: dict[str, int] = {}
preferred_object_ids = {
    "animals": 678013,       # Tiger in Repose
    "architecture": 438490,  # Interior of the Oude Kerk, Delft
    "flowers": 436175,       # Basket of Flowers
    "forest": 438816,        # The Forest in Winter at Sunset
    "garden": 437313,        # The Garden of the Tuileries on a Spring Morning
    "landscape": 437323,     # A Brazilian Landscape
    "night": 437631,         # Night Scene on the Volga
    "seascape": 437854,      # Whalers
    "snow": 437686,          # Rue Eugène Moussoir at Moret: Winter
    "still-life": 435904,    # Still Life with a Skull and a Writing Quill
}


def reject(reason: str) -> None:
    rejections[reason] = rejections.get(reason, 0) + 1


for topic in dict.fromkeys(row["topic"] for row in rows):
    preferred_id = preferred_object_ids.get(topic)
    if preferred_id is None:
        raise SystemExit(f"no curated object ID for topic {topic}")
    matching_rows = [
        item for item in rows
        if item["topic"] == topic and int(item["object_id"]) == preferred_id
    ]
    if len(matching_rows) != 1:
        raise SystemExit(f"curated object {preferred_id} is absent or ambiguous for topic {topic}")
    for row in matching_rows:
        object_id = int(row["object_id"])
        if object_id in used_ids:
            reject("duplicate_selection")
            continue
        path = object_dir / f"{object_id}.json"
        if not path.is_file():
            reject("missing_metadata")
            continue
        obj = json.loads(path.read_text(encoding="utf-8"))
        if int(obj.get("objectID", 0)) != object_id:
            reject("identity_mismatch")
            continue
        if obj.get("department") != "European Paintings":
            reject("wrong_department")
            continue
        classification = str(obj.get("classification", "")).strip()
        object_name = str(obj.get("objectName", "")).lower()
        if classification != "Paintings" or "painting" not in object_name:
            reject("not_painting")
            continue
        if obj.get("isPublicDomain") is not True:
            reject("not_public_domain")
            continue
        image_url = str(obj.get("primaryImage", "")).strip()
        if not image_url.startswith("https://images.metmuseum.org/"):
            reject("missing_original_image")
            continue
        title = str(obj.get("title", "")).strip()
        object_url = str(obj.get("objectURL", "")).strip()
        if not title or not object_url.startswith("https://www.metmuseum.org/art/collection/search/"):
            reject("missing_provenance")
            continue
        selected.append({
            "topic": topic,
            "search_rank": int(row["rank"]),
            "object_id": object_id,
            "title": title,
            "artist": str(obj.get("artistDisplayName", "")).strip(),
            "object_date": str(obj.get("objectDate", "")).strip(),
            "medium": str(obj.get("medium", "")).strip(),
            "dimensions": str(obj.get("dimensions", "")).strip(),
            "department": obj["department"],
            "classification": classification,
            "is_public_domain": True,
            "rights_and_reproduction": str(obj.get("rightsAndReproduction", "")).strip(),
            "object_url": object_url,
            "primary_image_url": image_url,
            "metadata_path": path.relative_to(discovery_dir).as_posix(),
        })
        used_ids.add(object_id)
        break
    else:
        raise SystemExit(f"no valid public-domain painting found for topic {topic}")

if len(selected) != 10:
    raise SystemExit(f"expected 10 selected paintings, found {len(selected)}")

jsonl = discovery_dir / "candidates.jsonl"
with jsonl.open("w", encoding="utf-8") as handle:
    for item in selected:
        handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")

fields = [
    "topic", "object_id", "search_rank", "title", "artist", "object_date",
    "medium", "dimensions", "classification", "is_public_domain",
    "primary_image_url", "object_url", "metadata_path",
]
with (discovery_dir / "candidates.tsv").open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(selected)

summary = {
    "dataset_id": "met_open_access_paintings_u8",
    "selected_count": len(selected),
    "selected_object_ids": [item["object_id"] for item in selected],
    "topics": [item["topic"] for item in selected],
    "rejections": dict(sorted(rejections.items())),
    "license_evidence": {
        "url": "https://metmuseum.github.io/",
        "required_phrases": list(required_policy_phrases),
        "local_path": policy_path.relative_to(discovery_dir).as_posix(),
    },
}
(discovery_dir / "discovery_summary.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps(summary, indent=2, sort_keys=True))
