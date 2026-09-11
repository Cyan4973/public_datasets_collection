#!/usr/bin/env python3
"""Stream and validate Pfam HMMER profiles without emitting sample payloads."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
from pathlib import Path
import statistics
import sys


CANDIDATE_ID = "pfam_profile_hmm_match_emissions_f32"
AMINO_ACIDS = ("A", "C", "D", "E", "F", "G", "H", "I", "K", "L", "M", "N", "P", "Q", "R", "S", "T", "V", "W", "Y")
TRANSITIONS = ("m->m", "m->i", "m->d", "i->m", "i->i", "d->m", "d->d")
MIN_SAMPLE_VALUES = 1_000


def percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    index = round((len(values) - 1) * fraction)
    return sorted(values)[index]


def parse_numeric_tokens(tokens: list[str], expected: int, context: str) -> tuple[int, float, float]:
    if len(tokens) < expected:
        raise ValueError(f"{context}: expected at least {expected} numeric tokens, got {len(tokens)}")
    stars = 0
    minimum = math.inf
    maximum = -math.inf
    for token in tokens[:expected]:
        if token == "*":
            stars += 1
            continue
        try:
            value = float(token)
        except ValueError as exc:
            raise ValueError(f"{context}: invalid numeric token {token!r}") from exc
        if not math.isfinite(value):
            raise ValueError(f"{context}: non-finite numeric token {token!r}")
        minimum = min(minimum, value)
        maximum = max(maximum, value)
    return stars, minimum, maximum


def main() -> int:
    parser = argparse.ArgumentParser()
    repo_root = Path(__file__).resolve().parents[2]
    default_archive = repo_root / ".data" / "downloads" / CANDIDATE_ID / "Pfam-A.hmm.gz"
    default_output = repo_root / ".data" / "discovery" / CANDIDATE_ID
    parser.add_argument("--archive", type=Path, default=default_archive)
    parser.add_argument("--output-dir", type=Path, default=default_output)
    args = parser.parse_args()

    archive = args.archive.resolve()
    output_dir = args.output_dir.resolve()
    if not archive.is_file():
        raise SystemExit(f"missing archive: {archive}; run download.sh first")
    output_dir.mkdir(parents=True, exist_ok=True)

    line_number = 0

    with gzip.open(archive, "rt", encoding="ascii", errors="strict", newline="") as handle:
        def read_line(context: str) -> str:
            nonlocal line_number
            line = handle.readline()
            if not line:
                raise ValueError(f"unexpected EOF while reading {context}")
            line_number += 1
            return line.rstrip("\r\n")

        families: list[dict[str, object]] = []
        while True:
            first = handle.readline()
            if not first:
                break
            line_number += 1
            first = first.rstrip("\r\n")
            if not first:
                continue
            if not first.startswith("HMMER3/"):
                raise ValueError(f"line {line_number}: expected HMMER3 record header, got {first!r}")

            name = ""
            accession = ""
            length = 0
            alphabet: tuple[str, ...] | None = None
            while True:
                line = read_line("profile header")
                parts = line.split()
                if not parts:
                    continue
                key = parts[0]
                if key == "NAME" and len(parts) >= 2:
                    name = parts[1]
                elif key == "ACC" and len(parts) >= 2:
                    accession = parts[1]
                elif key == "LENG" and len(parts) == 2:
                    length = int(parts[1])
                elif key == "HMM":
                    alphabet = tuple(parts[1:])
                    break
                elif key == "//":
                    raise ValueError(f"line {line_number}: record ended before HMM matrix")

            if not name or not accession or length <= 0:
                raise ValueError(
                    f"line {line_number}: incomplete profile header name={name!r} accession={accession!r} length={length}"
                )
            if alphabet != AMINO_ACIDS:
                raise ValueError(f"line {line_number}: unexpected HMM alphabet/order: {alphabet!r}")

            transition_header = tuple(read_line("transition header").split())
            if transition_header != TRANSITIONS:
                raise ValueError(
                    f"line {line_number}: unexpected transition columns: {transition_header!r}"
                )

            compo = read_line("COMPO match emissions").split()
            if not compo or compo[0] != "COMPO":
                raise ValueError(f"line {line_number}: expected COMPO row")
            compo_stars, _, _ = parse_numeric_tokens(compo[1:], 20, f"line {line_number} COMPO")
            insert_stars, _, _ = parse_numeric_tokens(
                read_line("COMPO insert emissions").split(), 20, f"line {line_number} COMPO insert"
            )
            transition_stars, _, _ = parse_numeric_tokens(
                read_line("COMPO transitions").split(), 7, f"line {line_number} COMPO transitions"
            )

            match_stars = 0
            match_min = math.inf
            match_max = -math.inf
            for expected_position in range(1, length + 1):
                match_parts = read_line(f"match row {expected_position}").split()
                if not match_parts or match_parts[0] != str(expected_position):
                    raise ValueError(
                        f"line {line_number}: expected match position {expected_position}, got {match_parts[:1]!r}"
                    )
                stars, row_min, row_max = parse_numeric_tokens(
                    match_parts[1:], 20, f"line {line_number} match row"
                )
                match_stars += stars
                match_min = min(match_min, row_min)
                match_max = max(match_max, row_max)
                stars, _, _ = parse_numeric_tokens(
                    read_line(f"insert row {expected_position}").split(),
                    20,
                    f"line {line_number} insert row",
                )
                insert_stars += stars
                stars, _, _ = parse_numeric_tokens(
                    read_line(f"transition row {expected_position}").split(),
                    7,
                    f"line {line_number} transition row",
                )
                transition_stars += stars

            terminator = read_line("record terminator").strip()
            if terminator != "//":
                raise ValueError(f"line {line_number}: expected // terminator, got {terminator!r}")

            families.append(
                {
                    "name": name,
                    "accession": accession,
                    "profile_length": length,
                    "match_values": length * 20,
                    "match_stars": match_stars,
                    "compo_stars": compo_stars,
                    "insert_stars": insert_stars,
                    "transition_stars": transition_stars,
                    "match_min": None if match_min == math.inf else match_min,
                    "match_max": None if match_max == -math.inf else match_max,
                }
            )
            if len(families) % 1_000 == 0:
                print(f"profiles_scanned={len(families)}", file=sys.stderr, flush=True)

    if len(families) < 25_000:
        raise SystemExit(f"unexpectedly few Pfam profiles: {len(families)}")
    accessions = [str(row["accession"]) for row in families]
    if len(set(accessions)) != len(accessions):
        raise SystemExit("duplicate Pfam accessions found")

    family_table = output_dir / "profile_probe.tsv"
    columns = (
        "name",
        "accession",
        "profile_length",
        "match_values",
        "match_stars",
        "compo_stars",
        "insert_stars",
        "transition_stars",
        "match_min",
        "match_max",
    )
    with family_table.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(families)

    lengths = [int(row["profile_length"]) for row in families]
    finite_families = [row for row in families if int(row["match_stars"]) == 0]
    qualifying = [row for row in finite_families if int(row["match_values"]) >= MIN_SAMPLE_VALUES]
    total_match_values = sum(int(row["match_values"]) for row in families)
    finite_match_values = sum(int(row["match_values"]) for row in finite_families)
    qualifying_values = sum(int(row["match_values"]) for row in qualifying)
    summary = {
        "candidate_id": CANDIDATE_ID,
        "archive_path": str(archive),
        "archive_bytes": archive.stat().st_size,
        "profiles": len(families),
        "profile_length": {
            "minimum": min(lengths),
            "p10": percentile(lengths, 0.10),
            "median": statistics.median(lengths),
            "p90": percentile(lengths, 0.90),
            "maximum": max(lengths),
        },
        "all_match_emissions": {
            "values": total_match_values,
            "float32_bytes": total_match_values * 4,
            "families_with_stars": sum(int(row["match_stars"]) > 0 for row in families),
            "star_tokens": sum(int(row["match_stars"]) for row in families),
        },
        "finite_match_emission_families": {
            "families": len(finite_families),
            "values": finite_match_values,
            "float32_bytes": finite_match_values * 4,
        },
        "qualifying_finite_families": {
            "minimum_sample_values": MIN_SAMPLE_VALUES,
            "families": len(qualifying),
            "values": qualifying_values,
            "float32_bytes": qualifying_values * 4,
            "median_sample_values": statistics.median(
                [int(row["match_values"]) for row in qualifying]
            ) if qualifying else 0,
        },
        "non_primary_sentinels": {
            "compo_stars": sum(int(row["compo_stars"]) for row in families),
            "insert_stars": sum(int(row["insert_stars"]) for row in families),
            "transition_stars": sum(int(row["transition_stars"]) for row in families),
        },
        "probe_table": str(family_table),
    }
    (output_dir / "schema_probe.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if not qualifying:
        raise SystemExit("no finite match-emission families meet the sample-size floor")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, EOFError, UnicodeError, ValueError) as exc:
        raise SystemExit(f"probe failed: {exc}") from exc
