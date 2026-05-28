#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DATASET_ID="noaa_isd_lite"
DOWNLOAD_ROOT="${DATA_DIR}/downloads/${DATASET_ID}"
HISTORY_DIR="${DOWNLOAD_ROOT}/history"
ISD_DIR="${DOWNLOAD_ROOT}/isd-lite"
LOG_ROOT="${DATA_DIR}/logs/${DATASET_ID}"
FORCE=${FORCE:-0}

YEARS="2021 2022 2023"
BASE_URL="https://www.ncei.noaa.gov/pub/data/noaa/isd-lite"
HISTORY_URL="https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv"
RUN_TS=$(date -u +"%Y%m%dT%H%M%SZ")
LOG_FILE="${LOG_ROOT}/download.${RUN_TS}.log"
LATEST_LOG="${LOG_ROOT}/download.latest.log"
FAILURES_FILE="${DOWNLOAD_ROOT}/download_failures.tsv"

STATIONS='
486980-99999 singapore
967490-99999 jakarta
486470-99999 kuala_lumpur
821110-99999 manaus
637400-99999 nairobi
430030-99999 mumbai
484560-99999 bangkok
652010-99999 lagos
911820-22521 honolulu
941200-99999 darwin
411940-99999 dubai
412170-99999 abu_dhabi
722780-23183 phoenix
623660-99999 cairo
943260-99999 alice_springs
725650-03017 denver
442920-99999 ulaanbaatar
846280-99999 lima
037720-99999 london
071570-99999 paris
476710-99999 tokyo
947670-99999 sydney
875760-99999 buenos_aires
837800-99999 sao_paulo
162420-99999 rome
688160-99999 cape_town
724940-23234 san_francisco
722190-13874 atlanta
583620-99999 shanghai
931190-99999 auckland
725300-94846 chicago
716240-99999 toronto
276120-99999 moscow
545110-99999 beijing
471080-99999 seoul
029740-99999 helsinki
024840-99999 stockholm
726580-14922 minneapolis
123750-99999 warsaw
296340-99999 novosibirsk
474120-99999 sapporo
702730-26451 anchorage
702610-26411 fairbanks
040300-99999 reykjavik
012250-99999 tromso
249590-99999 yakutsk
'

fetch() {
  url=$1
  out=$2
  tmp="${out}.tmp"

  if [ -f "${out}" ] && [ "${FORCE}" != "1" ]; then
    printf 'cached %s\n' "${out}"
    return 0
  fi

  mkdir -p "$(dirname "${out}")"
  rm -f "${tmp}"

  if command -v curl >/dev/null 2>&1; then
    curl -fL --retry 3 --retry-delay 2 -o "${tmp}" "${url}" >>"${LOG_FILE}" 2>&1
  elif command -v wget >/dev/null 2>&1; then
    wget -O "${tmp}" "${url}" >>"${LOG_FILE}" 2>&1
  else
    printf 'error: need curl or wget\n' >&2
    exit 1
  fi

  mv "${tmp}" "${out}"
}

say() {
  printf '%s\n' "$*" | tee -a "${LOG_FILE}"
}

mkdir -p "${HISTORY_DIR}" "${ISD_DIR}" "${LOG_ROOT}"
: > "${LOG_FILE}"
: > "${FAILURES_FILE}"
sync_latest_log() {
  cp "${LOG_FILE}" "${LATEST_LOG}"
}
trap sync_latest_log EXIT

say "dataset=${DATASET_ID}"
say "run_ts=${RUN_TS}"
say "download_root=${DOWNLOAD_ROOT}"
say "log_file=${LOG_FILE}"

if ! fetch "${HISTORY_URL}" "${HISTORY_DIR}/isd-history.csv"; then
  printf 'history\t-\t%s\t%s\n' "${HISTORY_URL}" "${HISTORY_DIR}/isd-history.csv" >> "${FAILURES_FILE}"
  say "failed history download: ${HISTORY_URL}"
  exit 1
fi
say "ok history ${HISTORY_DIR}/isd-history.csv"

for year in ${YEARS}; do
  mkdir -p "${ISD_DIR}/${year}"
done

printf '%s\n' "${STATIONS}" | awk 'NF == 2 { print $1, $2 }' \
  > "${DOWNLOAD_ROOT}/selected_stations.tsv"

printf '%s\n' "${YEARS}" | tr ' ' '\n' | awk 'NF > 0 { print }' \
  > "${DOWNLOAD_ROOT}/selected_years.txt"

failure_count=0
success_count=0
cached_count=0

while IFS=' ' read -r station slug; do
  [ -n "${station}" ] || continue
  [ -n "${slug}" ] || continue
  for year in ${YEARS}; do
    out="${ISD_DIR}/${year}/${station}-${year}.gz"
    url="${BASE_URL}/${year}/${station}-${year}.gz"
    if [ -f "${out}" ] && [ "${FORCE}" != "1" ]; then
      cached_count=$((cached_count + 1))
      say "cached ${station} ${slug} ${year} ${out}"
      continue
    fi
    say "fetch ${station} ${slug} ${year} ${url}"
    if fetch "${url}" "${out}"; then
      success_count=$((success_count + 1))
      say "ok ${station} ${slug} ${year} ${out}"
    else
      failure_count=$((failure_count + 1))
      rm -f "${out}" "${out}.tmp"
      printf '%s\t%s\t%s\t%s\n' "${station}" "${slug}" "${year}" "${url}" >> "${FAILURES_FILE}"
      say "failed ${station} ${slug} ${year} ${url}"
    fi
  done
done < "${DOWNLOAD_ROOT}/selected_stations.tsv"

say "success_count=${success_count}"
say "cached_count=${cached_count}"
say "failure_count=${failure_count}"
say "failures_file=${FAILURES_FILE}"

if [ "${failure_count}" -gt 0 ]; then
  say "download completed with failures"
  exit 1
fi

say "downloaded recipe inputs under ${DOWNLOAD_ROOT}"
