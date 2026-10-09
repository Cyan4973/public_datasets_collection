#!/usr/bin/env bash
# Fetch one fixed 12 MiB byte-range prefix of each of the 30 PacBio Revio
# hifi_reads BAMs in the WUSTL HPRC Fiber-seq submission (AWS Open Data,
# s3://human-pangenomics, CC0-1.0), plus the AWS registry entry that states
# the license. Each full object is pinned by size and S3 ETag (HEAD request);
# each prefix is fetched with resumable offset range requests.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="hprc_revio_fiberseq_hifi_pulse_width_u8"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

BUCKET_URL="https://human-pangenomics.s3.us-west-2.amazonaws.com"
SUBMISSION="submissions/4f00ec2d-4533-40e3-b0ca-624ab5a559d9--WUSTL_HPRC_PacBio_FiberSeq"
REGISTRY_URL="https://raw.githubusercontent.com/awslabs/open-data-registry/main/datasets/hpgp-data.yaml"
BAM_LIST="$RECIPE_DIR/scripts/bams.tsv"
# Fixed prefix per BAM: bytes 0..12582911 (12 MiB). 30 x 12 MiB = 377,487,360 bytes.
PREFIX_BYTES=12582912
EXPECTED_FILES=30

# 1. License evidence: the AWS Open Data registry entry for the bucket.
REGISTRY_YAML="$DOWNLOAD_DIR/hpgp-data.yaml"
curl -fsSL --retry 5 --retry-delay 5 --max-time 120 --max-filesize 1000000 \
  -o "$REGISTRY_YAML.part" "$REGISTRY_URL"
mv "$REGISTRY_YAML.part" "$REGISTRY_YAML"
grep -q '^License: "\[Creative Commons CC0 1.0 Universal\]' "$REGISTRY_YAML" \
  || { echo "registry entry no longer states CC0 1.0" >&2; exit 1; }
grep -q 'arn:aws:s3:::human-pangenomics' "$REGISTRY_YAML" \
  || { echo "registry entry no longer covers arn:aws:s3:::human-pangenomics" >&2; exit 1; }
echo "license_check=ok CC0-1.0 bucket=human-pangenomics"

n_listed="$(tail -n +2 "$BAM_LIST" | grep -c .)"
[[ "$n_listed" == "$EXPECTED_FILES" ]] || { echo "bams.tsv lists $n_listed files, expected $EXPECTED_FILES" >&2; exit 1; }

fetch_prefix() {
  # fetch_prefix URL TARGET: resumable offset-range transfer of PREFIX_BYTES.
  local url="$1" target="$2" part="$2.part" attempt=0 have want rc got chunk headers
  touch "$part"
  while :; do
    have="$(wc -c < "$part" | tr -d ' ')"
    if (( have == PREFIX_BYTES )); then break; fi
    if (( have > PREFIX_BYTES )); then echo "partial file larger than prefix: $have" >&2; return 1; fi
    attempt=$((attempt + 1))
    if (( attempt > 40 )); then echo "giving up after $((attempt - 1)) attempts at $have bytes" >&2; return 1; fi
    want=$((PREFIX_BYTES - have))
    chunk="$part.chunk"
    headers="$part.headers"
    rm -f "$chunk" "$headers"
    set +e
    curl -fsSL --speed-limit 1024 --speed-time 120 --connect-timeout 60 \
      --max-filesize "$want" -r "$have-$((PREFIX_BYTES - 1))" \
      -D "$headers" -o "$chunk" "$url"
    rc=$?
    set -e
    got=0
    [[ -f "$chunk" ]] && got="$(wc -c < "$chunk" | tr -d ' ')"
    # Only append bytes from a 206 whose Content-Range starts at our offset.
    if grep -qiE "^content-range: bytes $have-" "$headers" 2>/dev/null && (( got <= want )); then
      if (( got > 0 )); then cat "$chunk" >> "$part"; fi
    else
      echo "response is not a 206 at offset $have (rc=$rc); discarding $got bytes" >&2
    fi
    rm -f "$chunk" "$headers"
    if (( rc != 0 )); then sleep 5; fi
  done
  mv "$part" "$target"
}

# 2. Per BAM: pin the full object (HEAD: size + ETag), then fetch its prefix.
INVENTORY_TSV="$DOWNLOAD_DIR/prefix_inventory.tsv"
printf 'ordinal\tsample\tmovie\tkey\tfull_size_bytes\tetag\tprefix_file\tprefix_bytes\tprefix_sha256\n' > "$INVENTORY_TSV.part"
while IFS=$'\t' read -r ordinal sample movie key size etag <&3; do
  [[ "$ordinal" == "ordinal" ]] && continue
  url="$BUCKET_URL/$SUBMISSION/$key"
  target="$DOWNLOAD_DIR/${ordinal}_${sample}_${movie}.hifi_reads.prefix_${PREFIX_BYTES}.bam"
  head_out="$(curl -sSIL --retry 5 --retry-delay 5 --max-time 120 "$url" | tr -d '\r')"
  got_size="$(printf '%s\n' "$head_out" | grep -i '^content-length:' | tail -1 | awk '{print $2}')"
  got_etag="$(printf '%s\n' "$head_out" | grep -i '^etag:' | tail -1 | awk '{print $2}' | tr -d '"')"
  if [[ "$got_size" != "$size" || "$got_etag" != "$etag" ]]; then
    echo "object changed upstream: $key size=$got_size (pinned $size) etag=$got_etag (pinned $etag)" >&2
    exit 1
  fi
  if [[ -f "$target" && "$(wc -c < "$target" | tr -d ' ')" == "$PREFIX_BYTES" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "[$(date -Is)] cache_hit $ordinal $sample $movie"
  else
    # Liveness: a one-byte range request must answer 206.
    code="$(curl -sSL -r 0-0 -o /dev/null -w '%{http_code}' --max-time 60 "$url" || true)"
    [[ "$code" == "206" ]] || { echo "liveness check failed for $key: HTTP $code" >&2; exit 1; }
    echo "[$(date -Is)] fetch $ordinal $sample $movie bytes=0-$((PREFIX_BYTES - 1))"
    fetch_prefix "$url" "$target"
  fi
  sha="$(sha256sum "$target" | awk '{print $1}')"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$ordinal" "$sample" "$movie" "$key" "$size" "$etag" \
    "$(basename "$target")" "$PREFIX_BYTES" "$sha" >> "$INVENTORY_TSV.part"
done 3< "$BAM_LIST"
mv "$INVENTORY_TSV.part" "$INVENTORY_TSV"

# 3. Semantic validation: every prefix is a BGZF BAM whose header matches the
#    regime contract and whose first records carry B:C fp/rp arrays.
DOWNLOAD_DIR="$DOWNLOAD_DIR" SCRIPTS="$RECIPE_DIR/scripts" PREFIX_BYTES="$PREFIX_BYTES" python3 -I -B - <<'PY'
import csv, os, sys
sys.path.insert(0, os.environ["SCRIPTS"])
import hifi_bam as hb
ddir = os.environ["DOWNLOAD_DIR"]
prefix_bytes = int(os.environ["PREFIX_BYTES"])
rows = list(csv.DictReader(open(os.path.join(ddir, "prefix_inventory.tsv"), encoding="utf-8"), delimiter="\t"))
if len(rows) != 30:
    raise SystemExit(f"inventory has {len(rows)} rows, expected 30")
nonconforming = 0
for r in rows:
    path = os.path.join(ddir, r["prefix_file"])
    data = open(path, "rb").read()
    if len(data) != prefix_bytes:
        raise SystemExit(f"{path}: size {len(data)} != {prefix_bytes}")
    rd = hb.BamPrefixReader(data[: 2 * 1024 * 1024])
    text = rd.read_header()
    problems = hb.header_problems(text, r["sample"], r["movie"])
    if problems:
        nonconforming += 1
        print(f"WARNING {r['ordinal']} {r['sample']}: header differs, build.sh will skip it: {problems}")
        continue
    n = 0
    for rec in rd.records():
        for tag in ("fp", "rp"):
            typ, arr = rec["aux"].get(tag, (None, b""))
            if typ != "BC" or len(arr) not in (0, rec["l_seq"]):
                raise SystemExit(f"{r['ordinal']} record {n}: {tag} is {typ} len {len(arr)} vs l_seq {rec['l_seq']}")
        n += 1
    if n < 5:
        raise SystemExit(f"{r['ordinal']}: only {n} complete records in the first 2 MiB")
    print(f"bam_ok {r['ordinal']} {r['sample']} {r['movie']} first2MiB_records={n} sha256={r['prefix_sha256'][:16]}")
if nonconforming == len(rows):
    raise SystemExit("no BAM matches the header contract")
print(f"semantic_validation=ok files={len(rows)} nonconforming={nonconforming}")
PY

total="$(du -cb "$DOWNLOAD_DIR"/*.bam | tail -1 | awk '{print $1}')"
echo "[$(date -Is)] download done dataset=$DATASET_ID prefix_bytes_total=$total"
