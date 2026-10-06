#!/usr/bin/env bash
# Metadata-only discovery that reproduces selection.tsv for ds004584.
#
# It pages the public S3 listing (continuation tokens), fetches every
# subject's small *_channels.tsv and *_eeg.json sidecar (about 190 KB total),
# keeps subjects whose channel list equals canonical_channels.txt exactly
# (names and order), picks 30 of them at evenly spaced positions over the
# sorted subject ids, and writes a candidate selection.tsv for comparison.
# It never fetches .fdt signal data, .set files, or participants.tsv.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${DISCOVER_OUT:-/tmp/openneuro_ds004584_pd_rest_eeg_f32_discover}"
BUCKET="https://s3.amazonaws.com/openneuro.org"
PREFIX="ds004584/"
UA="openzl-public-datasets-ds004584-eeg/1.0"

mkdir -p "$OUT_DIR/listing" "$OUT_DIR/sidecars"
rm -f "$OUT_DIR"/listing/page_*.xml

cursor=""
page=0
while :; do
  page=$((page + 1))
  url="$BUCKET?list-type=2&prefix=$PREFIX&max-keys=1000"
  if [[ -n "$cursor" ]]; then
    encoded="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$cursor")"
    url="$url&continuation-token=$encoded"
  fi
  curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
    --max-time 120 --user-agent "$UA" --output "$OUT_DIR/listing/page_$page.xml" "$url"
  cursor="$(python3 - "$OUT_DIR/listing/page_$page.xml" <<'PY'
import re
import sys
text = open(sys.argv[1], encoding="utf-8").read()
match = re.search(r"<NextContinuationToken>(.*?)</NextContinuationToken>", text)
print(match.group(1) if match and "<IsTruncated>true</IsTruncated>" in text else "")
PY
)"
  echo "listing page $page fetched"
  [[ -z "$cursor" ]] && break
  [[ "$page" -ge 20 ]] && { echo "too many listing pages" >&2; exit 1; }
done

python3 - "$OUT_DIR" <<'PY'
import html
import json
import re
import sys
from pathlib import Path

out = Path(sys.argv[1])
objects = {}
for page in sorted((out / "listing").glob("page_*.xml")):
    text = page.read_text(encoding="utf-8")
    for block in re.findall(r"<Contents>(.*?)</Contents>", text, re.S):
        key = html.unescape(re.search(r"<Key>(.*?)</Key>", block).group(1))
        size = int(re.search(r"<Size>(\d+)</Size>", block).group(1))
        etag = html.unescape(re.search(r"<ETag>(.*?)</ETag>", block).group(1)).strip('"')
        objects[key] = {"size": size, "etag": etag}
(out / "objects.json").write_text(json.dumps(objects, indent=1, sort_keys=True), encoding="utf-8")
fdt = sorted(k for k in objects if k.endswith("_task-Rest_eeg.fdt"))
print(f"listed_objects={len(objects)} fdt_objects={len(fdt)} fdt_bytes={sum(objects[k]['size'] for k in fdt)}")
with (out / "sidecar_keys.txt").open("w", encoding="utf-8") as handle:
    for key in fdt:
        base = key[: -len("eeg.fdt")]
        handle.write(base + "channels.tsv\n")
        handle.write(base + "eeg.json\n")
PY

while read -r key; do
  name="${key##*/}"
  [[ -s "$OUT_DIR/sidecars/$name" ]] && continue
  curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
    --max-time 60 --user-agent "$UA" --output "$OUT_DIR/sidecars/$name" "$BUCKET/$key"
done < "$OUT_DIR/sidecar_keys.txt"

python3 - "$OUT_DIR" "$RECIPE_DIR/canonical_channels.txt" "$OUT_DIR/selection.tsv" <<'PY'
import csv
import json
import sys
from collections import Counter
from pathlib import Path

out = Path(sys.argv[1])
canonical = tuple(Path(sys.argv[2]).read_text(encoding="utf-8").split())
selection_path = Path(sys.argv[3])
objects = json.loads((out / "objects.json").read_text(encoding="utf-8"))
subjects = sorted(k.split("/")[1] for k in objects if k.endswith("_task-Rest_eeg.fdt"))
sets = Counter()
eligible = []
for subject in subjects:
    with (out / "sidecars" / f"{subject}_task-Rest_channels.tsv").open(encoding="utf-8") as handle:
        names = tuple(row["name"] for row in csv.DictReader(handle, delimiter="\t"))
    sets[len(names), names == canonical] += 1
    if names == canonical:
        eligible.append(subject)
print("channel-set census (count, equals canonical):", dict(sets))
count = 30
positions = [round(i * (len(eligible) - 1) / (count - 1)) for i in range(count)]
chosen = [eligible[i] for i in positions]
columns = ["subject", "fdt_bytes", "fdt_md5", "channels_bytes", "channels_md5", "eeg_json_bytes", "eeg_json_md5", "time_points"]
with selection_path.open("w", encoding="utf-8") as handle:
    handle.write("\t".join(columns) + "\n")
    for subject in chosen:
        base = f"ds004584/{subject}/eeg/{subject}_task-Rest_"
        fdt = objects[base + "eeg.fdt"]
        chan = objects[base + "channels.tsv"]
        side = objects[base + "eeg.json"]
        for item in (fdt, chan, side):
            if "-" in item["etag"]:
                raise SystemExit(f"multipart ETag is not an MD5 for {subject}")
        if fdt["size"] % (4 * len(canonical)):
            raise SystemExit(f"{subject}: fdt size not divisible by 4*nbchan")
        meta = json.loads((out / "sidecars" / f"{subject}_task-Rest_eeg.json").read_text(encoding="utf-8"))
        points = fdt["size"] // (4 * len(canonical))
        if meta.get("EEGChannelCount") != len(canonical) or abs(meta["RecordingDuration"] * 500 - points) > 1:
            raise SystemExit(f"{subject}: sidecar disagrees with fdt geometry")
        row = [subject, fdt["size"], fdt["etag"], chan["size"], chan["etag"], side["size"], side["etag"], points]
        handle.write("\t".join(str(v) for v in row) + "\n")
print(f"eligible={len(eligible)} selected={len(chosen)} selected_fdt_bytes={sum(objects[f'ds004584/{s}/eeg/{s}_task-Rest_eeg.fdt']['size'] for s in chosen)}")
print(f"wrote {selection_path}")
PY

if diff -q "$OUT_DIR/selection.tsv" "$RECIPE_DIR/selection.tsv" >/dev/null; then
  echo "discovered selection matches pinned selection.tsv"
else
  echo "discovered selection differs from pinned selection.tsv:" >&2
  diff "$OUT_DIR/selection.tsv" "$RECIPE_DIR/selection.tsv" >&2 || true
  exit 1
fi
