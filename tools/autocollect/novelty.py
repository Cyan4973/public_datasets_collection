#!/usr/bin/env python3
"""Corpus-relative novelty lookup for autocollect candidates.

Searches the committed layers (datasets/, staging/, attempts registry,
pipeline ledger) and the downstream corpus for matches on source URLs and
free-text terms. Keys on stable dataset_id per AGENTS.md; never inventories
.data/.

Examples:
  novelty.py --url https://zenodo.org/records/123 --terms lidar intensity
  novelty.py --list-width 16
  novelty.py --vocabulary                       # measurement types already collected
  novelty.py --type sar_backscatter --archive planetarycomputer.microsoft.com/modis
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import tomllib
from pathlib import Path
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[2]
OPENZL_ROOT = REPO_ROOT.parent
DOWNSTREAM_NUMERIC = OPENZL_ROOT / "training_data" / "numeric_datasets"
DOWNSTREAM_TRANSFORMER = OPENZL_ROOT / "transformer" / "source_data"
DOWNSTREAM_REGISTRY = DOWNSTREAM_NUMERIC / "public_datasets" / "repro" / "dataset_registry.csv"
REGISTRY_PATH = REPO_ROOT / "attempts" / "dataset_status.tsv"
LEDGER_PATH = REPO_ROOT / "pipeline" / "candidates.tsv"
BREADTH_KEYS_PATH = REPO_ROOT / "pipeline" / "breadth_keys.tsv"
BREADTH_VOCAB_PATH = REPO_ROOT / "pipeline" / "breadth_vocabulary.tsv"

TRANSFORMER_WIDTH_DIRS = {8: "u8", 16: "le-u16", 32: "le-u32", 64: "le-u64"}
URL_RE = re.compile(r"https?://[^\s'\"<>)`\\]+")
MAX_SCAN_BYTES = 1_000_000
HOST_MATCH_LIST_LIMIT = 15


def normalize_url(url: str) -> tuple[str, list[str]]:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    segments = [segment for segment in parsed.path.split("/") if segment]
    return host, segments


def recipe_urls(recipe_dir: Path, manifest: dict) -> set[str]:
    urls: set[str] = set()
    for key in ("homepage",):
        if isinstance(manifest.get(key), str):
            urls.add(manifest[key])
    for table in ("origins", "resources"):
        for entry in manifest.get(table, []):
            if isinstance(entry, dict) and isinstance(entry.get("url"), str):
                urls.add(entry["url"])
    for path in [*recipe_dir.glob("*.sh"), *recipe_dir.glob("*.py"), *recipe_dir.glob("scripts/*")]:
        if path.is_file() and path.stat().st_size <= MAX_SCAN_BYTES:
            urls.update(URL_RE.findall(path.read_text(encoding="utf-8", errors="replace")))
    return urls


def load_recipes(root: Path, layer: str) -> list[dict]:
    recipes = []
    for manifest_path in sorted(root.glob("*/manifest.toml")):
        try:
            manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            continue
        widths = sorted(
            {
                int(series["bit_width"])
                for series in manifest.get("series", [])
                if isinstance(series, dict)
                and series.get("role", "primary") != "auxiliary"
                and isinstance(series.get("bit_width"), int)
                and series["bit_width"] > 0
            }
        )
        text_parts = [
            manifest_path.parent.name,
            str(manifest.get("name", "")),
            str(manifest.get("description", "")),
        ]
        for series in manifest.get("series", []):
            if isinstance(series, dict):
                text_parts += [str(series.get(key, "")) for key in ("id", "description", "semantic_meaning", "source_field")]
        recipes.append(
            {
                "layer": layer,
                "dataset_id": manifest_path.parent.name,
                "name": str(manifest.get("name", "")),
                "widths": widths,
                "urls": sorted(recipe_urls(manifest_path.parent, manifest)),
                "text": " ".join(text_parts).lower(),
            }
        )
    return recipes


def load_tsv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def downstream_families(width: int) -> list[str]:
    names: set[str] = set()
    numeric_dir = DOWNSTREAM_NUMERIC / f"{width}bit" / "datasets"
    if numeric_dir.is_dir():
        names.update(path.name for path in numeric_dir.iterdir())
    transformer_dir = DOWNSTREAM_TRANSFORMER / TRANSFORMER_WIDTH_DIRS[width]
    if transformer_dir.is_dir():
        names.update(path.name for path in transformer_dir.iterdir())
    return sorted(names)


def url_matches(query_urls: list[str], recipes: list[dict]) -> list[dict]:
    matches = []
    for query in query_urls:
        q_host, q_segments = normalize_url(query)
        if not q_host:
            continue
        host_only: list[str] = []
        for recipe in recipes:
            best = -1
            best_url = ""
            for url in recipe["urls"]:
                host, segments = normalize_url(url)
                if host != q_host:
                    continue
                common = 0
                for left, right in zip(q_segments, segments):
                    if left != right:
                        break
                    common += 1
                if common > best:
                    best, best_url = common, url
            if best < 0:
                continue
            if best >= 2 or (best >= 1 and len(q_segments) <= 1):
                matches.append(
                    {
                        "query": query,
                        "kind": "same_path" if best >= 2 else "same_host_root",
                        "common_path_segments": best,
                        "layer": recipe["layer"],
                        "dataset_id": recipe["dataset_id"],
                        "widths": recipe["widths"],
                        "matched_url": best_url,
                    }
                )
            else:
                host_only.append(f"{recipe['layer']}:{recipe['dataset_id']}")
        if host_only:
            matches.append(
                {
                    "query": query,
                    "kind": "same_host_only",
                    "count": len(host_only),
                    "examples": host_only[:HOST_MATCH_LIST_LIMIT],
                }
            )
    return matches


def term_matches(terms: list[str], recipes: list[dict], registry: list[dict], ledger: list[dict]) -> dict:
    lowered = [term.lower() for term in terms if term.strip()]
    result: dict[str, list] = {"recipes": [], "registry": [], "ledger": [], "downstream": [], "downstream_registry": []}
    if not lowered:
        return result

    def hit(text: str) -> list[str]:
        text = text.lower()
        return [term for term in lowered if term in text]

    for recipe in recipes:
        found = hit(recipe["text"] + " " + " ".join(recipe["urls"]))
        if found:
            result["recipes"].append({"layer": recipe["layer"], "dataset_id": recipe["dataset_id"], "widths": recipe["widths"], "terms": found})
    for row in registry:
        found = hit(" ".join(row.get(key, "") for key in ("dataset_id", "reason", "retry_condition")))
        if found:
            result["registry"].append({key: row.get(key, "") for key in ("dataset_id", "status", "reason", "retry_condition")} | {"terms": found})
    for row in ledger:
        found = hit(" ".join(row.get(key, "") for key in ("candidate_id", "title", "source_url", "reason")))
        if found:
            result["ledger"].append({key: row.get(key, "") for key in ("candidate_id", "width", "status", "title", "reason")} | {"terms": found})
    for width in TRANSFORMER_WIDTH_DIRS:
        for name in downstream_families(width):
            found = hit(name)
            if found:
                result["downstream"].append({"width": width, "family": name, "terms": found})
    if DOWNSTREAM_REGISTRY.exists():
        with DOWNSTREAM_REGISTRY.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                found = hit(" ".join(row.get(key, "") for key in ("dataset_id", "source", "modalities", "notes")))
                if found:
                    result["downstream_registry"].append(
                        {key: row.get(key, "") for key in ("dataset_id", "source", "bitwidth_variants", "status")} | {"terms": found}
                    )
    return result


def list_width(width: int, recipes: list[dict]) -> dict:
    return {
        "width": width,
        "local_accepted": [
            {"dataset_id": recipe["dataset_id"], "name": recipe["name"]}
            for recipe in recipes
            if recipe["layer"] == "datasets" and width in recipe["widths"]
        ],
        "local_staging": [recipe["dataset_id"] for recipe in recipes if recipe["layer"] == "staging" and width in recipe["widths"]],
        "downstream_families": downstream_families(width),
    }


def breadth_lookup(measurement_type: str, instrument: str, archive: str) -> dict:
    rows = load_tsv(BREADTH_KEYS_PATH)
    result = {}
    if measurement_type:
        key = measurement_type.lower()
        result["same_measurement_type"] = [
            row for row in rows
            if row["measurement_type"].lower() == key or key in {t.strip().lower() for t in row.get("other_types", "").split(",")}
        ]
    if instrument:
        result["same_instrument_line"] = [row for row in rows if row["instrument_line"].lower() == instrument.lower()]
    if archive:
        result["same_archive_collection"] = [row for row in rows if row["archive_collection"].lower().rstrip("/") == archive.lower().rstrip("/")]
    return result


def vocabulary() -> list[dict]:
    rows = load_tsv(BREADTH_KEYS_PATH)
    definitions = {row["measurement_type"]: row.get("definition", "") for row in load_tsv(BREADTH_VOCAB_PATH)}
    members: dict[str, list[str]] = {}
    for row in rows:
        members.setdefault(row["measurement_type"], []).append(f"{row['dataset_id']} ({row['widths']})")
    return [{"measurement_type": key, "definition": definitions.get(key, ""), "members": sorted(value)} for key, value in sorted(members.items())]


def print_text(report: dict) -> None:
    if "vocabulary" in report:
        print(f"# measurement types already collected ({len(report['vocabulary'])})")
        for item in report["vocabulary"]:
            print(f"- {item['measurement_type']}: {item['definition']} [{len(item['members'])}] {', '.join(item['members'][:6])}")
        return
    if "breadth" in report:
        for section, rows in report["breadth"].items():
            print(f"# {section} ({len(rows)})")
            for row in rows:
                print(f"- {row['dataset_id']} widths={row['widths']} type={row['measurement_type']} line={row['instrument_line']} "
                      f"archive={row['archive_collection']} origin={row['origin']} verdict={row.get('verdict', '')}")
        return
    if "list_width" in report:
        listing = report["list_width"]
        print(f"# {listing['width']}-bit coverage")
        print(f"\n## local accepted ({len(listing['local_accepted'])})")
        for item in listing["local_accepted"]:
            print(f"- {item['dataset_id']}: {item['name']}")
        print(f"\n## local staging ({len(listing['local_staging'])})")
        print(", ".join(listing["local_staging"]) or "(none)")
        print(f"\n## downstream families ({len(listing['downstream_families'])})")
        print(", ".join(listing["downstream_families"]) or "(none)")
        return
    print("# URL matches")
    if not report["url_matches"]:
        print("(none)")
    for match in report["url_matches"]:
        if match["kind"] == "same_host_only":
            print(f"- {match['query']}: same host only, {match['count']} recipes, e.g. {', '.join(match['examples'])}")
        else:
            print(
                f"- {match['query']}: {match['kind']} ({match['common_path_segments']} segments) "
                f"{match['layer']}:{match['dataset_id']} widths={match['widths']} url={match['matched_url']}"
            )
    terms = report["term_matches"]
    for section in ("recipes", "registry", "ledger", "downstream", "downstream_registry"):
        print(f"\n# term matches: {section}")
        if not terms[section]:
            print("(none)")
        for item in terms[section]:
            print("- " + json.dumps(item, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", action="append", default=[], help="source/landing/resource URL (repeatable)")
    parser.add_argument("--terms", nargs="*", default=[], help="case-insensitive substrings to search")
    parser.add_argument("--list-width", type=int, choices=sorted(TRANSFORMER_WIDTH_DIRS), help="list local and downstream coverage at a width")
    parser.add_argument("--vocabulary", action="store_true", help="measurement types already collected, with members")
    parser.add_argument("--type", default="", help="families with this measurement_type, at any width")
    parser.add_argument("--instrument", default="", help="families with this instrument_line")
    parser.add_argument("--archive", default="", help="families from this archive_collection")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    recipes = load_recipes(REPO_ROOT / "datasets", "datasets") + load_recipes(REPO_ROOT / "staging", "staging")
    if args.vocabulary:
        report: dict = {"vocabulary": vocabulary()}
    elif args.type or args.instrument or args.archive:
        report = {"breadth": breadth_lookup(args.type, args.instrument, args.archive)}
    elif args.list_width:
        report = {"list_width": list_width(args.list_width, recipes)}
    else:
        if not args.url and not args.terms:
            parser.error("give --url and/or --terms, --list-width, --vocabulary, or --type/--instrument/--archive")
        report = {
            "url_matches": url_matches(args.url, recipes),
            "term_matches": term_matches(args.terms, recipes, load_tsv(REGISTRY_PATH), load_tsv(LEDGER_PATH)),
        }
    if args.json:
        print(json.dumps(report, indent=1, ensure_ascii=False))
    else:
        print_text(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
