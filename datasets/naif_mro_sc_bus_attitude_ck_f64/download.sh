#!/usr/bin/env bash
# Fetch only the pinned DAF metadata records, PDS labels, and the 44 pinned
# CK type-3 segment byte ranges listed in sources.tsv (never whole kernels).
#
# Origin: NASA PDS archive MRO-M-SPICE-6-V1.0 (volume MROSP_1000) on the NAIF
# server. Fallback: the USGS Astrogeology anonymous mirror, whose copies carry
# byte-identical segment arrays at addresses shifted by the PDS label records;
# both address sets are pinned. Each kernel's pieces come from one host.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DATA_DIR="${DATA_DIR:-${REPO_ROOT}/.data}"
DATASET_ID="naif_mro_sc_bus_attitude_ck_f64"
SOURCES="${SCRIPT_DIR}/sources.tsv"
HELPER="${SCRIPT_DIR}/scripts/ck_download_check.py"
PDS_BASE="https://naif.jpl.nasa.gov/pub/naif/pds/data/mro-m-spice-6-v1.0/mrosp_1000/data/ck"
MIRROR_BASE="https://asc-isisdata.s3.us-west-2.amazonaws.com/usgs_data/mro/kernels/ck"
DL="${DATA_DIR}/downloads/${DATASET_ID}"
LOG_DIR="${DATA_DIR}/logs/${DATASET_ID}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-12}"
export PYTHONDONTWRITEBYTECODE=1

mkdir -p "${DL}/labels" "${DL}/headers" "${DL}/segments" "${LOG_DIR}"
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
exec > >(tee "${LOG_DIR}/download.${RUN_TS}.log" "${LOG_DIR}/download.latest.log") 2>&1
echo "[$(date -u -Is)] download start dataset=${DATASET_ID}"

base_url() {
  case "$1" in
    pds) printf '%s' "${PDS_BASE}" ;;
    mirror) printf '%s' "${MIRROR_BASE}" ;;
    *) echo "unknown host $1" >&2; return 1 ;;
  esac
}

# fetch_range URL FIRST LAST OUT [HDR]
# Exact byte range into OUT via OUT.part. Resumes by requesting only the
# missing tail and appending it (curl -C - cannot be combined with -r: it
# silently drops the range). Only 206 responses whose Content-Range starts at
# the requested offset are appended; stalls are bounded by speed limits.
fetch_range() {
  local url="$1" first="$2" last="$3" out="$4" hdr_out="${5:-}"
  local want=$((last - first + 1))
  local part="${out}.part" chunk="${out}.chunk" hdr="${out}.hdr"
  local attempt=0 have code offset
  [ -f "${part}" ] || : > "${part}"
  while :; do
    have=$(wc -c < "${part}")
    if [ "${have}" -eq "${want}" ]; then
      break
    fi
    if [ "${have}" -gt "${want}" ]; then
      echo "overshoot on ${out}: ${have} > ${want}; discarding partial" >&2
      rm -f "${part}"
      return 1
    fi
    attempt=$((attempt + 1))
    if [ "${attempt}" -gt "${MAX_ATTEMPTS}" ]; then
      echo "giving up on ${url} after ${MAX_ATTEMPTS} attempts (${have}/${want} bytes kept for resume)" >&2
      return 1
    fi
    offset=$((first + have))
    rm -f "${chunk}" "${hdr}"
    code=$(curl -sS -L --connect-timeout 30 --speed-limit 1024 --speed-time 120 \
      --max-filesize $((want - have + 65536)) \
      -r "${offset}-${last}" -D "${hdr}" -o "${chunk}" -w '%{http_code}' "${url}") || true
    if [ "${code}" = "206" ] && [ -s "${chunk}" ] \
      && grep -qiE "^content-range: *bytes ${offset}-" "${hdr}"; then
      cat "${chunk}" >> "${part}"
      if [ -n "${hdr_out}" ] && [ "${have}" -eq 0 ]; then
        cp "${hdr}" "${hdr_out}"
      fi
    else
      echo "attempt ${attempt}: HTTP ${code:-none} for ${url} range ${offset}-${last}" >&2
      sleep $((attempt < 6 ? attempt * 5 : 30))
    fi
    rm -f "${chunk}" "${hdr}"
  done
  mv "${part}" "${out}"
}

# Choose the run host: PDS archive if a one-byte range GET works, else mirror.
probe_file="$(python3 "${HELPER}" files "${SOURCES}")"
probe_file="${probe_file%%$'\n'*}"
RUN_HOST=pds
if ! curl -sS -L -f --connect-timeout 30 --max-time 120 -r 0-0 -o /dev/null "${PDS_BASE}/${probe_file}"; then
  echo "PDS archive host not reachable; falling back to the USGS Astrogeology mirror"
  RUN_HOST=mirror
  curl -sS -L -f --connect-timeout 30 --max-time 120 -r 0-0 -o /dev/null "${MIRROR_BASE}/${probe_file}"
fi
echo "run_host=${RUN_HOST}"

: > "${DL}/checksums.sha256.part"
total_segments=0
while IFS= read -r name; do
  stem="${name%.bc}"
  host_file="${DL}/headers/${stem}.host"
  if [ -s "${host_file}" ]; then
    host="$(cat "${host_file}")"
  else
    host="${RUN_HOST}"
  fi
  url="$(base_url "${host}")/${name}"
  filerec="${DL}/headers/${stem}.filerecord"
  summaries="${DL}/headers/${stem}.summaries"
  httphdr="${DL}/headers/${stem}.filerecord.http"
  echo "== ${name} host=${host}"

  # DAF file record (bytes 0..1023) with its HTTP headers (object size).
  if [ ! -s "${filerec}" ] || [ ! -s "${httphdr}" ]; then
    rm -f "${filerec}" "${httphdr}"
    fetch_range "${url}" 0 1023 "${filerec}" "${httphdr}"
  fi
  printf '%s\n' "${host}" > "${host_file}"

  # Follow the DAF summary-record chain (FWARD -> NEXT ... -> 0).
  if [ ! -s "${summaries}" ]; then
    : > "${summaries}.build"
    while :; do
      next="$(python3 "${HELPER}" next-summary "${filerec}" "${summaries}.build")"
      [ "${next}" -eq 0 ] && break
      rec="${DL}/headers/${stem}.summary_${next}"
      fetch_range "${url}" $(((next - 1) * 1024)) $((next * 1024 - 1)) "${rec}"
      cat "${rec}" >> "${summaries}.build"
      rm -f "${rec}"
    done
    mv "${summaries}.build" "${summaries}"
  fi
  python3 "${HELPER}" check-headers "${SOURCES}" "${name}" "${host}" "${filerec}" "${httphdr}" "${summaries}"

  # PDS label (detached .lbl), pinned by sha256; only served by the PDS host.
  if [ "${host}" = "pds" ]; then
    label="${DL}/labels/${stem}.lbl"
    if [ ! -s "${label}" ]; then
      curl -sS -L -f --retry 5 --retry-delay 5 --connect-timeout 30 --max-time 300 \
        --max-filesize 100000 -o "${label}.part" "${PDS_BASE}/${stem}.lbl"
      mv "${label}.part" "${label}"
    fi
    python3 "${HELPER}" check-label "${SOURCES}" "${name}" "${label}"
  fi

  # Pinned segment ranges, one natural CK segment each.
  while read -r ordinal first last; do
    seg="${DL}/segments/${stem}__seg$(printf '%02d' "${ordinal}").be"
    if [ -s "${seg}" ]; then
      if ! digest="$(python3 "${HELPER}" check-segment "${SOURCES}" "${name}" "${ordinal}" "${seg}")"; then
        echo "cached ${seg} failed validation; refetching"
        rm -f "${seg}"
      fi
    fi
    if [ ! -s "${seg}" ]; then
      fetch_range "${url}" "${first}" "${last}" "${seg}"
      if ! digest="$(python3 "${HELPER}" check-segment "${SOURCES}" "${name}" "${ordinal}" "${seg}")"; then
        echo "FATAL: ${seg} is not a valid pinned CK type-3 segment" >&2
        mv "${seg}" "${seg}.rejected"
        exit 1
      fi
    fi
    printf '%s  segments/%s\n' "${digest}" "$(basename "${seg}")" >> "${DL}/checksums.sha256.part"
    echo "segment ok ${name} ordinal=${ordinal} bytes=$((last - first + 1)) sha256=${digest}"
    total_segments=$((total_segments + 1))
  done < <(python3 "${HELPER}" segments "${SOURCES}" "${name}" "${host}")
done < <(python3 "${HELPER}" files "${SOURCES}")

expected_segments=$(($(wc -l < "${SOURCES}") - 1))
if [ "${total_segments}" -ne "${expected_segments}" ]; then
  echo "FATAL: validated ${total_segments} segments, expected ${expected_segments}" >&2
  exit 1
fi
mv "${DL}/checksums.sha256.part" "${DL}/checksums.sha256"
echo "[$(date -u -Is)] download complete segments=${total_segments} bytes=$(du -sb "${DL}" | cut -f1)"
