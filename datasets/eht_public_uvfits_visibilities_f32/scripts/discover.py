#!/usr/bin/env python3
"""Discover licensed UVFITS payloads in official EHT GitHub repositories."""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any
from urllib.parse import quote


API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
ORG = "eventhorizontelescope"
USER_AGENT = "openzl-public-datasets-eht-uvfits-f32-discovery/1.0"
MAX_METADATA_BYTES = 20_000_000
MAX_DOCUMENT_BYTES = 2_000_000
MAX_DATA_BYTES = 1_000_000_000
PERMISSIVE_SPDX = {
    "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "CC-BY-3.0", "CC-BY-4.0",
    "CC0-1.0", "MIT", "PDDL-1.0",
}
LICENSE_MARKERS = (
    "data files in this data set are licensed under the odc-pddl license",
    "opendatacommons.org/licenses/pddl", "odc-pddl",
    "cc by 4.0", "cc-by-4.0", "creative commons attribution 4.0",
    "creativecommons.org/licenses/by/4.0", "cc0 1.0", "cc0-1.0",
    "creativecommons.org/publicdomain/zero/1.0", "apache license, version 2.0",
    "bsd 3-clause", "mit license",
)


def curl_bytes(url: str) -> bytes:
    command = [
        "curl", "--fail-with-body", "--silent", "--show-error", "--location",
        "--retry", "4", "--retry-all-errors", "--retry-delay", "2",
        "--connect-timeout", "30", "--max-time", "180",
        "--max-filesize", str(MAX_METADATA_BYTES),
        "--header", "Accept: application/vnd.github+json",
        "--header", "X-GitHub-Api-Version: 2022-11-28",
        "--user-agent", USER_AGENT,
    ]
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        command.extend(("--header", f"Authorization: Bearer {token}"))
    command.append(url)
    result = subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        body = result.stdout.decode("utf-8", errors="replace").strip()[:1_000]
        suffix = f" response={body}" if body else ""
        raise RuntimeError(f"curl failed rc={result.returncode}: {detail}{suffix}")
    if len(result.stdout) > MAX_METADATA_BYTES:
        raise RuntimeError("GitHub response exceeded metadata cap")
    return result.stdout


def curl_json(url: str) -> Any:
    return json.loads(curl_bytes(url))


def repo_relevant(repo: dict[str, Any]) -> bool:
    combined = " ".join(
        str(repo.get(key) or "") for key in ("name", "description", "homepage", "topics")
    ).lower()
    return bool(
        re.search(r"(?:^|\b)20(?:17|18|19|20|21|22|23|24)-d\d", combined)
        or any(term in combined for term in ("data release", "m87", "sgr a", "visibility", "uvfits"))
    )


def visibility_path(path: str) -> bool:
    lowered = path.lower()
    name = PurePosixPath(lowered).name
    if name.endswith((".uvfits", ".uvf", ".uvfits.gz", ".uvf.gz")):
        return True
    return name.endswith((".fits", ".fits.gz", ".fit", ".fit.gz")) and any(
        term in lowered for term in ("uv", "visib", "network_cal", "hops", "stokes")
    )


def documentation_path(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return (
        name.startswith(("readme", "license", "licence", "copying"))
        or "data_policy" in name
        or "data-license" in name
    )


def permissive_evidence(repo: dict[str, Any], documents: dict[str, str]) -> tuple[bool, str]:
    license_object = repo.get("license", {})
    spdx = str(license_object.get("spdx_id") or "") if isinstance(license_object, dict) else ""
    combined = "\n".join(documents.values()).lower().replace("_", "-")
    marker = next((value for value in LICENSE_MARKERS if value in combined), "")
    if marker:
        return True, f"document:{marker}"
    if spdx in PERMISSIVE_SPDX:
        return True, f"repository_spdx:{spdx}"
    return False, f"repository_spdx:{spdx or 'none'}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--reuse-existing",
        action="store_true",
        help="reprocess previously saved repository metadata without network access",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    repo_dir = args.output_dir / "repositories"
    repo_dir.mkdir(parents=True, exist_ok=True)

    saved_bundles: dict[str, dict[str, Any]] = {}
    repositories: list[dict[str, Any]] = []
    if args.reuse_existing:
        for path in sorted(repo_dir.glob("*.json")):
            bundle = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(bundle, dict) or not isinstance(bundle.get("repository"), dict):
                raise SystemExit(f"malformed saved repository metadata: {path}")
            repo = bundle["repository"]
            name = str(repo.get("name") or "")
            if not name:
                raise SystemExit(f"saved repository metadata lacks a name: {path}")
            saved_bundles[name] = bundle
            repositories.append(repo)
        if not repositories:
            raise SystemExit("no saved repository metadata is available to reprocess")
    else:
        for page in range(1, 4):
            url = f"{API}/orgs/{ORG}/repos?type=public&sort=full_name&per_page=100&page={page}"
            response = curl_json(url)
            if not isinstance(response, list):
                raise SystemExit("GitHub organization response is not a repository list")
            repositories.extend(repo for repo in response if isinstance(repo, dict))
            if len(response) < 100:
                break

    relevant = repositories if args.reuse_existing else [repo for repo in repositories if repo_relevant(repo)]
    rows: list[dict[str, object]] = []
    repository_summaries: list[dict[str, object]] = []
    errors: list[str] = []
    for repo in relevant:
        name = str(repo.get("name") or "")
        branch = str(repo.get("default_branch") or "main")
        if args.reuse_existing:
            bundle = saved_bundles[name]
            commit = bundle.get("commit", {})
            tree = bundle.get("tree", {})
            documents = bundle.get("documents", {})
            documents = documents if isinstance(documents, dict) else {}
        else:
            try:
                commit = curl_json(f"{API}/repos/{ORG}/{quote(name)}/commits/{quote(branch)}")
                commit_sha = str(commit.get("sha") or "") if isinstance(commit, dict) else ""
                if not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
                    raise RuntimeError("default-branch commit SHA is missing")
                tree = curl_json(f"{API}/repos/{ORG}/{quote(name)}/git/trees/{commit_sha}?recursive=1")
                entries = tree.get("tree", []) if isinstance(tree, dict) else []
                if not isinstance(entries, list):
                    raise RuntimeError("recursive tree has no entries")
                if isinstance(tree, dict) and tree.get("truncated"):
                    raise RuntimeError("recursive repository tree is truncated")
            except Exception as error:
                errors.append(f"{name}: {error}")
                continue

            documents = {}
            document_entries = [
                entry for entry in entries
                if isinstance(entry, dict)
                and entry.get("type") == "blob"
                and documentation_path(str(entry.get("path") or ""))
                and int(entry.get("size") or 0) <= MAX_DOCUMENT_BYTES
            ][:12]
            for entry in document_entries:
                path = str(entry.get("path"))
                url = f"{RAW}/{ORG}/{quote(name)}/{commit_sha}/{quote(path, safe='/')}"
                try:
                    payload = curl_bytes(url)
                    documents[path] = payload.decode("utf-8", errors="replace")
                except Exception as error:
                    errors.append(f"{name}:{path}: {error}")

        commit_sha = str(commit.get("sha") or "") if isinstance(commit, dict) else ""
        if not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
            errors.append(f"{name}: saved/default commit SHA is missing")
            continue
        entries = tree.get("tree", []) if isinstance(tree, dict) else []
        if not isinstance(entries, list):
            errors.append(f"{name}: recursive tree has no entries")
            continue

        licensed, license_evidence = permissive_evidence(repo, documents)
        visibility_entries = [
            entry for entry in entries
            if isinstance(entry, dict)
            and entry.get("type") == "blob"
            and visibility_path(str(entry.get("path") or ""))
        ]
        repository_summaries.append({
            "repository": name,
            "commit": commit_sha,
            "license_evidence": license_evidence,
            "licensed": licensed,
            "visibility_file_count": len(visibility_entries),
        })
        (repo_dir / f"{name}.json").write_text(
            json.dumps(
                {"repository": repo, "commit": commit, "tree": tree, "documents": documents},
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
        if not licensed:
            continue
        for entry in visibility_entries:
            path = str(entry.get("path") or "")
            size = int(entry.get("size") or 0)
            if size > MAX_DATA_BYTES:
                continue
            lowered = path.lower()
            direct_uvfits = lowered.endswith((".uvfits", ".uvf", ".uvfits.gz", ".uvf.gz"))
            score = (100 if direct_uvfits else 40) + (10 if size >= 20_000 else 0)
            notes = ["direct_uvfits" if direct_uvfits else "fits_name_requires_hdu_check"]
            if size < 1_024:
                notes.append("possible_git_lfs_pointer")
            rows.append({
                "score": score,
                "repository": name,
                "commit": commit_sha,
                "license_evidence": license_evidence,
                "path": path,
                "git_blob_size": size,
                "git_blob_sha": str(entry.get("sha") or ""),
                "url": f"{RAW}/{ORG}/{quote(name)}/{commit_sha}/{quote(path, safe='/')}",
                "ranking_notes": ",".join(notes),
            })

    rows.sort(key=lambda row: (-int(row["score"]), -int(row["git_blob_size"]), str(row["repository"]), str(row["path"])))
    candidates_path = args.output_dir / "candidates.tsv"
    fields = (
        "score", "repository", "commit", "license_evidence", "path",
        "git_blob_size", "git_blob_sha", "url", "ranking_notes",
    )
    with candidates_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "candidate_id": "eht_public_uvfits_visibilities_f32",
        "organization": ORG,
        "repositories_examined": len(repositories),
        "relevant_repositories": len(relevant),
        "repository_summaries": repository_summaries,
        "errors": errors,
        "licensed_visibility_files": len(rows),
        "top_candidate": rows[0] if rows else None,
        "next_check": "download one pinned candidate and inspect FITS HDUs, BITPIX/TFORM, axes, flags, and natural sample sizes",
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"candidates={candidates_path}")
    if not rows:
        raise SystemExit("no explicitly licensed visibility payload was found in official EHT repositories")


if __name__ == "__main__":
    main()
