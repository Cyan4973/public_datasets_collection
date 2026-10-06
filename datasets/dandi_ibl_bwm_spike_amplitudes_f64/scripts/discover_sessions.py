#!/usr/bin/env python3
"""Reproduce the deterministic session selection pinned in sessions.tsv.

Documentation tool used by discover.sh only (download/build never call it).

Rule: take the published DANDI:000409 version's processed NWB assets
(`*desc-processed_behavior+ecephys.nwb`) in path order. Read `/general/lab`
from the first asset of every subject; a lab's first processed asset is the
first asset (path order) of its first subject. Walk labs in that order and
keep a lab's first asset if the cumulative stored spike count of the kept
sessions stays at or below SPIKE_BUDGET (500 MB of float64 amplitudes);
stop after MAX_SESSIONS. Labs whose first session does not fit are skipped.

Subcommands:
  plan    resolve lab strings and spike counts over cached 16 KiB blocks;
          exit 3 with block_requests.tsv while blocks are missing
  select  apply the rule, write subject_labs.tsv and selection.tsv, and
          compare the result with sessions.tsv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nwb_hdf5 as H  # noqa: E402

BLOCK = 16384
SPIKE_BUDGET = 62_500_000
MAX_SESSIONS = 3
S3_PREFIX = "https://dandiarchive.s3.amazonaws.com/blobs/"


def load_listing(path: Path) -> list[dict[str, object]]:
    listing = json.loads(path.read_text(encoding="utf-8"))
    results = listing["results"]
    if listing.get("next") is not None or listing.get("count") != len(results):
        raise SystemExit("asset listing is paginated or incomplete; raise page_size")
    assets = sorted(results, key=lambda a: a["path"])
    if not assets or any(not a["path"].endswith("_desc-processed_behavior+ecephys.nwb") for a in assets):
        raise SystemExit("listing contains non-processed assets")
    return assets


def url_of(asset: dict[str, object]) -> str:
    blob = str(asset["blob"])
    return f"{S3_PREFIX}{blob[:3]}/{blob[3:6]}/{blob}"


def first_by_subject(assets: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: dict[str, dict[str, object]] = {}
    for asset in assets:
        seen.setdefault(str(asset["path"]).split("/")[0], asset)
    return list(seen.values())


def probe(work: Path, asset: dict[str, object], want_counts: bool) -> dict[str, object]:
    store = H.BlockStore(work / str(asset["asset_id"]), int(asset["size"]), BLOCK)
    h5 = H.H5File(store, int(asset["size"]))
    result: dict[str, object] = {
        "lab": h5.scalar_string(h5.resolve("/general/lab")),
        "institution": h5.scalar_string(h5.resolve("/general/institution")),
    }
    if want_counts:
        result["spikes"] = h5.dataset(h5.resolve("/units/spike_amplitudes_uV"))["shape"][0]
        result["units"] = h5.dataset(h5.resolve("/units/spike_amplitudes_uV_index"))["shape"][0]
    return result


def resolve_all(listing: Path, work: Path) -> tuple[list[tuple[dict, dict]], list[list[object]]]:
    assets = load_listing(listing)
    firsts = first_by_subject(assets)
    requests: list[list[object]] = []
    resolved: list[tuple[dict, dict]] = []
    labs_seen: set[str] = set()
    blocked = False
    for asset in firsts:
        try:
            info = probe(work, asset, want_counts=False)
        except H.MissingBlock as missing:
            requests.append(block_request(asset, missing.index))
            blocked = True
            continue
        if not blocked and info["lab"] not in labs_seen:
            labs_seen.add(str(info["lab"]))
            try:
                info = probe(work, asset, want_counts=True)
                info["lab_first"] = True
            except H.MissingBlock as missing:
                requests.append(block_request(asset, missing.index))
                continue
        resolved.append((asset, info))
    return resolved, requests


def block_request(asset: dict[str, object], index: int) -> list[object]:
    start = index * BLOCK
    end = min(int(asset["size"]), start + BLOCK) - 1
    return [asset["asset_id"], index, start, end, url_of(asset), asset["size"]]


def command_plan(args: argparse.Namespace) -> int:
    _, requests = resolve_all(args.listing, args.work)
    with (args.work / "block_requests.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["asset_id", "block", "start", "end", "url", "total"])
        writer.writerows(requests)
    if requests:
        print(f"discover_plan need_blocks={len(requests)}")
        return 3
    print("discover_plan complete")
    return 0


def command_select(args: argparse.Namespace) -> int:
    resolved, requests = resolve_all(args.listing, args.work)
    if requests:
        raise SystemExit("run plan until complete first")
    with (args.out_dir / "subject_labs.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["subject_dir", "first_processed_asset_id", "lab", "institution"])
        for asset, info in resolved:
            writer.writerow([str(asset["path"]).split("/")[0], asset["asset_id"], info["lab"], info["institution"]])
    rows = []
    kept: list[str] = []
    cumulative = 0
    for order, (asset, info) in enumerate([pair for pair in resolved if pair[1].get("lab_first")], 1):
        spikes = int(info["spikes"])
        if len(kept) < MAX_SESSIONS and cumulative + spikes <= SPIKE_BUDGET:
            cumulative += spikes
            kept.append(str(asset["asset_id"]))
            decision = "selected"
        else:
            decision = "skipped_budget" if len(kept) < MAX_SESSIONS else "skipped_max_sessions"
        rows.append([order, info["lab"], info["institution"], asset["path"], asset["asset_id"], asset["size"],
                     spikes, info["units"], cumulative, decision])
    with (args.out_dir / "selection.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["lab_order", "lab", "institution", "first_processed_asset_path", "asset_id", "size_bytes",
                         "stored_spikes", "units", "cumulative_selected_spikes", "decision"])
        writer.writerows(rows)
    with (args.recipe_dir / "sessions.tsv").open(encoding="utf-8", newline="") as handle:
        pinned = [row["asset_id"] for row in csv.DictReader(handle, delimiter="\t")]
    print(f"labs={len(rows)} selected={kept} cumulative_spikes={cumulative}")
    if kept != pinned:
        raise SystemExit(f"selection {kept} differs from sessions.tsv {pinned}")
    print("selection matches sessions.tsv")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "select"):
        item = sub.add_parser(name)
        item.add_argument("--listing", type=Path, required=True)
        item.add_argument("--work", type=Path, required=True)
        if name == "select":
            item.add_argument("--out-dir", type=Path, required=True)
            item.add_argument("--recipe-dir", type=Path, required=True)
    args = parser.parse_args()
    return command_plan(args) if args.command == "plan" else command_select(args)


if __name__ == "__main__":
    raise SystemExit(main())
