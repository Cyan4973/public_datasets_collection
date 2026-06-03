#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="openf1_belgium_2023_car_data_native"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
FAILURES_FILE="$DOWNLOAD_DIR/download_failures.tsv"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"
printf 'resource\tstatus\tdetail\n' > "$FAILURES_FILE"

if [ -z "${https_proxy:-}" ] && [ -z "${HTTPS_PROXY:-}" ] \
   && [ -z "${http_proxy:-}" ] && [ -z "${HTTP_PROXY:-}" ]; then
  if getent hosts fwdproxy >/dev/null 2>&1; then
    export https_proxy="http://fwdproxy:8080"
    export http_proxy="http://fwdproxy:8080"
    echo "info: auto-set https_proxy=$https_proxy"
  fi
fi

export DOWNLOAD_DIR FAILURES_FILE
python3 - <<'PY'
from __future__ import annotations

from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

download_dir = Path(os.environ["DOWNLOAD_DIR"])
failures_file = Path(os.environ["FAILURES_FILE"])

USER_AGENT = "openzl-transformer-public-datasets/1.0 (openf1_belgium_2023_car_data_native)"
EXPECTED_SESSION_KEY = 9135


def log_failure(resource: str, detail: str) -> None:
    with failures_file.open("a", encoding="utf-8") as fh:
        fh.write(f"{resource}\tfailed\t{detail}\n")


def fetch_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except (urllib.error.URLError, OSError) as exc:
            last_err = exc
            print(f"warn: attempt {attempt + 1}/3 failed for {url}: {exc}", file=sys.stderr)
    raise SystemExit(f"error: failed to fetch {url}: {last_err}")


def download_via_cli(url: str, out: Path) -> None:
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    if shutil.which("curl"):
        cmd = ["curl", "-L", "--fail", "--show-error", "--retry", "3", "--retry-delay", "5", "-A", USER_AGENT, "--output", str(tmp), url]
    elif shutil.which("wget"):
        cmd = ["wget", "-U", USER_AGENT, "-O", str(tmp), url]
    else:
        tmp.write_bytes(fetch_url(url))
        tmp.replace(out)
        return
    subprocess.run(cmd, check=True)
    tmp.replace(out)


def session_url() -> str:
    return "https://api.openf1.org/v1/sessions?year=2023&country_name=Belgium&session_name=Qualifying"


def drivers_url() -> str:
    return f"https://api.openf1.org/v1/drivers?session_key={EXPECTED_SESSION_KEY}"


def car_data_url(driver_number: int) -> str:
    return f"https://api.openf1.org/v1/car_data?session_key={EXPECTED_SESSION_KEY}&driver_number={driver_number}"


def verify_session_pin() -> None:
    payload = json.loads(fetch_url(session_url()))
    keys = [item.get("session_key") for item in payload]
    if EXPECTED_SESSION_KEY not in keys:
        raise SystemExit(f"error: OpenF1 /v1/sessions no longer returns session_key={EXPECTED_SESSION_KEY}; returned {keys}")
    print(f"verified session_key={EXPECTED_SESSION_KEY}")


def fetch_driver_list() -> list[int]:
    payload = json.loads(fetch_url(drivers_url()))
    drivers = sorted({int(item["driver_number"]) for item in payload})
    if not drivers:
        raise SystemExit("error: OpenF1 /v1/drivers returned an empty list")
    return drivers


def validate_car_data(path: Path) -> tuple[int, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise RuntimeError("expected non-empty JSON array")
    sample = payload[0]
    required = ["date", "driver_number", "speed", "rpm", "throttle", "brake", "n_gear", "drs"]
    missing = [field for field in required if field not in sample]
    if missing:
        raise RuntimeError(f"missing required fields: {missing}")
    return len(payload), str(sample["date"])


def acquire_driver(source_dir: Path | None, driver_number: int, force: bool) -> None:
    out = download_dir / f"car_data_s{EXPECTED_SESSION_KEY}_d{driver_number}.json"
    if out.exists() and not force:
        try:
            count, first_date = validate_car_data(out)
            print(f"cached driver={driver_number} samples={count} first_date={first_date}")
            return
        except Exception as exc:
            print(f"cached file invalid for driver={driver_number}: {exc}")
            out.unlink(missing_ok=True)
    if source_dir is not None:
        src = source_dir / out.name
        if not src.is_file():
            raise SystemExit(f"error: missing local source file: {src}")
        shutil.copyfile(src, out)
    else:
        download_via_cli(car_data_url(driver_number), out)
    count, first_date = validate_car_data(out)
    print(f"downloaded driver={driver_number} samples={count} first_date={first_date}")


def main() -> int:
    source_env = os.environ.get("OPENF1_BELGIUM_2023_CAR_DATA_NATIVE_SOURCE_DIR")
    source_dir = Path(source_env) if source_env else None
    force = os.environ.get("FORCE") == "1"

    if source_dir:
        drivers = sorted({int(path.stem.rsplit("_d", 1)[-1]) for path in source_dir.glob("car_data_s*_d*.json")})
        if not drivers:
            raise SystemExit(f"error: no car_data_*.json under {source_dir}")
    else:
        verify_session_pin()
        drivers = fetch_driver_list()
    print(f"driver roster: {drivers}")

    failures = 0
    for driver_number in drivers:
        try:
            acquire_driver(source_dir, driver_number, force)
        except Exception as exc:
            failures += 1
            log_failure(f"driver_{driver_number}", str(exc).replace("\n", " "))

    return failures


raise SystemExit(main())
PY

if grep -q $'\tfailed\t' "$FAILURES_FILE"; then
  failure_count="$(grep -c $'\tfailed\t' "$FAILURES_FILE")"
else
  failure_count=0
fi
echo "failure_count=$failure_count"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
exit "$failure_count"
