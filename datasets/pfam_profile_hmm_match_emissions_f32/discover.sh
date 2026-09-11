#!/usr/bin/env bash
# Metadata-only discovery for official Pfam-A profile-HMM data.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="pfam_profile_hmm_match_emissions_f32"
RELEASE_BASE="${PFAM_RELEASE_BASE:-https://ftp.ebi.ac.uk/pub/databases/Pfam/current_release}"
ARCHIVE_NAME="Pfam-A.hmm.gz"
ARCHIVE_URL="$RELEASE_BASE/$ARCHIVE_NAME"
OUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
UA="openzl-public-datasets-pfam-profile-hmm-discovery/1.0"

mkdir -p "$OUT_DIR/release_docs" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] metadata discovery start candidate=$CANDIDATE_ID"

curl --fail --silent --show-error --location \
  --retry 5 --retry-delay 2 --retry-all-errors \
  --max-time 180 --max-filesize 5000000 \
  --user-agent "$UA" \
  --output "$OUT_DIR/release_index.html.part" "$RELEASE_BASE/"
mv "$OUT_DIR/release_index.html.part" "$OUT_DIR/release_index.html"

curl --fail --silent --show-error --location --head \
  --retry 5 --retry-delay 2 --retry-all-errors \
  --max-time 180 --user-agent "$UA" \
  --dump-header "$OUT_DIR/archive.headers.part" \
  --output /dev/null "$ARCHIVE_URL"
mv "$OUT_DIR/archive.headers.part" "$OUT_DIR/archive.headers"

python3 - "$OUT_DIR/release_index.html" "$OUT_DIR/release_files.txt" <<'PY'
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import sys
from urllib.parse import unquote, urlparse


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.links.append(value)


source, destination = map(Path, sys.argv[1:])
parser = LinkParser()
parser.feed(source.read_text(encoding="utf-8", errors="replace"))
names = set()
for link in parser.links:
    path = unquote(urlparse(link).path)
    name = Path(path.rstrip("/")).name
    if name and name not in {".", ".."}:
        names.add(name)
destination.write_text("\n".join(sorted(names)) + "\n", encoding="utf-8")
if "Pfam-A.hmm.gz" not in names:
    raise SystemExit("official release index does not list Pfam-A.hmm.gz")
print(f"release_index_files={len(names)} archive_listed=1")
PY

python3 - "$OUT_DIR/archive.headers" "$ARCHIVE_URL" "$OUT_DIR/archive_metadata.json" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import re
import sys


headers_path = Path(sys.argv[1])
archive_url = sys.argv[2]
output_path = Path(sys.argv[3])
text = headers_path.read_text(encoding="iso-8859-1")
responses = re.split(r"(?=^HTTP/)", text, flags=re.MULTILINE)
final = next((part for part in reversed(responses) if part.strip()), "")
status_match = re.search(r"^HTTP/\S+\s+(\d+)", final, flags=re.MULTILINE)
length_match = re.search(
    r"^Content-Length:\s*(\d+)\s*$", final, flags=re.IGNORECASE | re.MULTILINE
)
type_match = re.search(
    r"^Content-Type:\s*([^\r\n]+)", final, flags=re.IGNORECASE | re.MULTILINE
)
modified_match = re.search(
    r"^Last-Modified:\s*([^\r\n]+)", final, flags=re.IGNORECASE | re.MULTILINE
)
etag_match = re.search(
    r"^ETag:\s*([^\r\n]+)", final, flags=re.IGNORECASE | re.MULTILINE
)
status = int(status_match.group(1)) if status_match else 0
size = int(length_match.group(1)) if length_match else 0
if status != 200:
    raise SystemExit(f"unexpected archive HEAD status: {status}")
if size and size < 10_000_000:
    raise SystemExit(f"archive is unexpectedly small: {size} bytes")
metadata = {
    "url": archive_url,
    "http_status": status,
    "size_bytes": size,
    "content_type": type_match.group(1).strip() if type_match else "",
    "last_modified": modified_match.group(1).strip() if modified_match else "",
    "etag": etag_match.group(1).strip() if etag_match else "",
}
output_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(
    f"archive_http_status={status} archive_size_bytes={size} "
    f"last_modified={metadata['last_modified']!r} etag={metadata['etag']!r}"
)
PY

# Fetch only small release-local documentation/checksum files named by the
# directory index. The large HMM archive itself is not downloaded here.
python3 - "$OUT_DIR/release_files.txt" "$OUT_DIR/doc_candidates.txt" <<'PY'
from __future__ import annotations

from pathlib import Path
import re
import sys


names = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
pattern = re.compile(r"(?:readme|license|licence|copying|terms|md5|sha(?:1|256)?|checksum|relnotes)", re.I)
candidates = [name for name in names if pattern.search(name) and "/" not in name]
Path(sys.argv[2]).write_text("\n".join(candidates) + ("\n" if candidates else ""), encoding="utf-8")
print(f"release_doc_candidates={len(candidates)}")
PY

: > "$OUT_DIR/release_docs.tsv"
printf 'name\turl\tstatus\tbytes\n' >> "$OUT_DIR/release_docs.tsv"
while IFS= read -r name; do
  [ -n "$name" ] || continue
  safe_name="$(printf '%s' "$name" | tr -c 'A-Za-z0-9._-' '_')"
  url="$RELEASE_BASE/$name"
  output="$OUT_DIR/release_docs/$safe_name"
  set +e
  curl --fail --silent --show-error --location \
    --retry 2 --retry-delay 1 --retry-all-errors \
    --max-time 90 --max-filesize 2000000 \
    --user-agent "$UA" --output "$output.part" "$url"
  curl_exit=$?
  set -e
  if (( curl_exit == 0 )); then
    mv "$output.part" "$output"
    bytes="$(wc -c < "$output" | tr -d ' ')"
    printf '%s\t%s\tok\t%s\n' "$name" "$url" "$bytes" >> "$OUT_DIR/release_docs.tsv"
  else
    rm -f "$output.part"
    printf '%s\t%s\tfailed:%s\t0\n' "$name" "$url" "$curl_exit" >> "$OUT_DIR/release_docs.tsv"
  fi
done < "$OUT_DIR/doc_candidates.txt"

python3 - "$OUT_DIR" "$ARCHIVE_URL" <<'PY'
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys


out_dir = Path(sys.argv[1])
archive_url = sys.argv[2]
metadata = json.loads((out_dir / "archive_metadata.json").read_text(encoding="utf-8"))
docs = []
license_matches = []
checksum_matches = []
for path in sorted((out_dir / "release_docs").iterdir()):
    if not path.is_file():
        continue
    payload = path.read_bytes()
    text = payload.decode("utf-8", errors="replace")
    normalized = re.sub(r"\s+", " ", text)
    lower = normalized.lower()
    docs.append(
        {
            "name": path.name,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    )
    for pattern in (
        r"creative commons zero",
        r"\bcc0(?:[- ]?1\.0)?\b",
        r"creativecommons\.org/publicdomain/zero/1\.0",
    ):
        match = re.search(pattern, lower)
        if match:
            excerpt = normalized[max(0, match.start() - 180) : match.end() + 240]
            license_matches.append({"document": path.name, "excerpt": excerpt})
            break
    for line in text.splitlines():
        if "Pfam-A.hmm.gz" in line and re.search(r"[0-9a-fA-F]{32,64}", line):
            checksum_matches.append({"document": path.name, "line": line.strip()})

summary = {
    "candidate_id": "pfam_profile_hmm_match_emissions_f32",
    "metadata_only": True,
    "archive": metadata,
    "release_documents": docs,
    "license_expected": "CC0-1.0",
    "release_local_cc0_evidence": license_matches,
    "archive_checksum_evidence": checksum_matches,
    "archive_downloaded": False,
    "proposed_sample_shape": "one variable-length profile_length_by_20 match-emission matrix per Pfam family",
    "proposed_numeric_format": "canonical little-endian IEEE float32",
    "next_step": (
        "write exact pinned download and local HMMER schema probe"
        if license_matches
        else "locate authoritative dataset-specific license evidence before acquisition"
    ),
}
(out_dir / "summary.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps(summary, indent=2, sort_keys=True))
if not docs:
    raise SystemExit("release index exposed no downloadable documentation/checksum files")
if not license_matches:
    raise SystemExit(
        "no release-local document explicitly established CC0; do not download the HMM archive yet"
    )
if not metadata.get("size_bytes"):
    print("warning: archive Content-Length was unavailable; checksum evidence will be required")
if not checksum_matches:
    print("warning: no release-local checksum line for Pfam-A.hmm.gz was found")
print(f"discovery_ok archive_url={archive_url}")
PY

echo "[$(date -Is)] metadata discovery done candidate=$CANDIDATE_ID"
