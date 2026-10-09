#!/usr/bin/env python3
"""Autocollect driver: scout -> screen -> author -> download -> build -> judge.

Roles run as headless `claude -p --agent autocollect-<role>` sessions defined
in .claude/agents/. The driver owns every repository mutation outside
staging/<id>/ (ledger, registry, reports, promotion) and makes local commits.
It never pushes.

Committed state (pipeline/):
  baseline.json    accepted recipes per width when collection began
  candidates.tsv   every candidate and its resting status
  cards/<id>.md    scout candidate cards
Runtime state (.data/pipeline/): per-candidate state, agent transcripts,
download/build logs, costs, archived drafts.

Commands:
  driver.py init [--target 50]
  driver.py status
  driver.py activity [--minutes 120] [--lines 8]
  driver.py follow [--backlog 3]
  driver.py run [--agents 3] [--downloads 2] [--widths 8,16] [--stop-after N] [--max-cost-usd X]
  driver.py requeue <candidate_id> [--status queued]
  driver.py approve-breadth <candidate_id> [--note ...]
  driver.py reject <candidate_id> --reason ...
  driver.py unpause
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import dataclasses
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import tomllib
import uuid
from pathlib import Path
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / ".data"
PIPELINE_DIR = REPO_ROOT / "pipeline"
CARDS_DIR = PIPELINE_DIR / "cards"
LEDGER_PATH = PIPELINE_DIR / "candidates.tsv"
BASELINE_PATH = PIPELINE_DIR / "baseline.json"
REGISTRY_PATH = REPO_ROOT / "attempts" / "dataset_status.tsv"
# Breadth registry: one row per family (baseline and autocollect) with its
# measurement type, instrument line and archive collection. The breadth gate
# compares candidates against it across all widths.
BREADTH_KEYS_PATH = PIPELINE_DIR / "breadth_keys.tsv"
BREADTH_COLUMNS = ["dataset_id", "origin", "widths", "measurement_type", "instrument_line", "archive_collection", "other_types", "verdict"]
COUNTED_VERDICTS = {"STRONG", "OK"}
ZLSIM = [sys.executable, "tools/autocollect/zlsim.py"]
ZLSIM_ENV = {"ZLSIM_PARETO_TIMEOUT_S": "600"}
# Hosts serving many unrelated collections are not one archive: these match
# with their subdomains (ndownloader.figshare.com, raw.githubusercontent.com),
# path-style object stores only exactly (per-bucket hosts stay one archive).
MULTI_TENANT_SUFFIXES = {"zenodo.org", "figshare.com", "github.com", "githubusercontent.com", "huggingface.co", "hf.co",
                         "osf.io", "dataverse.harvard.edu", "datadryad.org", "mendeley.com"}
MULTI_TENANT_EXACT = {"s3.amazonaws.com", "storage.googleapis.com"}


def is_multi_tenant(host: str) -> bool:
    return host in MULTI_TENANT_EXACT or any(host == suffix or host.endswith("." + suffix) for suffix in MULTI_TENANT_SUFFIXES)
STAGING_DIR = REPO_ROOT / "staging"
DATASETS_DIR = REPO_ROOT / "datasets"
RUNTIME_DIR = DATA_ROOT / "pipeline"
STATE_DIR = RUNTIME_DIR / "state"
LOGS_DIR = RUNTIME_DIR / "logs"
ARCHIVE_DIR = RUNTIME_DIR / "archive"
COSTS_PATH = RUNTIME_DIR / "costs.tsv"
DRIVER_LOG = RUNTIME_DIR / "driver.log"
HEARTBEAT_PATH = RUNTIME_DIR / "driver_status.json"
PAUSE_PATH = RUNTIME_DIR / "global_pause.json"
LOCK_PATH = RUNTIME_DIR / "driver.lock"
ROTATION_PATH = RUNTIME_DIR / "focus_rotation.json"
CONTROL_PATH = RUNTIME_DIR / "control.jsonl"
QUARANTINE_DIR = RUNTIME_DIR / "quarantine"
# Untracked files outside these top-level areas are agent scratch (e.g. a
# self-test run from the repo root) and get quarantined instead of pausing.
RECIPE_AREAS = {"datasets", "attempts", "reports", "pipeline", "tools", "evaluation", ".claude", ".llms", "staging", ".data"}

WIDTHS = (8, 16, 32, 64)
# `updated` stays last: an empty trailing field would end the row in a tab,
# which `git diff --check` rejects as trailing whitespace.
LEDGER_COLUMNS = ["candidate_id", "width", "status", "priority", "title", "source_url", "novelty_kind", "breadth", "reason", "updated"]
REGISTRY_COLUMNS = ["dataset_id", "status", "active_path", "evidence_path", "replacement_id", "reason", "retry_condition"]
ACTIVE_STATUSES = ["proposed", "queued", "ready_for_download", "downloaded", "built", "needs_repair", "ready_for_judge"]
REGISTRY_TERMINALS = ["rejected", "blocked", "deferred", "transient_failure", "needs_tooling"]
TERMINAL_STATUSES = ["screened_out", "accepted", *REGISTRY_TERMINALS]
PAUSED = "paused"
DRIVER_OWNED_PREFIXES = ("pipeline/",)
SHARED_FILES = ["attempts/dataset_status.tsv", "reports/accepted_recipe_audit.tsv", "reports/accepted_recipe_audit.md"]
DATA_SUBDIRS_PRUNABLE = ["downloads", "extracted", "filtered", "samples", "index", "discovery", "probes", "tmp"]
CANDIDATE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]{2,90}$")
NOVELTY_KINDS = ["new_modality", "new_source", "new_quantity", "new_content_same_modality", "downstream_mirror_fill", "not_new"]

FOCUS_DOMAINS = [
    "astronomy and astrophysics instrument data",
    "solar, heliospheric and space-weather physics",
    "planetary science missions",
    "seismology, geophysics and geodesy",
    "oceanography and underwater acoustics",
    "atmospheric science, weather and climate model output",
    "hydrology, glaciology and cryosphere",
    "remote sensing and Earth observation rasters",
    "lidar, photogrammetry and terrain",
    "particle, nuclear and accelerator physics",
    "materials science, crystallography and diffraction",
    "chemistry, spectroscopy and spectrometry",
    "genomics and sequencing instruments",
    "proteomics, structural biology and mass spectrometry",
    "neuroscience electrophysiology and neuroimaging",
    "openly licensed medical imaging collections",
    "physiological and wearable signals",
    "microscopy and cell imaging",
    "ecology, bioacoustics and animal biologging",
    "agriculture, soil and forestry",
    "energy systems, power grids and batteries",
    "transportation and vehicle telemetry",
    "industrial sensors and predictive maintenance",
    "robotics, SLAM, IMU and motion capture",
    "public-domain or CC audio, speech and music",
    "computer graphics: meshes, textures, volumes, HDR",
    "open machine-learning model weights and embeddings",
    "scientific simulation outputs (CFD, N-body, plasma, climate)",
    "radio, SDR, radar and sonar signals",
    "permissively licensed market microstructure and economics",
    "numeric network, systems and performance telemetry",
    "sports tracking and biomechanics",
]

ROLE_AGENT = {role: f"autocollect-{role}" for role in ("scout", "screener", "builder", "judge")}
# Meta's sanctioned agent internet access: open internet, no user-data stores
# (agent role internet_without_user_data). Without it, agents only reach the
# security team's short destination allowlist.
AGENT_INTERNET_FLAGS = ["--secure-internet-mode"]
IDENTITY_PROBE_URL = "https://zenodo.org/"
AGENT_ROLE_MARKER = '"agent_role":"internet_without_user_data"'
READ_TOOLS = [
    "Read",
    "Glob",
    "Grep",
    "Bash",
    "WebFetch",
    "WebSearch",
    "mcp__plugin_meta_mux__external_web_search3pai",
    "mcp__plugin_meta_mux__search_files",
]
ROLE_ALLOWED_TOOLS = {
    "scout": READ_TOOLS,
    "screener": READ_TOOLS,
    "judge": READ_TOOLS,
    "builder": READ_TOOLS + ["Edit", "Write"],
}
# Deny rules win over the user's global Edit/Write allows; path-scoped allows
# do not, so protected paths are denied explicitly. Bash can still write
# anywhere: Driver.check_repo_mutations is the backstop.
PROTECTED_PATHS = [
    "datasets/**", "attempts/**", "reports/**", "pipeline/**", "tools/**", "evaluation/**", ".claude/**", ".llms/**",
    "AGENTS.md", "collection_protocol.md", "external_registry_sync.tsv", ".gitignore", ".data/README.md", "staging/README.md",
]
WRITE_TOOLS = ["Edit", "Write", "NotebookEdit"]
DENIED_TOOLS = [
    "Agent",
    "Workflow",
    "Bash(git add:*)",
    "Bash(git commit:*)",
    "Bash(git push:*)",
    "Bash(git reset:*)",
    "Bash(git checkout:*)",
    "Bash(git restore:*)",
    "Bash(git rm:*)",
    "Bash(git mv:*)",
    "Bash(git stash:*)",
    "Bash(git clean:*)",
    "Bash(git rebase:*)",
    "Bash(git merge:*)",
    "Bash(sudo:*)",
]
ROLE_DENIED_TOOLS = {
    "scout": DENIED_TOOLS + WRITE_TOOLS,
    "screener": DENIED_TOOLS + WRITE_TOOLS,
    "judge": DENIED_TOOLS + WRITE_TOOLS,
    "builder": DENIED_TOOLS + ["NotebookEdit"] + [f"{tool}({path})" for tool in ("Edit", "Write") for path in PROTECTED_PATHS],
}


@dataclasses.dataclass
class Config:
    agents: int = 3
    downloads: int = 2
    widths: tuple[int, ...] = WIDTHS
    scout_batch: int = 6
    scouts_per_width: int = 2
    queue_low_water: int = 3
    screen_batch: int = 8
    download_cap_bytes: int = 5_000_000_000
    download_timeout_s: int = 6 * 3600
    download_stall_s: int = 20 * 60
    build_timeout_s: int = 4 * 3600
    min_free_bytes: int = 200_000_000_000
    disk_budget_bytes: int = 500_000_000_000
    max_download_cycles: int = 4
    max_build_cycles: int = 4
    max_repair_cycles: int = 2
    max_agent_failures: int = 2
    max_per_archive: int = 2
    budgets_usd: dict = dataclasses.field(default_factory=lambda: {"scout": 10.0, "screener": 8.0, "builder": 40.0, "judge": 15.0})
    timeouts_s: dict = dataclasses.field(default_factory=lambda: {"scout": 5400, "screener": 5400, "builder": 4 * 3600, "judge": 2 * 3600})
    max_cost_usd: float | None = None
    stop_after: int | None = None
    model: str | None = None
    effort: str | None = None
    # Cost tuning (2026-10-05): user settings run Opus 5.5 at xhigh everywhere.
    # Mechanical roles get lower effort; the judge keeps full thoroughness.
    role_effort: dict = dataclasses.field(default_factory=lambda: {"scout": "medium", "screener": "medium", "builder": "high", "judge": "xhigh"})
    # Builders accumulate large contexts that are re-read every turn.
    role_autocompact: dict = dataclasses.field(default_factory=lambda: {"builder": "300k"})
    keep_rejected_data: bool = False
    notify_cmd: str | None = None
    poll_s: int = 15


# ---------------------------------------------------------------- utilities


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def today() -> str:
    return dt.date.today().strftime("%Y%m%d")


FILE_LOCK = threading.Lock()


def log(message: str) -> None:
    line = f"[{now_iso()}] {message}"
    with FILE_LOCK:
        print(line, flush=True)
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        with DRIVER_LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def one_line(text: str, limit: int = 600) -> str:
    return " ".join(str(text).split())[:limit]


def tail(path: Path, lines: int = 60) -> str:
    if not path.exists():
        return ""
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def clean_markdown(text: str) -> str:
    """Strip trailing whitespace and extra blank lines at the end, so
    committed text passes `git diff --check`."""
    return "\n".join(line.rstrip() for line in text.strip("\n").splitlines()) + "\n"


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def read_curlrc() -> tuple[str, str]:
    proxy = noproxy = ""
    curlrc = Path.home() / ".curlrc"
    if curlrc.exists():
        for raw in curlrc.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if line.startswith("proxy="):
                proxy = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("noproxy="):
                noproxy = line.split("=", 1)[1].strip().strip('"')
    return proxy, noproxy


def child_env() -> dict[str, str]:
    """Environment for agents and recipe scripts: export the curl proxy so
    Python urllib reaches the internet too, not only curl."""
    env = dict(os.environ)
    proxy, noproxy = read_curlrc()
    if proxy and not any(env.get(key) for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")):
        for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
            env[key] = proxy
    if noproxy:
        env.setdefault("no_proxy", noproxy)
        env.setdefault("NO_PROXY", noproxy)
    env["AUTOCOLLECT"] = "1"
    return env


LIVE_GROUPS: set[int] = set()
# Set by a second interrupt: no new agents, no retries; in-flight subprocesses
# are killed and every half-done step unwinds through its normal failure path.
SHUTTING_DOWN = threading.Event()


def run_proc(cmd: list[str], *, log_path: Path, timeout_s: int, input_text: str | None = None, monitor=None, poll_s: int = 15) -> tuple[int, str]:
    """Run cmd in its own process group with stdout+stderr to log_path.
    Returns (returncode, kill_reason). monitor() may return a kill reason."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8") as out:
        proc = subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            env=child_env(),
            stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        LIVE_GROUPS.add(proc.pid)
        try:
            if input_text is not None:
                proc.stdin.write(input_text)
                proc.stdin.close()
            reason = ""
            while proc.poll() is None:
                time.sleep(min(poll_s, 5) if time.monotonic() - started < 60 else poll_s)
                if time.monotonic() - started > timeout_s:
                    reason = f"timeout after {timeout_s}s"
                elif monitor is not None:
                    reason = monitor() or ""
                if reason and proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGTERM)
                    try:
                        proc.wait(30)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait()
            return proc.returncode, reason
        finally:
            LIVE_GROUPS.discard(proc.pid)


def candidate_bytes(cid: str) -> int:
    total = 0
    if not DATA_ROOT.is_dir():
        return 0
    for top in DATA_ROOT.iterdir():
        if top.name == "pipeline":
            continue
        root = top / cid
        if not root.is_dir():
            continue
        for dirpath, _, filenames in os.walk(root):
            for name in filenames:
                try:
                    total += os.lstat(os.path.join(dirpath, name)).st_size
                except OSError:
                    pass
    return total


def notify(cfg: Config, message: str) -> None:
    """Send a milestone message through the user's notification command
    (message on stdin), e.g. a pingme script."""
    if not cfg.notify_cmd:
        return
    try:
        result = subprocess.run(["bash", "-c", cfg.notify_cmd], input=message, text=True, capture_output=True, timeout=60)
        if result.returncode != 0:
            log(f"notify failed (rc={result.returncode}): {one_line(result.stderr, 300)}")
    except (OSError, subprocess.TimeoutExpired) as exc:
        log(f"notify failed: {exc!r}")


# ---------------------------------------------------------------- state files


def load_ledger() -> list[dict]:
    if not LEDGER_PATH.exists():
        return []
    with LEDGER_PATH.open(encoding="utf-8", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh, delimiter="\t")]


def save_ledger(rows: list[dict]) -> None:
    lines = ["\t".join(LEDGER_COLUMNS)]
    for row in rows:
        lines.append("\t".join(one_line(row.get(column, ""), 400) for column in LEDGER_COLUMNS))
    write_atomic(LEDGER_PATH, "\n".join(lines) + "\n")


def load_state(cid: str) -> dict:
    path = STATE_DIR / f"{cid}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"candidate_id": cid, "events": []}


def save_state(cid: str, state: dict) -> None:
    write_atomic(STATE_DIR / f"{cid}.json", json.dumps(state, indent=1, default=str))


def add_event(state: dict, kind: str, **fields) -> None:
    state.setdefault("events", []).append({"at": now_iso(), "kind": kind, **fields})


def accepted_widths() -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    for manifest_path in sorted(DATASETS_DIR.glob("*/manifest.toml")):
        try:
            manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            continue
        result[manifest_path.parent.name] = sorted(
            {
                int(series["bit_width"])
                for series in manifest.get("series", [])
                if isinstance(series, dict)
                and series.get("role", "primary") != "auxiliary"
                and series.get("bit_width") in WIDTHS
            }
        )
    return result


def load_baseline() -> dict:
    if not BASELINE_PATH.exists():
        raise SystemExit("pipeline/baseline.json missing; run `driver.py init` first")
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def load_breadth() -> list[dict]:
    if not BREADTH_KEYS_PATH.exists():
        return []
    with BREADTH_KEYS_PATH.open(encoding="utf-8", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh, delimiter="\t")]


def append_breadth(row: dict) -> None:
    rows = [existing for existing in load_breadth() if existing["dataset_id"] != row["dataset_id"]]
    rows.append(row)
    lines = ["\t".join(BREADTH_COLUMNS)] + ["\t".join(one_line(item.get(column, "") or "-", 300) for column in BREADTH_COLUMNS) for item in rows]
    write_atomic(BREADTH_KEYS_PATH, "\n".join(lines) + "\n")


def url_archive(url: str) -> str:
    host = urlparse(url.strip()).netloc.lower().split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def recipe_archives(recipe_dir: Path) -> set[str]:
    """Archive hosts of a recipe's declared resources (facts, not agent labels).
    Bare multi-tenant hosts (Zenodo, GitHub, ...) are not one archive."""
    try:
        manifest = tomllib.loads((recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return set()
    hosts = {url_archive(item.get("url", "")) for item in manifest.get("resources", []) if isinstance(item, dict)}
    return {host for host in hosts if host and not is_multi_tenant(host)}


def progress(counted_only: bool = True) -> dict[int, list[str]]:
    """New recipes since the baseline per width. Autocollect families count
    toward the goal only with a STRONG or OK breadth verdict; recipes added
    outside the pipeline count as they are."""
    baseline = load_baseline()
    known = set(baseline["accepted_ids"])
    verdicts = {row["candidate_id"]: row.get("breadth", "") or "" for row in load_ledger()}
    new: dict[int, list[str]] = {width: [] for width in WIDTHS}
    for dataset_id, widths in accepted_widths().items():
        if dataset_id in known:
            continue
        if counted_only and dataset_id in verdicts and verdicts[dataset_id].upper() not in COUNTED_VERDICTS:
            continue
        for width in widths:
            new[width].append(dataset_id)
    return new


def registry_rows() -> list[dict]:
    with REGISTRY_PATH.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def append_registry(row: dict) -> None:
    text = REGISTRY_PATH.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    row = {**row, "reason": row.get("reason") or "No reason recorded.", "retry_condition": row.get("retry_condition") or "None recorded."}
    text += "\t".join(one_line(row.get(column, ""), 1200) for column in REGISTRY_COLUMNS) + "\n"
    REGISTRY_PATH.write_text(text, encoding="utf-8")


def record_cost(role: str, subject: str, cost: float, seconds: float, outcome: str) -> None:
    with FILE_LOCK:
        new = not COSTS_PATH.exists()
        with COSTS_PATH.open("a", encoding="utf-8") as fh:
            if new:
                fh.write("at\trole\tsubject\tcost_usd\tseconds\toutcome\n")
            fh.write(f"{now_iso()}\t{role}\t{subject}\t{cost:.4f}\t{seconds:.0f}\t{outcome}\n")


def total_cost(since: str | None = None) -> float:
    if not COSTS_PATH.exists():
        return 0.0
    total = 0.0
    with COSTS_PATH.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            if since is None or row["at"] >= since:
                total += float(row["cost_usd"] or 0)
    return total


# ---------------------------------------------------------------- git


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, text=True, capture_output=True, check=check)


def dirty_paths() -> set[str]:
    paths = set()
    for line in git("status", "--porcelain", "--untracked-files=all").stdout.splitlines():
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.add(path.strip('"'))
    return paths


def commit(paths: list[str], message: str) -> bool:
    paths = sorted({path for path in paths if path})
    hygiene = subprocess.run([sys.executable, "tools/check_repo_hygiene.py"], cwd=REPO_ROOT, text=True, capture_output=True)
    if hygiene.returncode != 0:
        log(f"commit blocked by hygiene check: {one_line(hygiene.stdout + hygiene.stderr, 1500)}")
        return False
    git("add", "-A", "--", *paths)
    check = git("diff", "--cached", "--check", "--", *paths, check=False)
    if check.returncode != 0:
        log(f"commit blocked by whitespace check: {one_line(check.stdout, 1500)}")
        git("reset", "-q", "--", *paths, check=False)
        return False
    result = git("commit", "-q", "-m", message, "--", *paths, check=False)
    if result.returncode != 0:
        log(f"git commit failed: {one_line(result.stdout + result.stderr, 1500)}")
        return False
    log(f"committed: {message}")
    return True


# ---------------------------------------------------------------- agents

STR = {"type": "string"}
INT = {"type": "integer"}

SCOUT_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "candidate_id": STR,
                    "width": {"type": "integer", "enum": list(WIDTHS)},
                    "numeric_kind": {"type": "string", "enum": ["int", "uint", "float"]},
                    "title": STR,
                    "quantity": STR,
                    "source_url": STR,
                    "resource_urls": {"type": "array", "items": STR},
                    "license": STR,
                    "license_evidence_url": STR,
                    "license_quote": STR,
                    "natural_record": STR,
                    "est_samples": INT,
                    "est_primary_values": INT,
                    "est_download_bytes": INT,
                    "est_primary_bytes": INT,
                    "decode_path": STR,
                    "novelty_kind": {"type": "string", "enum": NOVELTY_KINDS[:-1]},
                    "novelty_evidence": STR,
                    "measurement_type": STR,
                    "instrument_line": STR,
                    "archive_collection": STR,
                    "homogeneity_notes": STR,
                    "risks": STR,
                    "probe_evidence": STR,
                },
                "required": [
                    "candidate_id", "width", "numeric_kind", "title", "quantity", "source_url", "resource_urls",
                    "license", "license_evidence_url", "license_quote", "natural_record", "est_samples",
                    "est_primary_values", "est_download_bytes", "est_primary_bytes", "decode_path",
                    "novelty_kind", "novelty_evidence", "homogeneity_notes", "risks", "probe_evidence",
                    "measurement_type", "instrument_line", "archive_collection",
                ],
            },
        },
        "search_notes": STR,
    },
    "required": ["candidates", "search_notes"],
}

SCREEN_SCHEMA = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "candidate_id": STR,
                    "decision": {"type": "string", "enum": ["approve", "reject"]},
                    "priority": {"type": "integer", "minimum": 1, "maximum": 5},
                    "reason": STR,
                    "builder_notes": STR,
                    "measurement_type": STR,
                    "instrument_line": STR,
                    "archive_collection": STR,
                },
                "required": ["candidate_id", "decision", "priority", "reason", "builder_notes", "measurement_type",
                             "instrument_line", "archive_collection"],
            },
        }
    },
    "required": ["decisions"],
}

BUILDER_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["ready_for_download", "ready_for_judge", "abandon"]},
        "summary": STR,
        "expected_download_bytes": INT,
        "abandon_status": {"type": "string", "enum": ["", *REGISTRY_TERMINALS]},
        "attempt_markdown": STR,
        "registry_reason": STR,
        "retry_condition": STR,
    },
    "required": ["status", "summary", "expected_download_bytes", "abandon_status", "attempt_markdown", "registry_reason", "retry_condition"],
}

JUDGE_CHECKS = ["mechanics", "reproducibility", "bytes", "conversion", "rights", "novelty", "homogeneity", "volume"]
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["accept", "repair", *REGISTRY_TERMINALS]},
        "novelty_kind": {"type": "string", "enum": NOVELTY_KINDS},
        "breadth_verdict": {"type": "string", "enum": ["STRONG", "OK", "WEAK"]},
        "measurement_type": STR,
        "instrument_line": STR,
        "archive_collection": STR,
        "summary": STR,
        "checks": {"type": "object", "properties": {check: STR for check in JUDGE_CHECKS}, "required": JUDGE_CHECKS},
        "repair_instructions": STR,
        "registry_reason": STR,
        "retry_condition": STR,
        "report_markdown": STR,
    },
    "required": ["decision", "novelty_kind", "breadth_verdict", "measurement_type", "instrument_line", "archive_collection",
                 "summary", "checks", "repair_instructions", "registry_reason",
                 "retry_condition", "report_markdown"],
}


def run_agent(cfg: Config, role: str, subject: str, prompt: str, schema: dict, session_id: str | None = None, resume: bool = False) -> dict:
    session_id = session_id or str(uuid.uuid4())
    if SHUTTING_DOWN.is_set():
        return {"role": role, "subject": subject, "ok": False, "error": "driver shutting down", "structured": {},
                "session_id": session_id, "cost": 0.0, "seconds": 0.0, "log": ""}
    cmd = [
        "claude", "-p",
        "--agent", ROLE_AGENT[role],
        "--output-format", "stream-json",
        "--verbose",
        "--json-schema", json.dumps(schema),
        "--permission-mode", "dontAsk",
        "--max-budget-usd", str(cfg.budgets_usd[role]),
        "--allowedTools", *ROLE_ALLOWED_TOOLS[role],
        "--disallowedTools", *ROLE_DENIED_TOOLS[role],
        *AGENT_INTERNET_FLAGS,
    ]
    cmd += ["--resume", session_id] if resume else ["--session-id", session_id]
    if cfg.model:
        cmd += ["--model", cfg.model]
    effort = cfg.effort or cfg.role_effort.get(role)
    if effort:
        cmd += ["--effort", effort]
    if cfg.role_autocompact.get(role):
        cmd += ["--autocompact", cfg.role_autocompact[role]]
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / subject / f"{role}.{stamp}.jsonl"
    started = time.monotonic()
    rc, kill_reason = run_proc(cmd, log_path=log_path, timeout_s=cfg.timeouts_s[role], input_text=prompt)
    seconds = time.monotonic() - started
    result: dict = {}
    for line in reversed(log_path.read_text(encoding="utf-8", errors="replace").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if candidate.get("type") == "result":
                result = candidate
                break
    structured = result.get("structured_output")
    cost = float(result.get("total_cost_usd") or 0)
    error = ""
    if kill_reason:
        error = kill_reason
    elif not result:
        error = f"no result (rc={rc}): {one_line(tail(log_path, 5), 300)}"
    elif result.get("is_error") or not isinstance(structured, dict):
        error = f"{result.get('subtype')}: {one_line(result.get('result', ''), 300)}"
    record_cost(role, subject, cost, seconds, "ok" if not error else "error")
    return {
        "role": role,
        "subject": subject,
        "ok": not error,
        "error": error,
        "structured": structured if isinstance(structured, dict) else {},
        "session_id": result.get("session_id") or session_id,
        "cost": cost,
        "seconds": seconds,
        "log": str(log_path.relative_to(REPO_ROOT)),
    }


# ---------------------------------------------------------------- prompts


def card_markdown(candidate: dict, scout_log: str) -> str:
    lines = [f"# {candidate['title']}", "", f"- Candidate id: `{candidate['candidate_id']}`"]
    fields = [
        ("Width", f"{candidate['numeric_kind']}{candidate['width']}"),
        ("Quantity", candidate["quantity"]),
        ("Source", candidate["source_url"]),
        ("Resources", ", ".join(candidate["resource_urls"])),
        ("License", candidate["license"]),
        ("License evidence", candidate["license_evidence_url"]),
        ("License quote", candidate["license_quote"]),
        ("Natural record", candidate["natural_record"]),
        ("Estimated samples", f"{candidate['est_samples']:,}"),
        ("Estimated primary values", f"{candidate['est_primary_values']:,}"),
        ("Estimated download bytes", f"{candidate['est_download_bytes']:,}"),
        ("Estimated primary bytes", f"{candidate['est_primary_bytes']:,}"),
        ("Decode path", candidate["decode_path"]),
        ("Novelty kind", candidate["novelty_kind"]),
        ("Measurement type", candidate.get("measurement_type", "")),
        ("Instrument line", candidate.get("instrument_line", "")),
        ("Archive collection", candidate.get("archive_collection", "")),
        ("Novelty evidence", candidate["novelty_evidence"]),
        ("Homogeneity", candidate["homogeneity_notes"]),
        ("Risks", candidate["risks"]),
        ("Probe evidence", candidate["probe_evidence"]),
    ]
    lines += [f"- {name}: {one_line(value, 2000)}" for name, value in fields]
    lines += ["", f"Proposed by the autocollect scout on {dt.date.today().isoformat()} (transcript `{scout_log}`)."]
    return clean_markdown("\n".join(lines))


def scout_prompt(width: int, count: int, domains: list[str], have: int, target: int, avoid: list[str], lessons: list[str]) -> str:
    parts = [
        f"Target width: {width}-bit. Return up to {count} candidates; fewer is fine if quality is lacking.",
        f"Focus domains this round: {'; '.join(domains)}. Other domains are welcome if clearly more promising.",
        f"Progress: {have} of {target} new {width}-bit families accepted since the baseline.",
    ]
    if avoid:
        parts.append("Already proposed in the pipeline (do not repeat these or their sources):\n" + "\n".join(f"- {item}" for item in avoid))
    if lessons:
        parts.append("Recent rejection reasons at this width; learn from them:\n" + "\n".join(f"- {item}" for item in lessons))
    return "\n\n".join(parts) + "\n"


def screen_prompt(rows: list[dict]) -> str:
    listing = "\n".join(f"- {row['candidate_id']} ({row['width']}-bit): pipeline/cards/{row['candidate_id']}.md" for row in rows)
    return f"Screen these candidates and return exactly one decision per candidate id:\n{listing}\n"


def builder_prompt(cfg: Config, row: dict, state: dict, phase: str, detail: str) -> str:
    cid = row["candidate_id"]
    header = [
        f"Phase: {phase}",
        f"Candidate: {cid} (target width {row['width']}-bit)",
        f"Card: pipeline/cards/{cid}.md",
        f"Recipe directory: staging/{cid}/",
        f"Download guardrails: the driver runs download.sh with a cap of {cfg.download_cap_bytes:,} bytes across all .data/*/{cid} "
        f"directories and a {cfg.download_timeout_s // 3600} h time limit.",
    ]
    if state.get("screener_notes"):
        header.append(f"Screener notes: {state['screener_notes']}")
    return "\n".join(header) + "\n\n" + detail.strip() + "\n"


def judge_prompt(row: dict, state: dict, cfg: Config, gate_warnings: list[str]) -> str:
    cid = row["candidate_id"]
    warnings = "\n".join(f"- {warning}" for warning in gate_warnings) or "- none"
    return (
        f"Candidate: {cid} (target width {row['width']}-bit)\n"
        f"Recipe: staging/{cid}/\n"
        f"Card: pipeline/cards/{cid}.md\n"
        f"Repair cycles used: {state.get('repair_cycles', 0)} of {cfg.max_repair_cycles}\n\n"
        f"The driver already re-ran build.sh and verify.sh from the current scripts and gate.py passed. Gate warnings:\n{warnings}\n\n"
        f"Measured breadth (zlsim, compression + features): verdict {(state.get('similarity') or {}).get('verdict')}; "
        f"nearest per series: {json.dumps([{'series': s_.get('key'), 'nearest_distance': s_.get('nearest_distance'), 'mode_share': s_.get('mode_share'), 'closest': (s_.get('neighbors') or [None])[0]} for s_ in (state.get('similarity') or {}).get('series', [])])}\n"
        f"Fill warnings (one value dominates the samples; justify or repair): {(state.get('similarity') or {}).get('fill_warnings', [])}\n"
        f"Screener breadth keys (descriptive): {json.dumps(state.get('breadth_keys', {}))}\n"
        + (f"Breadth override APPROVED by the user: {state.get('breadth_approval_note', '')}\n" if state.get("breadth_approved") else "")
        + f"\nBuilder summary:\n{state.get('builder_summary', '(none)')}\n"
    )


# ---------------------------------------------------------------- tasks (worker threads)


def task_download(cfg: Config, cid: str) -> dict:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / cid / f"download.{stamp}.log"

    progress = {"bytes": candidate_bytes(cid), "at": time.monotonic()}

    def monitor() -> str:
        used = candidate_bytes(cid)
        if used > cfg.download_cap_bytes:
            return f"byte cap exceeded ({used:,} > {cfg.download_cap_bytes:,})"
        # A script stuck in an error/retry loop adds no bytes; stop it instead of
        # hammering the host until the time limit.
        if used != progress["bytes"]:
            progress.update(bytes=used, at=time.monotonic())
        elif time.monotonic() - progress["at"] > cfg.download_stall_s:
            return f"no download progress for {cfg.download_stall_s // 60} min ({used:,} bytes)"
        return ""

    started = time.monotonic()
    rc, reason = run_proc(["bash", f"staging/{cid}/download.sh"], log_path=log_path, timeout_s=cfg.download_timeout_s, monitor=monitor, poll_s=cfg.poll_s)
    return {
        "kind": "download",
        "cid": cid,
        "rc": rc,
        "reason": reason,
        "bytes": candidate_bytes(cid),
        "seconds": round(time.monotonic() - started),
        "log": str(log_path.relative_to(REPO_ROOT)),
        "tail": tail(log_path, 60),
    }


def task_rebuild(cfg: Config, cid: str) -> dict:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    steps = []
    for script in ("build.sh", "verify.sh"):
        log_path = LOGS_DIR / cid / f"driver_{script.split('.')[0]}.{stamp}.log"
        rc, reason = run_proc(["bash", f"staging/{cid}/{script}"], log_path=log_path, timeout_s=cfg.build_timeout_s, poll_s=cfg.poll_s)
        steps.append({"script": script, "rc": rc, "reason": reason, "log": str(log_path.relative_to(REPO_ROOT)), "tail": tail(log_path, 40)})
        if rc != 0:
            return {"kind": "rebuild", "cid": cid, "ok": False, "steps": steps, "gate": None}
    gate = subprocess.run(
        [sys.executable, "tools/autocollect/gate.py", f"staging/{cid}", "--json"], cwd=REPO_ROOT, text=True, capture_output=True
    )
    try:
        report = json.loads(gate.stdout)
    except json.JSONDecodeError:
        report = {"ok": False, "failures": [f"gate crashed: {one_line(gate.stderr, 800)}"], "warnings": []}
    similarity = None
    if report.get("ok"):
        # Byte-level breadth: compression equivalence AND feature proximity (zlsim.py).
        # Through run_proc so an interrupt can kill it (process group, tracked).
        report_path = LOGS_DIR / cid / f"zlsim_gate.{stamp}.json"
        log_path = LOGS_DIR / cid / f"zlsim_gate.{stamp}.log"
        os.environ.update(ZLSIM_ENV)
        rc, reason = run_proc([*ZLSIM, "gate", f"staging/{cid}", "--jobs", "16", "--output", str(report_path)],
                              log_path=log_path, timeout_s=3 * 3600, poll_s=cfg.poll_s)
        try:
            similarity = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            similarity = {"verdict": "ERROR", "error": f"rc={rc} {reason}: {one_line(tail(log_path, 5), 600)}"}
    return {"kind": "rebuild", "cid": cid, "ok": bool(report.get("ok")), "steps": steps, "gate": report, "similarity": similarity}


def task_agent(cfg: Config, kind: str, role: str, subject: str, prompt: str, schema: dict, payload: dict, session_id: str | None = None, resume: bool = False) -> dict:
    result = run_agent(cfg, role, subject, prompt, schema, session_id=session_id, resume=resume)
    if not result["ok"] and resume and not SHUTTING_DOWN.is_set() and result["seconds"] < 120 and result["cost"] < 0.5:
        log(f"{role} resume failed for {subject} ({result['error']}); retrying in a fresh session")
        prompt = (
            f"You are taking over an interrupted session for this candidate. Inspect the current state of staging/{subject}/ "
            f"and the logs under .data/logs/{subject}/ and .data/pipeline/logs/{subject}/ before acting.\n\n" + prompt
        )
        result = run_agent(cfg, role, subject, prompt, schema)
    return {"kind": kind, **payload, "agent": result}


# ---------------------------------------------------------------- driver


class Driver:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.ledger = load_ledger()
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=cfg.agents + cfg.downloads + 2)
        self.futures: dict[concurrent.futures.Future, dict] = {}
        self.stopping = False
        self.started_at = now_iso()
        self.terminal_this_run = 0
        self.startup_dirty = dirty_paths()

    # ledger helpers
    def row(self, cid: str) -> dict:
        for row in self.ledger:
            if row["candidate_id"] == cid:
                return row
        raise KeyError(cid)

    def set_status(self, cid: str, status: str, reason: str | None = None, **fields) -> None:
        row = self.row(cid)
        row["status"] = status
        row["updated"] = now_iso()
        if reason is not None:
            row["reason"] = one_line(reason, 400)
        row.update({key: str(value) for key, value in fields.items()})
        save_ledger(self.ledger)

    def inflight(self, kind: str | None = None) -> list[dict]:
        return [meta for meta in self.futures.values() if kind is None or meta["kind"] == kind]

    def busy(self, cid: str) -> bool:
        return any(meta.get("cid") == cid for meta in self.futures.values())

    def agent_slots_free(self) -> int:
        if self.budget_exhausted():
            return 0
        return self.cfg.agents - sum(1 for meta in self.futures.values() if meta["kind"] in {"scout", "screen", "builder", "judge"})

    def download_slots_free(self) -> int:
        return self.cfg.downloads - sum(1 for meta in self.futures.values() if meta["kind"] in {"download", "rebuild"})

    def submit(self, meta: dict, fn, *args, **kwargs) -> None:
        future = self.executor.submit(fn, *args, **kwargs)
        self.futures[future] = meta
        log(f"launch {meta['kind']} {meta.get('cid') or meta.get('width') or ''} {meta.get('phase', '')}".rstrip())

    # guardrails
    def pause_globally(self, reason: str) -> None:
        log(f"GLOBAL PAUSE: {reason}")
        write_atomic(PAUSE_PATH, json.dumps({"at": now_iso(), "reason": reason}, indent=1))
        notify(self.cfg, f"autocollect PAUSED, needs a look: {one_line(reason, 600)}")

    def paused(self) -> bool:
        return PAUSE_PATH.exists()

    def check_repo_mutations(self) -> None:
        unexpected = {path for path in dirty_paths() - self.startup_dirty if not path.startswith(DRIVER_OWNED_PREFIXES)}
        if not unexpected:
            return
        untracked = set(git("ls-files", "--others", "--exclude-standard").stdout.splitlines())
        strays = sorted(path for path in unexpected if path in untracked and path.split("/", 1)[0] not in RECIPE_AREAS)
        if strays:
            target = QUARANTINE_DIR / dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            for path in strays:
                destination = target / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(REPO_ROOT / path), str(destination))
            log(f"quarantined {len(strays)} stray untracked files to {target}: {strays[:10]}")
            notify(self.cfg, f"autocollect quarantined {len(strays)} stray files an agent wrote into the repo: {strays[:5]} -> {target}")
        rest = sorted(unexpected - set(strays))
        if rest:
            self.pause_globally(f"unexpected repository changes outside staging/: {rest[:20]}")

    def budget_exhausted(self) -> bool:
        return self.cfg.max_cost_usd is not None and total_cost(self.started_at) >= self.cfg.max_cost_usd

    def winding_down(self) -> bool:
        return (
            self.stopping
            or self.paused()
            or self.budget_exhausted()
            or (self.cfg.stop_after is not None and self.terminal_this_run >= self.cfg.stop_after)
        )

    def deficits(self) -> dict[int, int]:
        target = int(load_baseline()["target_new_per_width"])
        new = progress()
        return {width: target - len(new[width]) for width in self.cfg.widths}

    def disk_ok(self, expected: int) -> tuple[bool, str]:
        free = shutil.disk_usage(DATA_ROOT).free
        if free - expected < self.cfg.min_free_bytes:
            return False, f"free disk {free:,} minus expected {expected:,} below reserve {self.cfg.min_free_bytes:,}"
        used = sum(int(load_state(row["candidate_id"]).get("bytes", 0)) for row in self.ledger)
        if used + expected > self.cfg.disk_budget_bytes:
            return False, f"pipeline disk budget {self.cfg.disk_budget_bytes:,} would be exceeded ({used:,} used)"
        return True, ""

    # scheduling
    def schedule(self) -> None:
        if self.paused() or self.stopping:
            return
        deficits = self.deficits()
        by_status = lambda status: [row for row in self.ledger if row["status"] == status and not self.busy(row["candidate_id"])]  # noqa: E731

        for row in by_status("ready_for_judge"):
            if self.agent_slots_free() <= 0:
                break
            self.launch_judge(row)
        for status, phase in (("downloaded", "build"), ("needs_repair", "repair")):
            for row in by_status(status):
                if self.agent_slots_free() <= 0:
                    break
                self.launch_builder(row, phase)
        for row in by_status("built"):
            if self.download_slots_free() <= 0:
                break
            self.submit({"kind": "rebuild", "cid": row["candidate_id"]}, task_rebuild, self.cfg, row["candidate_id"])
        for row in by_status("ready_for_download"):
            if self.download_slots_free() <= 0:
                break
            self.launch_download(row)

        if self.winding_down():
            return
        proposed = by_status("proposed")
        if proposed and not self.inflight("screen") and self.agent_slots_free() > 0:
            batch = proposed[: self.cfg.screen_batch]
            self.submit({"kind": "screen", "cids": [row["candidate_id"] for row in batch]},
                        task_agent, self.cfg, "screen", "screener", "screen", screen_prompt(batch), SCREEN_SCHEMA,
                        {"cids": [row["candidate_id"] for row in batch]})
        queued = sorted(
            (row for row in by_status("queued") if int(row["width"]) in self.cfg.widths and deficits[int(row["width"])] > 0),
            key=lambda row: (-deficits[int(row["width"])], int(row["priority"] or 5), row["updated"]),
        )
        for row in queued:
            if self.agent_slots_free() <= 0:
                break
            self.launch_builder(row, "author")
        for width in sorted(self.cfg.widths, key=lambda w: -deficits[w]):
            if self.agent_slots_free() <= 0:
                break
            running = sum(1 for meta in self.inflight("scout") if meta.get("width") == width)
            if deficits[width] <= 0 or running >= self.cfg.scouts_per_width:
                continue
            waiting = sum(1 for row in self.ledger if row["width"] == str(width) and row["status"] in {"proposed", "queued"})
            if waiting < self.cfg.queue_low_water and (running == 0 or self.agent_slots_free() > len(self.cfg.widths)):
                self.launch_scout(width, deficits[width])

    def launch_scout(self, width: int, deficit: int) -> None:
        rotation = json.loads(ROTATION_PATH.read_text()) if ROTATION_PATH.exists() else {}
        turn = int(rotation.get(str(width), 0))
        offset = WIDTHS.index(width) * 7
        domains = [FOCUS_DOMAINS[(offset + 2 * turn + i) % len(FOCUS_DOMAINS)] for i in range(2)]
        rotation[str(width)] = turn + 1
        write_atomic(ROTATION_PATH, json.dumps(rotation))
        target = int(load_baseline()["target_new_per_width"])
        rows = [row for row in self.ledger if row["width"] == str(width)]
        avoid = [f"{row['candidate_id']}: {row['title']} ({row['source_url']})" for row in rows[-60:]]
        lessons = [
            f"{row['candidate_id']} [{row['status']}]: {row['reason']}"
            for row in rows
            if row["status"] in {"screened_out", *REGISTRY_TERMINALS} and row["reason"]
        ][-15:]
        prompt = scout_prompt(width, self.cfg.scout_batch, domains, target - deficit, target, avoid, lessons)
        self.submit({"kind": "scout", "width": width}, task_agent, self.cfg, "scout", "scout", f"scout_{width}bit", prompt, SCOUT_SCHEMA, {"width": width})

    def launch_builder(self, row: dict, phase: str) -> None:
        cid = row["candidate_id"]
        state = load_state(cid)
        if phase == "author":
            detail = "Write the recipe and return ready_for_download, or abandon."
            if (STAGING_DIR / cid).exists():
                detail = f"staging/{cid}/ already exists from an interrupted run; inspect it and continue. " + detail
            session_id, resume = state.get("builder_session"), bool(state.get("builder_session"))
        elif phase == "build":
            info = state.get("last_download") or {}
            rebuild = state.get("last_rebuild")
            if rebuild and not rebuild.get("ok"):
                detail = "The driver re-ran the current build.sh/verify.sh/gate.py and they failed:\n" + json.dumps(rebuild, indent=1)[:12000]
            elif info.get("rc") == 0 and not info.get("reason"):
                detail = (
                    f"The driver ran download.sh successfully ({info.get('bytes', 0):,} bytes under .data/*/{cid}, {info.get('seconds')} s; "
                    f"log {info.get('log')}). Now run build.sh, verify.sh and gate.py; iterate until clean, then return ready_for_judge."
                )
            else:
                detail = (
                    f"download.sh failed: rc={info.get('rc')} {info.get('reason', '')}; {info.get('bytes', 0):,} bytes present; "
                    f"log {info.get('log')}. Tail:\n```\n{info.get('tail', '')}\n```\nFix download.sh and return ready_for_download, or abandon."
                )
            session_id, resume = state.get("builder_session"), bool(state.get("builder_session"))
        else:
            detail = (
                f"Repair cycle {state.get('repair_cycles', 0)} of {self.cfg.max_repair_cycles}. The acceptance judge returned the recipe.\n"
                f"Judge summary: {state.get('judge_summary', '')}\nInstructions:\n{state.get('repair_instructions', '')}\n"
                "Fix the recipe, rebuild, verify, gate, and return ready_for_judge (or ready_for_download if download.sh changed)."
            )
            session_id, resume = state.get("builder_session"), bool(state.get("builder_session"))
        prompt = builder_prompt(self.cfg, row, state, phase, detail)
        self.submit({"kind": "builder", "cid": cid, "phase": phase}, task_agent, self.cfg, "builder", "builder", cid, prompt,
                    BUILDER_SCHEMA, {"cid": cid, "phase": phase}, session_id=session_id, resume=resume)

    def launch_download(self, row: dict) -> None:
        cid = row["candidate_id"]
        state = load_state(cid)
        if int(state.get("download_cycles", 0)) >= self.cfg.max_download_cycles:
            last = state.get("last_download") or {}
            self.terminal(cid, "transient_failure",
                          f"download failed {state['download_cycles']} times; last: rc={last.get('rc')} {last.get('reason', '')}",
                          "Retry when the upstream source is reachable and download.sh completes within the pipeline caps.",
                          None)
            return
        expected = min(int(state.get("expected_download_bytes") or 0), self.cfg.download_cap_bytes)
        ok, why = self.disk_ok(expected)
        if not ok:
            if not state.get("disk_wait_logged"):
                log(f"download of {cid} waiting: {why}")
                state["disk_wait_logged"] = True
                save_state(cid, state)
            return
        state["disk_wait_logged"] = False
        state["download_cycles"] = int(state.get("download_cycles", 0)) + 1
        state["download_sha"] = sha256_file(STAGING_DIR / cid / "download.sh")
        save_state(cid, state)
        self.submit({"kind": "download", "cid": cid}, task_download, self.cfg, cid)

    def launch_judge(self, row: dict) -> None:
        cid = row["candidate_id"]
        state = load_state(cid)
        if sha256_file(STAGING_DIR / cid / "download.sh") != state.get("download_sha"):
            log(f"{cid}: download.sh changed since the last successful download; re-running it before judging")
            self.set_status(cid, "ready_for_download")
            return
        gate_warnings = ((state.get("last_rebuild") or {}).get("gate") or {}).get("warnings", [])
        self.submit({"kind": "judge", "cid": cid}, task_agent, self.cfg, "judge", "judge", cid,
                    judge_prompt(row, state, self.cfg, gate_warnings), JUDGE_SCHEMA, {"cid": cid})

    # result application (main thread only)
    def apply(self, meta: dict, result: dict) -> None:
        kind = meta["kind"]
        if kind == "scout":
            self.apply_scout(meta["width"], result["agent"])
        elif kind == "screen":
            self.apply_screen(meta["cids"], result["agent"])
        elif kind == "builder":
            self.apply_builder(meta["cid"], meta["phase"], result["agent"])
        elif kind == "download":
            self.apply_download(meta["cid"], result)
        elif kind == "rebuild":
            self.apply_rebuild(meta["cid"], result)
        elif kind == "judge":
            self.apply_judge(meta["cid"], result["agent"])
        self.check_repo_mutations()

    def apply_scout(self, width: int, agent: dict) -> None:
        if not agent["ok"]:
            log(f"scout {width}-bit failed: {agent['error']}")
            return
        known = {row["candidate_id"] for row in self.ledger} | {row["dataset_id"] for row in registry_rows()}
        known |= {path.name for path in DATASETS_DIR.iterdir() if path.is_dir()}
        known |= {path.name for path in STAGING_DIR.iterdir() if path.is_dir()}
        seen_urls = {row["source_url"].rstrip("/").lower() for row in self.ledger}
        added = 0
        for candidate in agent["structured"].get("candidates", []):
            cid = candidate.get("candidate_id", "")
            url = candidate.get("source_url", "").rstrip("/").lower()
            if not CANDIDATE_ID_RE.match(cid) or cid in known:
                log(f"scout candidate skipped (invalid or known id): {cid}")
                continue
            if url and url in seen_urls:
                log(f"scout candidate skipped (source already in ledger): {cid} {url}")
                continue
            write_atomic(CARDS_DIR / f"{cid}.md", card_markdown(candidate, agent["log"]))
            self.ledger.append(
                {
                    "candidate_id": cid,
                    "width": str(candidate["width"]),
                    "status": "proposed",
                    "priority": "",
                    "title": candidate["title"],
                    "source_url": candidate["source_url"],
                    "novelty_kind": candidate["novelty_kind"],
                    "updated": now_iso(),
                    "reason": "",
                }
            )
            state = load_state(cid)
            state["expected_download_bytes"] = int(candidate.get("est_download_bytes") or 0)
            state["resource_urls"] = list(candidate.get("resource_urls") or [])
            add_event(state, "proposed", log=agent["log"])
            save_state(cid, state)
            known.add(cid)
            seen_urls.add(url)
            added += 1
        save_ledger(self.ledger)
        log(f"scout {width}-bit proposed {added} candidates (cost ${agent['cost']:.2f})")

    def archive_gate(self, cid: str, archives: set[str]) -> tuple[str, str]:
        """A third acceptance from the same archive host in this effort needs the
        user's sign-off. Hosts come from declared resource URLs, not agent labels."""
        if load_state(cid).get("breadth_approved") or not archives:
            return "ok", ""
        accepted = [row["candidate_id"] for row in self.ledger if row["status"] == "accepted" and row["candidate_id"] != cid]
        shared = {}
        for other in accepted:
            common = archives & recipe_archives(DATASETS_DIR / other)
            for host in common:
                shared.setdefault(host, []).append(other)
        crowded = {host: ids for host, ids in shared.items() if len(ids) >= self.cfg.max_per_archive}
        if crowded:
            host, ids = next(iter(crowded.items()))
            return "signoff", f"archive cap: {len(ids)} families already accepted from {host} ({', '.join(ids[:4])})"
        return "ok", ""

    def hold_for_signoff(self, cid: str, reason: str) -> None:
        state = load_state(cid)
        state["paused_from"] = self.row(cid)["status"]
        state["breadth_signoff"] = reason
        save_state(cid, state)
        self.set_status(cid, PAUSED, reason)
        notify(self.cfg, f"autocollect needs your sign-off for {cid}: {one_line(reason, 500)}. "
                         f"Approve: driver.py approve-breadth {cid}; refuse: driver.py reject {cid} --reason ...")

    def apply_screen(self, cids: list[str], agent: dict) -> None:
        decisions = {item["candidate_id"]: item for item in agent["structured"].get("decisions", [])} if agent["ok"] else {}
        if not agent["ok"]:
            log(f"screener failed: {agent['error']}")
        for cid in cids:
            state = load_state(cid)
            decision = decisions.get(cid)
            if decision is None:
                state["screen_misses"] = int(state.get("screen_misses", 0)) + 1
                save_state(cid, state)
                if state["screen_misses"] >= 2:
                    self.set_status(cid, "screened_out", "screener returned no decision twice")
                continue
            add_event(state, "screened", decision=decision["decision"], reason=decision["reason"], log=agent["log"])
            if decision["decision"] == "approve":
                state["screener_notes"] = decision["builder_notes"]
                state["preexisting_data"] = any((DATA_ROOT / sub / cid).exists() for sub in DATA_SUBDIRS_PRUNABLE)
                state["breadth_keys"] = {key: decision.get(key, "") for key in ("measurement_type", "instrument_line", "archive_collection")}
                save_state(cid, state)
                archives = {host for host in (url_archive(url) for url in state.get("resource_urls", [])) if host and not is_multi_tenant(host)}
                verdict, why = self.archive_gate(cid, archives)
                self.set_status(cid, "queued", decision["reason"], priority=decision["priority"])
                if verdict == "signoff":
                    self.hold_for_signoff(cid, why)
            else:
                save_state(cid, state)
                self.set_status(cid, "screened_out", decision["reason"])
        log(f"screened {len(cids)} candidates (cost ${agent['cost']:.2f})")

    def apply_builder(self, cid: str, phase: str, agent: dict) -> None:
        state = load_state(cid)
        state["builder_session"] = agent["session_id"]
        if not agent["ok"]:
            state["agent_failures"] = int(state.get("agent_failures", 0)) + 1
            add_event(state, "builder_error", phase=phase, error=agent["error"], log=agent["log"])
            save_state(cid, state)
            log(f"builder {cid} ({phase}) failed: {agent['error']}")
            if "budget" in agent["error"].lower():
                self.terminal(cid, "deferred", f"builder exceeded the ${self.cfg.budgets_usd['builder']:.0f} per-phase agent budget in the {phase} phase",
                              "Retry with a larger builder budget or a narrower recipe scope.", None)
                return
            if state["agent_failures"] > self.cfg.max_agent_failures:
                self.set_status(cid, PAUSED, f"builder failed repeatedly: {agent['error']}")
            return
        state["agent_failures"] = 0
        out = agent["structured"]
        state["builder_summary"] = out.get("summary", "")
        add_event(state, "builder", phase=phase, status=out.get("status"), log=agent["log"], cost=agent["cost"])
        if out.get("expected_download_bytes"):
            state["expected_download_bytes"] = int(out["expected_download_bytes"])
        save_state(cid, state)
        status = out.get("status")
        if status == "abandon":
            registry_status = out.get("abandon_status") or "rejected"
            self.terminal(cid, registry_status, out.get("registry_reason", ""), out.get("retry_condition", ""), out.get("attempt_markdown", ""))
        elif status == "ready_for_download" or not state.get("download_sha"):
            if not (STAGING_DIR / cid / "download.sh").exists():
                self.set_status(cid, "needs_repair" if phase == "repair" else "queued", "builder reported ready but download.sh is missing")
                return
            self.set_status(cid, "ready_for_download", f"builder {phase}: ready for download")
        else:
            state["build_cycles"] = int(state.get("build_cycles", 0)) + 1
            save_state(cid, state)
            if state["build_cycles"] > self.cfg.max_build_cycles:
                self.terminal(cid, "deferred", f"recipe did not pass the driver rebuild check after {self.cfg.max_build_cycles} cycles",
                              "Revisit manually; see the driver rebuild logs.", None)
                return
            self.set_status(cid, "built", f"builder {phase}: ready for judge")

    def apply_download(self, cid: str, result: dict) -> None:
        state = load_state(cid)
        state["last_download"] = {key: result[key] for key in ("rc", "reason", "bytes", "seconds", "log", "tail")}
        state["bytes"] = result["bytes"]
        state["last_rebuild"] = None
        ok = result["rc"] == 0 and not result["reason"]
        if not ok:
            state["download_sha"] = ""
        add_event(state, "download", rc=result["rc"], reason=result["reason"], bytes=result["bytes"], log=result["log"])
        save_state(cid, state)
        log(f"download {cid}: rc={result['rc']} {result['reason']} bytes={result['bytes']:,} in {result['seconds']} s")
        self.set_status(cid, "downloaded", "download ok" if ok else f"download failed: {result['reason'] or 'rc=' + str(result['rc'])}")

    def apply_rebuild(self, cid: str, result: dict) -> None:
        state = load_state(cid)
        state["last_rebuild"] = result
        state["bytes"] = candidate_bytes(cid)
        add_event(state, "rebuild", ok=result["ok"])
        save_state(cid, state)
        if not result["ok"]:
            self.set_status(cid, "downloaded", "driver rebuild check failed")
            return
        similarity = result.get("similarity") or {"verdict": "ERROR", "error": "no similarity report"}
        state["similarity"] = similarity
        save_state(cid, state)
        verdict = similarity.get("verdict")
        if verdict == "WEAK":
            matches = "; ".join(
                f"{series['key'].split(':')[-1]} ~ {series['match']['key']} (distance {series['match']['distance']}, loss {series['match']['loss']:+.3f})"
                for series in similarity.get("series", []) if series.get("match")
            )
            self.terminal(cid, "rejected",
                          f"byte-level breadth: every primary series is compression- and feature-equivalent to an existing family: {matches}",
                          "Retry only with material whose bytes differ measurably (zlsim.py gate) from the existing families.", None)
        elif verdict == "ERROR":
            self.set_status(cid, PAUSED, f"similarity gate failed: {one_line(similarity.get('error', ''), 300)}")
        else:
            self.set_status(cid, "ready_for_judge", f"driver rebuild, verify, gate and similarity ({verdict}) passed")

    def apply_judge(self, cid: str, agent: dict) -> None:
        state = load_state(cid)
        if not agent["ok"]:
            state["agent_failures"] = int(state.get("agent_failures", 0)) + 1
            add_event(state, "judge_error", error=agent["error"], log=agent["log"])
            save_state(cid, state)
            log(f"judge {cid} failed: {agent['error']}")
            if "budget" in agent["error"].lower() or state["agent_failures"] > self.cfg.max_agent_failures:
                self.set_status(cid, PAUSED, f"judge failed repeatedly: {agent['error']}")
            return
        state["agent_failures"] = 0
        out = agent["structured"]
        decision = out["decision"]
        add_event(state, "judge", decision=decision, summary=out.get("summary", ""), log=agent["log"], cost=agent["cost"])
        state["judge_summary"] = out.get("summary", "")
        save_state(cid, state)
        self.row(cid)["novelty_kind"] = out.get("novelty_kind", "")
        if decision == "accept" and out.get("novelty_kind") == "not_new":
            decision = "rejected"
            out["registry_reason"] = out.get("registry_reason") or "Judge labeled the material not new."
        if decision == "accept":
            verdict, why = self.archive_gate(cid, recipe_archives(STAGING_DIR / cid))
            if verdict == "signoff":
                log(f"judge {cid}: accept held for archive sign-off — {why}")
                self.hold_for_signoff(cid, why)
                return
            # Breadth is measured on bytes (zlsim), not judged from names.
            measured = (state.get("similarity") or {}).get("verdict")
            if measured in COUNTED_VERDICTS:
                out["breadth_verdict"] = measured
        log(f"judge {cid}: {decision} — {one_line(out.get('summary', ''), 300)}")
        if decision == "accept":
            self.promote(cid, out)
        elif decision == "repair":
            if int(state.get("repair_cycles", 0)) >= self.cfg.max_repair_cycles:
                self.terminal(cid, "deferred", f"still needs repair after {self.cfg.max_repair_cycles} cycles: {out['summary']}",
                              out.get("retry_condition") or one_line(out.get("repair_instructions", ""), 600), out.get("report_markdown", ""))
                return
            state["repair_cycles"] = int(state.get("repair_cycles", 0)) + 1
            state["repair_instructions"] = out.get("repair_instructions", "")
            save_state(cid, state)
            self.set_status(cid, "needs_repair", out.get("summary", ""))
        else:
            self.terminal(cid, decision, out.get("registry_reason") or out.get("summary", ""), out.get("retry_condition", ""), out.get("report_markdown", ""))

    # terminal transitions
    def shared_files_clean(self) -> bool:
        dirty = git("status", "--porcelain", "--", *SHARED_FILES).stdout.strip()
        if dirty:
            self.pause_globally(f"shared ledger files modified outside the driver: {dirty}")
            return False
        return True

    def promote(self, cid: str, out: dict) -> None:
        if not self.shared_files_clean():
            return
        row = self.row(cid)
        source, target = STAGING_DIR / cid, DATASETS_DIR / cid
        gate = subprocess.run([sys.executable, "tools/autocollect/gate.py", f"staging/{cid}", "--json"], cwd=REPO_ROOT, text=True, capture_output=True)
        if gate.returncode != 0:
            self.send_back(cid, f"gate failed at promotion: {one_line(gate.stdout, 1500)}")
            return
        shutil.move(str(source), str(target))
        verify_log = LOGS_DIR / cid / f"promotion_verify.{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        rc, reason = run_proc(["bash", f"datasets/{cid}/verify.sh"], log_path=verify_log, timeout_s=self.cfg.build_timeout_s, poll_s=self.cfg.poll_s)
        if rc != 0:
            shutil.move(str(target), str(source))
            self.send_back(cid, f"verify.sh failed after moving to datasets/ (rc={rc} {reason}): {tail(verify_log, 30)}")
            return
        width = row["width"]
        report_path = REPO_ROOT / "reports" / f"{width}bit_{cid}_development_{today()}.md"
        write_atomic(report_path, clean_markdown(out["report_markdown"]))
        append_registry(
            {
                "dataset_id": cid,
                "status": "accepted",
                "active_path": f"datasets/{cid}/manifest.toml",
                "evidence_path": str(report_path.relative_to(REPO_ROOT)),
                "replacement_id": "",
                "reason": out.get("registry_reason") or out.get("summary", ""),
                "retry_condition": "Already accepted.",
            }
        )
        subprocess.run([sys.executable, "tools/audit_acceptance.py"], cwd=REPO_ROOT, text=True, capture_output=True, check=False)
        verdict = out.get("breadth_verdict") or "WEAK"
        append_breadth(
            {
                "dataset_id": cid,
                "origin": "autocollect",
                "widths": ",".join(str(width) for width in accepted_widths().get(cid, [])),
                "measurement_type": out.get("measurement_type", ""),
                "instrument_line": out.get("instrument_line", ""),
                "archive_collection": out.get("archive_collection", ""),
                "other_types": "",
                "verdict": verdict,
            }
        )
        self.row(cid)["breadth"] = verdict
        self.set_status(cid, "accepted", one_line(out.get("registry_reason") or out.get("summary", ""), 400))
        try:
            name = tomllib.loads((target / "manifest.toml").read_text(encoding="utf-8")).get("name") or cid
        except tomllib.TOMLDecodeError:
            name = cid
        paths = [f"datasets/{cid}", str(report_path.relative_to(REPO_ROOT)), *SHARED_FILES, "pipeline"]
        if commit(paths, f"Add {name}\n\nAccepted by the autocollect judge ({row['novelty_kind'] or 'novelty unlabeled'}, breadth {verdict})."):
            self.terminal_this_run += 1
            sha = git("rev-parse", "--short", "HEAD").stdout.strip()
            subprocess.run([*ZLSIM, "adopt", cid], cwd=REPO_ROOT, text=True, capture_output=True, check=False)
            have = len(progress()[int(width)])
            notify(self.cfg, f"autocollect accepted {cid} ({width}-bit, {row['novelty_kind']}, breadth {verdict}): {name}. "
                             f"{width}-bit progress {have}/{load_baseline()['target_new_per_width']}. Commit {sha}.")
        else:
            self.pause_globally(f"could not commit accepted dataset {cid}; files are promoted but uncommitted")

    def send_back(self, cid: str, reason: str) -> None:
        state = load_state(cid)
        state["repair_instructions"] = reason
        state["repair_cycles"] = int(state.get("repair_cycles", 0)) + 1
        save_state(cid, state)
        log(f"{cid}: sent back to builder: {one_line(reason, 300)}")
        self.set_status(cid, "needs_repair", one_line(reason, 300))

    def terminal(self, cid: str, status: str, reason: str, retry: str, markdown: str | None) -> None:
        if status not in REGISTRY_TERMINALS:
            status = "rejected"
        if not self.shared_files_clean():
            return
        row = self.row(cid)
        state = load_state(cid)
        attempt_path = REPO_ROOT / "attempts" / f"{today()}_{status}_{cid}.md"
        if not markdown or not markdown.strip():
            events = "\n".join(f"  - {event['at']} {event['kind']}: {one_line(json.dumps({k: v for k, v in event.items() if k not in ('at', 'kind')}), 300)}" for event in state.get("events", [])[-12:])
            markdown = (
                f"# {cid}\n\n- Date: {dt.date.today().isoformat()}\n- Status: {status}\n- Candidate dataset: {row['title']}\n"
                f"- Source: {row['source_url']}\n- Why it looked promising: see `pipeline/cards/{cid}.md`\n"
                f"- Failure class: autocollect driver limit\n- What happened: {reason}\n- Evidence:\n{events}\n"
                f"- Logs: `.data/pipeline/logs/{cid}/`, `.data/logs/{cid}/`\n- Decision: {status}\n- Retry conditions: {retry}\n"
            )
        write_atomic(attempt_path, clean_markdown(markdown))
        append_registry(
            {
                "dataset_id": cid,
                "status": status,
                "active_path": "",
                "evidence_path": str(attempt_path.relative_to(REPO_ROOT)),
                "replacement_id": "",
                "reason": reason,
                "retry_condition": retry,
            }
        )
        if (STAGING_DIR / cid).exists():
            ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
            shutil.move(str(STAGING_DIR / cid), str(ARCHIVE_DIR / f"{cid}-{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}"))
        if not self.cfg.keep_rejected_data and not state.get("preexisting_data"):
            for sub in DATA_SUBDIRS_PRUNABLE:
                shutil.rmtree(DATA_ROOT / sub / cid, ignore_errors=True)
            state["bytes"] = 0
            save_state(cid, state)
        self.set_status(cid, status, reason)
        if commit([str(attempt_path.relative_to(REPO_ROOT)), "attempts/dataset_status.tsv", "pipeline"], f"Record {status.replace('_', ' ')} {cid}"):
            self.terminal_this_run += 1
            notify(self.cfg, f"autocollect {status} {cid} ({row['width']}-bit): {one_line(reason, 400)}")
        else:
            self.pause_globally(f"could not commit terminal record for {cid}")

    # main loop
    def heartbeat(self) -> None:
        write_atomic(
            HEARTBEAT_PATH,
            json.dumps(
                {
                    "at": now_iso(),
                    "pid": os.getpid(),
                    "started_at": self.started_at,
                    "inflight": [{key: value for key, value in meta.items() if key != "future"} for meta in self.futures.values()],
                    "cost_this_run_usd": round(total_cost(self.started_at), 2),
                    "terminal_this_run": self.terminal_this_run,
                    "winding_down": self.winding_down(),
                },
                indent=1,
            ),
        )

    def process_control(self) -> None:
        """Apply commands queued by approve-breadth / reject / requeue while running."""
        if not CONTROL_PATH.exists():
            return
        claimed = CONTROL_PATH.with_suffix(".processing")
        CONTROL_PATH.replace(claimed)
        for line in claimed.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            command = json.loads(line)
            cid = command.get("candidate_id", "")
            if not any(row["candidate_id"] == cid for row in self.ledger) or self.busy(cid):
                log(f"control: ignored {command}")
                continue
            log(f"control: {command}")
            if command["action"] == "approve-breadth":
                state = load_state(cid)
                state["breadth_approved"] = True
                state["breadth_approval_note"] = command.get("note") or state.get("breadth_signoff", "")
                restore = state.pop("paused_from", "") or "queued"
                add_event(state, "breadth_approved", note=state["breadth_approval_note"])
                save_state(cid, state)
                self.set_status(cid, restore, "breadth sign-off approved by the user")
            elif command["action"] == "reject":
                self.terminal(cid, "rejected", command["reason"], command.get("retry", ""), None)
            elif command["action"] == "reopen":
                if not self.shared_files_clean():
                    continue
                summary = reopen_candidate(cid)
                self.set_status(cid, "ready_for_download", f"reopened for re-measurement ({summary})")
                commit(["attempts/dataset_status.tsv", "pipeline"], f"Reopen {cid} for re-measurement")
            elif command["action"] == "requeue":
                state = load_state(cid)
                state["agent_failures"] = 0
                save_state(cid, state)
                self.set_status(cid, command.get("status", "queued"), "requeued by the user")
        claimed.unlink()

    def goal_reached(self) -> bool:
        return all(deficit <= 0 for deficit in self.deficits().values())

    def run(self) -> int:
        def on_signal(signum, frame):  # noqa: ARG001
            if self.stopping:
                log("second interrupt: killing in-flight work")
                SHUTTING_DOWN.set()
                for pgid in list(LIVE_GROUPS):
                    try:
                        os.killpg(pgid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                return
            self.stopping = True
            log("interrupt: finishing in-flight work, launching nothing new (interrupt again to kill)")

        signal.signal(signal.SIGINT, on_signal)
        signal.signal(signal.SIGTERM, on_signal)
        log(f"driver start: {dataclasses.asdict(self.cfg)}")
        while True:
            self.process_control()
            done = [future for future in self.futures if future.done()]
            for future in done:
                meta = self.futures.pop(future)
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001
                    log(f"task {meta} crashed: {exc!r}")
                    continue
                self.apply(meta, result)
            if SHUTTING_DOWN.is_set() and not self.futures:
                break
            self.schedule()
            self.heartbeat()
            if not self.futures:
                log("nothing left to launch and nothing in flight; stopping")
                break
            time.sleep(self.cfg.poll_s)
        self.heartbeat()
        pending = git("status", "--porcelain", "--", "pipeline").stdout.strip()
        if pending:
            commit(["pipeline"], "Update autocollect ledger")
        summary = f"driver stop: goal_reached={self.goal_reached()} paused={self.paused()} cost_this_run=${total_cost(self.started_at):.2f}"
        log(summary)
        new = progress()
        notify(self.cfg, f"autocollect {summary}; new per width: " + ", ".join(f"{w}-bit {len(new[w])}" for w in WIDTHS))
        return 0


# ---------------------------------------------------------------- commands


def cmd_init(args) -> int:
    if BASELINE_PATH.exists() and not args.force:
        print(f"{BASELINE_PATH.relative_to(REPO_ROOT)} already exists; use --force to re-snapshot")
        return 1
    widths = accepted_widths()
    baseline = {
        "created": now_iso(),
        "target_new_per_width": args.target,
        "accepted_ids": sorted(widths),
        "accepted_per_width": {str(width): sum(1 for ws in widths.values() if width in ws) for width in WIDTHS},
    }
    write_atomic(BASELINE_PATH, json.dumps(baseline, indent=1) + "\n")
    if not LEDGER_PATH.exists():
        save_ledger([])
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    print(json.dumps(baseline["accepted_per_width"]))
    return 0


def cmd_status(args) -> int:  # noqa: ARG001
    baseline = load_baseline()
    target = int(baseline["target_new_per_width"])
    new = progress()
    ledger = load_ledger()
    beat = json.loads(HEARTBEAT_PATH.read_text()) if HEARTBEAT_PATH.exists() else {"inflight": []}
    # The ledger holds resting statuses only; the heartbeat says what is running now.
    live: dict[str, str] = {}
    for item in beat["inflight"]:
        cid = item.get("cid")
        if cid:
            live[cid] = {"builder": "authoring" if item.get("phase") == "author" else "building", "judge": "judging"}.get(item["kind"], "building")
    resting = {
        "proposed": "proposed", "queued": "waiting", "ready_for_download": "building", "downloaded": "building",
        "built": "building", "needs_repair": "building", "ready_for_judge": "judging", "accepted": "accepted",
        "screened_out": "screened_out", PAUSED: "paused", **{status: "not_accepted" for status in REGISTRY_TERMINALS},
    }
    groups = ["proposed", "waiting", "authoring", "building", "judging", "accepted", "screened_out", "not_accepted", "paused"]
    print(f"baseline {baseline['created']}, target +{target} accepted families per width\n")
    weak = {width: sum(1 for row in ledger if row["width"] == str(width) and row["status"] == "accepted"
                       and (row.get("breadth") or "").upper() not in COUNTED_VERDICTS) for width in WIDTHS}
    print(f"{'width':>5} {'base':>5} {'counted':>8} {'weak':>5}  " + " ".join(f"{name:>12}" for name in groups))
    for width in WIDTHS:
        rows = [row for row in ledger if row["width"] == str(width)]
        stage = [live.get(row["candidate_id"]) or resting.get(row["status"], row["status"]) for row in rows]
        print(f"{width:>5} {baseline['accepted_per_width'][str(width)]:>5} {len(new[width]):>4}/{target:<3} {weak[width]:>5}  " + " ".join(f"{stage.count(name):>12}" for name in groups))
    print("\ncounted = new families with a STRONG or OK breadth verdict (the goal); weak = accepted but same measurement type")
    print("waiting = screened and queued for a free builder slot; authoring = builder writing the recipe now;")
    print("building = download, build/verify, driver rebuild check, or repair; judging = with the judge or next in line")
    print(f"\ntotal agent cost: ${total_cost():.2f}")
    if PAUSE_PATH.exists():
        print(f"GLOBAL PAUSE: {json.loads(PAUSE_PATH.read_text())['reason']}  (inspect, then `driver.py unpause`)")
    if beat.get("at"):
        inflight = ", ".join(
            f"{item['kind']}:{item.get('cid') or item.get('width') or ','.join(item.get('cids', []))}" for item in beat["inflight"]
        )
        print(f"last heartbeat {beat['at']} pid {beat['pid']}; in flight: {inflight or 'none'}")
    for row in ledger:
        if row["status"] == PAUSED:
            print(f"paused {row['candidate_id']}: {row['reason']}")
    return 0


def describe_tool_use(item: dict) -> str:
    args = item.get("input") or {}
    detail = args.get("command") or args.get("natural_language_query") or args.get("query") or args.get("url") or args.get("file_path") or args.get("pattern")
    return f"{item.get('name', '?')}: {one_line(detail if detail else json.dumps(args), 160)}"


def cmd_activity(args) -> int:
    """Latest steps of recent agent sessions, from their streamed transcripts."""
    cutoff = time.time() - args.minutes * 60
    logs = sorted(
        (path for path in LOGS_DIR.glob("*/*.jsonl") if path.stat().st_mtime >= cutoff),
        key=lambda path: path.stat().st_mtime,
    )
    if not logs:
        print(f"no agent transcripts updated in the last {args.minutes} minutes")
    for path in logs:
        steps: list[str] = []
        finished = ""
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "assistant":
                for item in (event.get("message") or {}).get("content") or []:
                    if isinstance(item, dict) and item.get("type") == "tool_use":
                        steps.append(describe_tool_use(item))
            elif event.get("type") == "result":
                finished = f"finished: {event.get('subtype')}, ${float(event.get('total_cost_usd') or 0):.2f}, {event.get('num_turns')} turns"
        age = int(time.time() - path.stat().st_mtime)
        print(f"== {path.parent.name}/{path.name}  ({len(steps)} steps, updated {age}s ago) {finished or 'running'}")
        for step in steps[-args.lines:]:
            print(f"   {step}")
    return 0


def transcript_lines(raw: bytes) -> list[str]:
    """Readable lines (tool calls, short narration, results) from stream-json events."""
    lines: list[str] = []
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "assistant":
            for item in (event.get("message") or {}).get("content") or []:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "tool_use":
                    lines.append(describe_tool_use(item))
                elif item.get("type") == "text" and item.get("text", "").strip():
                    lines.append("> " + one_line(item["text"], 300))
        elif event.get("type") == "result":
            lines.append(f"finished: {event.get('subtype')}, ${float(event.get('total_cost_usd') or 0):.2f}, {event.get('num_turns')} turns")
    return lines


def cmd_follow(args) -> int:
    """Print new agent steps and driver events continuously, like tail -f."""
    width = shutil.get_terminal_size((160, 40)).columns
    started = time.time()
    offsets: dict[Path, int] = {}

    def emit(label: str, text: str) -> None:
        print(f"{time.strftime('%H:%M:%S')} {label[:38]:<38} {text}"[:width], flush=True)

    for path in sorted(LOGS_DIR.glob("*/*.jsonl"), key=lambda path: path.stat().st_mtime):
        offsets[path] = path.stat().st_size
        if args.backlog and path.stat().st_mtime >= started - 600:
            for text in transcript_lines(path.read_bytes())[-args.backlog:]:
                emit(f"{path.parent.name} {path.stem.split('.')[0]}", text)
    driver_offset = DRIVER_LOG.stat().st_size if DRIVER_LOG.exists() else 0
    try:
        while True:
            for path in sorted(LOGS_DIR.glob("*/*.jsonl")):
                size = path.stat().st_size
                offset = offsets.setdefault(path, 0)
                if size <= offset:
                    continue
                with path.open("rb") as fh:
                    fh.seek(offset)
                    chunk = fh.read(size - offset)
                end = chunk.rfind(b"\n")
                if end < 0:
                    continue
                offsets[path] = offset + end + 1
                for text in transcript_lines(chunk[: end + 1]):
                    emit(f"{path.parent.name} {path.stem.split('.')[0]}", text)
            if DRIVER_LOG.exists() and DRIVER_LOG.stat().st_size > driver_offset:
                with DRIVER_LOG.open("rb") as fh:
                    fh.seek(driver_offset)
                    chunk = fh.read()
                end = chunk.rfind(b"\n")
                if end >= 0:
                    driver_offset += end + 1
                    for line in chunk[: end + 1].decode("utf-8", errors="replace").splitlines():
                        emit("driver", one_line(line.split("] ", 1)[-1], 400))
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


def reopen_candidate(cid: str) -> str:
    """Restore an archived, non-accepted candidate to staging for re-measurement:
    drop its registry row (the attempt record stays as history) and send it back
    to the download step. Returns a summary; the caller commits."""
    archives = sorted(ARCHIVE_DIR.glob(f"{cid}-*"))
    if not archives:
        raise SystemExit(f"no archived recipe for {cid}")
    if (STAGING_DIR / cid).exists():
        raise SystemExit(f"staging/{cid} already exists")
    shutil.move(str(archives[-1]), str(STAGING_DIR / cid))
    lines = REGISTRY_PATH.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if line.split("\t", 1)[0] != cid]
    REGISTRY_PATH.write_text("\n".join(kept) + "\n", encoding="utf-8")
    state = load_state(cid)
    for key in ("download_cycles", "build_cycles", "repair_cycles", "agent_failures", "download_sha", "last_download",
                "last_rebuild", "similarity", "bytes"):
        state.pop(key, None)
    add_event(state, "reopened", archive=archives[-1].name)
    save_state(cid, state)
    return f"restored {archives[-1].name}, registry row removed"


def driver_running() -> bool:
    if not LOCK_PATH.exists():
        return False
    with LOCK_PATH.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle, fcntl.LOCK_UN)
    return False


def queue_control(command: dict) -> int:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with CONTROL_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(command) + "\n")
    print(f"queued for the running driver: {command}")
    return 0


def cmd_approve_breadth(args) -> int:
    if driver_running():
        return queue_control({"action": "approve-breadth", "candidate_id": args.candidate_id, "note": args.note})
    rows = load_ledger()
    row = next((item for item in rows if item["candidate_id"] == args.candidate_id), None)
    if row is None:
        print(f"unknown candidate {args.candidate_id}")
        return 1
    state = load_state(args.candidate_id)
    if not state.get("breadth_signoff"):
        print(f"{args.candidate_id} has no pending breadth sign-off")
        return 1
    state["breadth_approved"] = True
    state["breadth_approval_note"] = args.note or state["breadth_signoff"]
    restore = state.pop("paused_from", "") or "queued"
    add_event(state, "breadth_approved", note=state["breadth_approval_note"])
    save_state(args.candidate_id, state)
    row["status"], row["updated"] = restore, now_iso()
    save_ledger(rows)
    print(f"{args.candidate_id}: breadth override approved; back to {restore}")
    return 0


def cmd_reject(args) -> int:
    if driver_running():
        return queue_control({"action": "reject", "candidate_id": args.candidate_id, "reason": args.reason, "retry": args.retry})
    rows = load_ledger()
    if not any(item["candidate_id"] == args.candidate_id for item in rows):
        print(f"unknown candidate {args.candidate_id}")
        return 1
    Driver(Config()).terminal(args.candidate_id, "rejected", args.reason, args.retry, None)
    print(f"{args.candidate_id}: recorded as rejected")
    return 0


def cmd_reopen(args) -> int:
    if driver_running():
        return queue_control({"action": "reopen", "candidate_id": args.candidate_id})
    summary = reopen_candidate(args.candidate_id)
    rows = load_ledger()
    for row in rows:
        if row["candidate_id"] == args.candidate_id:
            row["status"], row["updated"], row["reason"] = "ready_for_download", now_iso(), f"reopened for re-measurement ({summary})"
    save_ledger(rows)
    commit(["attempts/dataset_status.tsv", "pipeline"], f"Reopen {args.candidate_id} for re-measurement")
    print(f"{args.candidate_id}: {summary}")
    return 0


def cmd_requeue(args) -> int:
    if driver_running():
        return queue_control({"action": "requeue", "candidate_id": args.candidate_id, "status": args.status})
    rows = load_ledger()
    for row in rows:
        if row["candidate_id"] == args.candidate_id:
            row["status"] = args.status
            row["updated"] = now_iso()
            save_ledger(rows)
            state = load_state(args.candidate_id)
            state["agent_failures"] = 0
            save_state(args.candidate_id, state)
            print(f"{args.candidate_id} -> {args.status}")
            return 0
    print(f"unknown candidate {args.candidate_id}")
    return 1


def cmd_unpause(args) -> int:  # noqa: ARG001
    if PAUSE_PATH.exists():
        print(f"clearing pause: {json.loads(PAUSE_PATH.read_text())['reason']}")
        PAUSE_PATH.unlink()
    return 0


def proxy_identity() -> str:
    """The forward proxy's view of this process: the X-FB-IP-Type header."""
    probe = subprocess.run(
        ["curl", "-sv", "-o", "/dev/null", "-r", "0-0", "--max-time", "20", IDENTITY_PROBE_URL],
        text=True, capture_output=True, env=child_env(),
    )
    for line in probe.stderr.splitlines():
        if "X-FB-IP-Type:" in line:
            return line.split("X-FB-IP-Type:", 1)[1].strip()
    return ""


def cmd_run(args) -> int:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    lock = LOCK_PATH.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("another driver is running")
        return 1
    load_baseline()
    if PAUSE_PATH.exists():
        print(f"pipeline is paused: {json.loads(PAUSE_PATH.read_text())['reason']}\ninspect, then run `driver.py unpause`")
        return 1
    dirty_shared = git("status", "--porcelain", "--", *SHARED_FILES).stdout.strip()
    if dirty_shared:
        print(f"commit or revert these first; the driver appends to them and commits them:\n{dirty_shared}")
        return 1
    hygiene = subprocess.run([sys.executable, "tools/check_repo_hygiene.py"], cwd=REPO_ROOT, text=True, capture_output=True)
    if hygiene.returncode != 0:
        print(f"tools/check_repo_hygiene.py fails; fix before running:\n{hygiene.stdout}{hygiene.stderr}")
        return 1
    if shutil.which("claude") is None:
        print("claude CLI not found")
        return 1
    identity = proxy_identity()
    if AGENT_ROLE_MARKER not in identity and not args.allow_user_identity_downloads:
        print(
            "refusing to start: download.sh scripts are agent-written, so the driver must run under the\n"
            "secure-internet agent role, but the forward proxy sees this process as: " + (identity or "(no identity header)") + "\n"
            "Launch the driver from a Claude Code session started with --secure-internet-mode (see\n"
            "tools/autocollect/README.md). --allow-user-identity-downloads overrides this; not recommended."
        )
        return 1
    cfg = Config(
        agents=args.agents,
        downloads=args.downloads,
        widths=tuple(int(width) for width in args.widths.split(",")),
        max_cost_usd=args.max_cost_usd,
        stop_after=args.stop_after,
        model=args.model,
        effort=args.effort,
        download_cap_bytes=int(args.download_cap_gb * 1e9),
        disk_budget_bytes=int(args.disk_budget_gb * 1e9),
        keep_rejected_data=args.keep_rejected_data,
        notify_cmd=args.notify_cmd,
    )
    for item in filter(None, (args.role_effort or "").split(",")):
        role, _, level = item.partition("=")
        cfg.role_effort[role.strip()] = level.strip()
    if args.builder_autocompact:
        cfg.role_autocompact["builder"] = args.builder_autocompact
    return Driver(cfg).run()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="snapshot the baseline and create the ledger")
    init.add_argument("--target", type=int, default=50)
    init.add_argument("--force", action="store_true")
    sub.add_parser("status", help="progress per width and pipeline state")
    activity = sub.add_parser("activity", help="latest steps of recent agent sessions")
    activity.add_argument("--minutes", type=int, default=120, help="transcripts updated within this window")
    activity.add_argument("--lines", type=int, default=8, help="steps shown per session")
    follow = sub.add_parser("follow", help="continuously print new agent steps and driver events")
    follow.add_argument("--backlog", type=int, default=3, help="recent steps to show per active session at start")
    follow.add_argument("--interval", type=float, default=2.0)
    run = sub.add_parser("run", help="run the pipeline until the goal, a stop condition, or an interrupt")
    run.add_argument("--agents", type=int, default=3, help="concurrent agent sessions")
    run.add_argument("--downloads", type=int, default=2, help="concurrent download/rebuild subprocesses")
    run.add_argument("--widths", default=",".join(str(width) for width in WIDTHS))
    run.add_argument("--max-cost-usd", type=float, default=None, help="stop launching agents after this much spend in this run")
    run.add_argument("--stop-after", type=int, default=None, help="stop launching new work after N terminal decisions (pilot runs)")
    run.add_argument("--model", default=None)
    run.add_argument("--effort", default=None, choices=["low", "medium", "high", "xhigh", "max"], help="one effort for every role (overrides --role-effort)")
    run.add_argument("--role-effort", default=None, help="per-role effort overrides, e.g. scout=low,builder=medium (defaults: scout/screener medium, builder high, judge xhigh)")
    run.add_argument("--builder-autocompact", default=None, help="builder context compaction window (default 300k; 'auto' for the CLI default)")
    run.add_argument("--download-cap-gb", type=float, default=5.0)
    run.add_argument("--disk-budget-gb", type=float, default=500.0)
    run.add_argument("--keep-rejected-data", action="store_true")
    run.add_argument("--notify-cmd", default=None, help="shell command receiving each milestone message on stdin (e.g. a pingme script)")
    run.add_argument("--allow-user-identity-downloads", action="store_true",
                     help="run downloads even when the driver is not under the secure-internet agent role (not recommended)")
    requeue = sub.add_parser("requeue", help="reset a candidate's status (e.g. after a pause)")
    requeue.add_argument("candidate_id")
    requeue.add_argument("--status", default="queued", choices=ACTIVE_STATUSES)
    sub.add_parser("unpause", help="clear a global pause after inspecting its cause")
    reopen = sub.add_parser("reopen", help="restore an archived rejected candidate for re-measurement")
    reopen.add_argument("candidate_id")
    approve = sub.add_parser("approve-breadth", help="approve a pending breadth override or archive-cap sign-off")
    approve.add_argument("candidate_id")
    approve.add_argument("--note", default="", help="why the override is justified")
    reject = sub.add_parser("reject", help="record a candidate as rejected (e.g. a refused breadth sign-off)")
    reject.add_argument("candidate_id")
    reject.add_argument("--reason", required=True)
    reject.add_argument("--retry", default="Retry only with the user's explicit approval.")
    args = parser.parse_args()
    return {"init": cmd_init, "status": cmd_status, "activity": cmd_activity, "follow": cmd_follow, "run": cmd_run, "requeue": cmd_requeue, "unpause": cmd_unpause,
            "approve-breadth": cmd_approve_breadth, "reject": cmd_reject, "reopen": cmd_reopen}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
