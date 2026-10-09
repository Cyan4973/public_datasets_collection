#!/usr/bin/env bash
# Download the NIH ChestX-ray14 licence evidence (FAQ_CHESTXRAY.pdf) and a
# bounded 14 MiB prefix of each of the 12 official images_NNN.tar.gz tarballs
# from the NIH Clinical Center Box share. Box static links answer HEAD with 404
# and redirect GETs to short-lived signed public.boxcloud.com URLs, so every
# request starts again from the static link with -L and a byte Range.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="nihcc_chestxray14_frontal_radiograph_png_u8"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SCRIPTS="$RECIPE_DIR/scripts"
UA="openzl-public-datasets-chestxray14/1.0"
export PYTHONDONTWRITEBYTECODE=1

STATIC_BASE="https://nihcc.box.com/shared/static"
PREFIX_BYTES=$((14 * 1024 * 1024))
FAQ_URL="https://nihcc.app.box.com/index.php?rm=box_download_shared_file&vanity_name=ChestXray-NIHCC&file_id=f_249502714403"
FAQ_BYTES=72223
FAQ_SHA256="674665256e6a14c8ebaa93648f438c2b4ca21205167839559bab3ecc89b6b83a"

# tarball|static-link hash|full size (Content-Range total, 2026-10-08)
TARBALLS=(
  "images_001.tar.gz|vfk49d74nhbxq3nqjg0900w5nvkorp5c|2008470987"
  "images_002.tar.gz|i28rlmbvmfjbl8p2n3ril0pptcmcu9d1|3952623504"
  "images_003.tar.gz|f1t00wrtdk94satdfb9olcolqx20z2jp|3929234850"
  "images_004.tar.gz|0aowwzs5lhjrceb3qp67ahp0rd1l1etg|3838903983"
  "images_005.tar.gz|v5e3goj22zr6h8tzualxfsqlqaygfbsn|3935496531"
  "images_006.tar.gz|asi7ikud9jwnkrnkj99jnpfkjdes7l6l|3986301172"
  "images_007.tar.gz|jn1b4mw4n6lnh74ovmcjb8y48h8xj07n|4016328426"
  "images_008.tar.gz|tvpxmn7qyrgl0w8wfh9kqfjskv6nmm1j|4018347353"
  "images_009.tar.gz|upyy3ml7qdumlgk2rfcvlb9k6gvqq2pj|4111327929"
  "images_010.tar.gz|l6nilvfa9cg3s28tqv1qc1olm3gnz54p|4181556296"
  "images_011.tar.gz|hhq8fkdgvcari67vfhs7ppg2w6ni4jze|4187084020"
  "images_012.tar.gz|ioqwiy20ihqwyr8pf4c24eazhh281pbu|2914187733"
)

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID prefix_bytes=$PREFIX_BYTES"

size_of() { stat -L -c %s "$1"; }
sha256_of() { sha256sum "$1" | awk '{print $1}'; }

# Cross-check the shell constants against scripts/nih_pins.py.
python3 - "$SCRIPTS" "$PREFIX_BYTES" "$FAQ_SHA256" "$FAQ_BYTES" "${TARBALLS[@]}" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import nih_pins as pins
prefix, faq_sha, faq_bytes = int(sys.argv[2]), sys.argv[3], int(sys.argv[4])
specs = [tuple(s.split("|")) for s in sys.argv[5:]]
pinned = [(n, h, str(s)) for n, h, s, _md5 in pins.TARBALLS]
if prefix != pins.PREFIX_BYTES or faq_sha != pins.FAQ_SHA256 or faq_bytes != pins.FAQ_BYTES or specs != pinned:
    raise SystemExit("FATAL: download.sh constants disagree with scripts/nih_pins.py")
print("pins_consistent=ok")
PY

# 1. Licence evidence: FAQ_CHESTXRAY.pdf (Q04 'usage ... is unrestricted').
faq="$DOWNLOAD_DIR/FAQ_CHESTXRAY.pdf"
if [ -f "$faq" ] && [ "$(size_of "$faq")" = "$FAQ_BYTES" ] && [ "$(sha256_of "$faq")" = "$FAQ_SHA256" ]; then
  echo "cache_hit file=FAQ_CHESTXRAY.pdf"
else
  rm -f "$faq" "$faq.part"
  curl --fail --silent --show-error --location \
    --retry 5 --retry-delay 5 --retry-all-errors \
    --max-time 300 --max-filesize 1000000 \
    --user-agent "$UA" --output "$faq.part" "$FAQ_URL"
  mv "$faq.part" "$faq"
fi
python3 "$SCRIPTS/faq_check.py" "$faq"

# 2. Bounded tarball prefixes.
fetch_prefix() {
  local name="$1" hash="$2" full="$3"
  local dest="$DOWNLOAD_DIR/${name%.tar.gz}.prefix${PREFIX_BYTES}.tar.gz"
  local part="$dest.part" piece="$dest.piece" hdr="$dest.headers"
  local url="$STATIC_BASE/$hash.gz"
  if [ -f "$dest" ] && [ "$(size_of "$dest")" = "$PREFIX_BYTES" ]; then
    echo "cache_hit file=$(basename "$dest")"
    return 0
  fi
  rm -f "$dest"
  [ -f "$part" ] || : >"$part"
  if [ "$(size_of "$part")" -gt "$PREFIX_BYTES" ]; then
    echo "discarding oversized partial $part"
    : >"$part"
  fi
  local attempt=0
  while [ "$(size_of "$part")" -lt "$PREFIX_BYTES" ]; do
    attempt=$((attempt + 1))
    if [ "$attempt" -gt 8 ]; then
      echo "FATAL: $name prefix still incomplete after 8 attempts ($(size_of "$part") bytes); re-run to resume" >&2
      return 1
    fi
    local have want last
    have="$(size_of "$part")"
    last=$((PREFIX_BYTES - 1))
    want=$((PREFIX_BYTES - have))
    echo "fetch file=$name range=$have-$last attempt=$attempt"
    rm -f "$piece" "$hdr"
    # --max-filesize aborts before transfer if the server ignored Range and
    # announced the whole multi-GB object.
    local code
    code="$(curl --fail --location --silent --show-error \
      --retry 5 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 \
      --range "$have-$last" --max-filesize "$want" \
      --user-agent "$UA" --dump-header "$hdr" --output "$piece" \
      --write-out '%{http_code}' "$url")" || { echo "curl failed for $name (attempt $attempt)"; sleep 5; continue; }
    local disposition range_line
    disposition="$(tr -d '\r' <"$hdr" | grep -i '^content-disposition:' | tail -n 1 || true)"
    range_line="$(tr -d '\r' <"$hdr" | grep -i '^content-range:' | tail -n 1 | sed 's/^[^:]*: *//' || true)"
    if [ "$code" != "206" ]; then
      echo "FATAL: $name answered HTTP $code instead of 206 Partial Content" >&2
      rm -f "$piece"
      return 1
    fi
    case "$disposition" in
      *"filename=\"$name\""*) ;;
      *) echo "FATAL: $name Content-Disposition is '$disposition'" >&2; rm -f "$piece"; return 1 ;;
    esac
    local got_end got_total
    got_total="${range_line##*/}"
    if [ "$got_total" != "$full" ]; then
      echo "FATAL: $name full size is now '$got_total' (pinned $full); upstream changed" >&2
      rm -f "$piece"
      return 1
    fi
    case "$range_line" in
      "bytes $have-"*) ;;
      *) echo "FATAL: $name Content-Range '$range_line' does not start at $have" >&2; rm -f "$piece"; return 1 ;;
    esac
    got_end="${range_line#bytes $have-}"
    got_end="${got_end%%/*}"
    if [ "$got_end" -gt "$last" ] || [ "$(size_of "$piece")" -gt "$want" ]; then
      echo "FATAL: $name returned more than the requested range" >&2
      rm -f "$piece"
      return 1
    fi
    cat "$piece" >>"$part"
    rm -f "$piece"
  done
  rm -f "$hdr"
  if [ "$(size_of "$part")" != "$PREFIX_BYTES" ]; then
    echo "FATAL: $name prefix is $(size_of "$part") bytes" >&2
    return 1
  fi
  mv "$part" "$dest"
  echo "downloaded file=$(basename "$dest") bytes=$PREFIX_BYTES sha256=$(sha256_of "$dest")"
}

for spec in "${TARBALLS[@]}"; do
  IFS='|' read -r name hash full <<<"$spec"
  fetch_prefix "$name" "$hash" "$full"
  dest="$DOWNLOAD_DIR/${name%.tar.gz}.prefix${PREFIX_BYTES}.tar.gz"
  # Semantic checks: gzip magic, ustar header checksums, member names, PNG
  # signatures/IHDR, at least 20 whole 1024x1024 8-bit grayscale members.
  if ! python3 "$SCRIPTS/nih_decode.py" check-prefix "$dest"; then
    echo "FATAL: $(basename "$dest") failed validation; removed" >&2
    rm -f "$dest"
    exit 1
  fi
  # Enforce a recorded prefix SHA-256 once one is pinned.
  python3 - "$SCRIPTS" "$name" "$(sha256_of "$dest")" <<'PY' || { rm -f "$dest"; exit 1; }
import sys
sys.path.insert(0, sys.argv[1])
import nih_pins as pins
pinned = pins.PREFIX_SHA256.get(sys.argv[2])
if pinned and pinned != sys.argv[3]:
    raise SystemExit(f"FATAL: {sys.argv[2]} prefix sha256 {sys.argv[3]} != pinned {pinned}")
print(f"prefix_sha256 file={sys.argv[2]} sha256={sys.argv[3]} pinned={'yes' if pinned else 'not yet'}")
PY
done

echo "[$(date -Is)] download done dataset=$DATASET_ID"
