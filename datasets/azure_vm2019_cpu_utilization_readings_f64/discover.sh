#!/usr/bin/env bash
# Documents how the pinned resources were resolved. Metadata-only: one GitHub
# release API call, the license API, and three 64 KiB head ranges. Prints to
# stdout; writes only to a temporary directory that it removes.
set -euo pipefail

REPO="Azure/AzurePublicDataset"
TAG="dataset-v2"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/azure_v2_discover.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

curl -fsSL --retry 3 --retry-delay 5 --retry-all-errors --max-time 120 "https://api.github.com/repos/$REPO/releases/tags/$TAG" -o "$TMP/release.json"
curl -fsSL --retry 3 --retry-delay 5 --retry-all-errors --max-time 60 "https://api.github.com/repos/$REPO/license" -o "$TMP/license.json"
python3 - "$TMP/release.json" "$TMP/license.json" <<'PY'
import json
import sys

release = json.load(open(sys.argv[1], encoding="utf-8"))
lic = json.load(open(sys.argv[2], encoding="utf-8"))
print(f"license path={lic['path']} spdx={lic['license']['spdx_id']} blob={lic['sha']}")
print(f"release id={release['id']} tag={release['tag_name']} published={release['published_at']}")
cpu = sorted(
    (a for a in release["assets"] if "vm_cpu_readings-file-" in a["name"]),
    key=lambda a: int(a["name"].split("file-")[1].split("-of-")[0]),
)
print(f"vm_cpu_readings assets={len(cpu)} total_bytes={sum(a['size'] for a in cpu)}")
for asset in release["assets"]:
    if asset["name"] == "schema.csv" or asset in cpu[:3]:
        print(f"{asset['name']}\t{asset['id']}\t{asset['size']}\t{asset['digest']}")
PY

for n in 1 2 3; do
  url="https://github.com/$REPO/releases/download/$TAG/trace_data_vm_cpu_readings_vm_cpu_readings-file-$n-of-195.csv.gz"
  curl -fsSL --retry 3 --retry-delay 5 --retry-all-errors --max-time 120 --range 0-65535 -o "$TMP/head$n.gz" "$url"
  python3 - "$TMP/head$n.gz" "$n" <<'PY'
import hashlib
import sys
import zlib

raw = open(sys.argv[1], "rb").read()
rows = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw).split(b"\n")
print(f"file-{sys.argv[2]} head sha256={hashlib.sha256(raw).hexdigest()} first_ts={rows[0].split(b',')[0].decode()}")
PY
done
