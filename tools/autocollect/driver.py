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
  driver.py run [--agents 3] [--downloads 2] [--widths 8,16] [--stop-after N] [--max-cost-usd X]
  driver.py requeue <candidate_id> [--status queued]
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


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / ".data"
PIPELINE_DIR = REPO_ROOT / "pipeline"
CARDS_DIR = PIPELINE_DIR / "cards"
LEDGER_PATH = PIPELINE_DIR / "candidates.tsv"
BASELINE_PATH = PIPELINE_DIR / "baseline.json"
REGISTRY_PATH = REPO_ROOT / "attempts" / "dataset_status.tsv"
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

WIDTHS = (8, 16, 32, 64)
LEDGER_COLUMNS = ["candidate_id", "width", "status", "priority", "title", "source_url", "novelty_kind", "updated", "reason"]
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
    queue_low_water: int = 3
    screen_batch: int = 8
    download_cap_bytes: int = 5_000_000_000
    download_timeout_s: int = 6 * 3600
    build_timeout_s: int = 4 * 3600
    min_free_bytes: int = 200_000_000_000
    disk_budget_bytes: int = 500_000_000_000
    max_download_cycles: int = 4
    max_build_cycles: int = 4
    max_repair_cycles: int = 2
    max_agent_failures: int = 2
    budgets_usd: dict = dataclasses.field(default_factory=lambda: {"scout": 10.0, "screener": 8.0, "builder": 40.0, "judge": 15.0})
    timeouts_s: dict = dataclasses.field(default_factory=lambda: {"scout": 5400, "screener": 5400, "builder": 4 * 3600, "judge": 2 * 3600})
    max_cost_usd: float | None = None
    stop_after: int | None = None
    model: str | None = None
    effort: str | None = None
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


def progress() -> dict[int, list[str]]:
    baseline = load_baseline()
    known = set(baseline["accepted_ids"])
    new: dict[int, list[str]] = {width: [] for width in WIDTHS}
    for dataset_id, widths in accepted_widths().items():
        if dataset_id in known:
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
                    "homogeneity_notes": STR,
                    "risks": STR,
                    "probe_evidence": STR,
                },
                "required": [
                    "candidate_id", "width", "numeric_kind", "title", "quantity", "source_url", "resource_urls",
                    "license", "license_evidence_url", "license_quote", "natural_record", "est_samples",
                    "est_primary_values", "est_download_bytes", "est_primary_bytes", "decode_path",
                    "novelty_kind", "novelty_evidence", "homogeneity_notes", "risks", "probe_evidence",
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
                },
                "required": ["candidate_id", "decision", "priority", "reason", "builder_notes"],
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
        "summary": STR,
        "checks": {"type": "object", "properties": {check: STR for check in JUDGE_CHECKS}, "required": JUDGE_CHECKS},
        "repair_instructions": STR,
        "registry_reason": STR,
        "retry_condition": STR,
        "report_markdown": STR,
    },
    "required": ["decision", "novelty_kind", "summary", "checks", "repair_instructions", "registry_reason", "retry_condition", "report_markdown"],
}


def run_agent(cfg: Config, role: str, subject: str, prompt: str, schema: dict, session_id: str | None = None, resume: bool = False) -> dict:
    session_id = session_id or str(uuid.uuid4())
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
    ]
    cmd += ["--resume", session_id] if resume else ["--session-id", session_id]
    if cfg.model:
        cmd += ["--model", cfg.model]
    if cfg.effort:
        cmd += ["--effort", cfg.effort]
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
        ("Novelty evidence", candidate["novelty_evidence"]),
        ("Homogeneity", candidate["homogeneity_notes"]),
        ("Risks", candidate["risks"]),
        ("Probe evidence", candidate["probe_evidence"]),
    ]
    lines += [f"- {name}: {one_line(value, 2000)}" for name, value in fields]
    lines += ["", f"Proposed by the autocollect scout on {dt.date.today().isoformat()} (transcript `{scout_log}`)."]
    return "\n".join(lines) + "\n"


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
        f"Builder summary:\n{state.get('builder_summary', '(none)')}\n"
    )


# ---------------------------------------------------------------- tasks (worker threads)


def task_download(cfg: Config, cid: str) -> dict:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / cid / f"download.{stamp}.log"

    def monitor() -> str:
        used = candidate_bytes(cid)
        return f"byte cap exceeded ({used:,} > {cfg.download_cap_bytes:,})" if used > cfg.download_cap_bytes else ""

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
    return {"kind": "rebuild", "cid": cid, "ok": bool(report.get("ok")), "steps": steps, "gate": report}


def task_agent(cfg: Config, kind: str, role: str, subject: str, prompt: str, schema: dict, payload: dict, session_id: str | None = None, resume: bool = False) -> dict:
    result = run_agent(cfg, role, subject, prompt, schema, session_id=session_id, resume=resume)
    if not result["ok"] and resume and result["seconds"] < 120 and result["cost"] < 0.5:
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
        if unexpected:
            self.pause_globally(f"unexpected repository changes outside staging/: {sorted(unexpected)[:20]}")

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
            if deficits[width] <= 0 or any(meta.get("width") == width for meta in self.inflight("scout")):
                continue
            waiting = sum(1 for row in self.ledger if row["width"] == str(width) and row["status"] in {"proposed", "queued"})
            if waiting < self.cfg.queue_low_water:
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
            add_event(state, "proposed", log=agent["log"])
            save_state(cid, state)
            known.add(cid)
            seen_urls.add(url)
            added += 1
        save_ledger(self.ledger)
        log(f"scout {width}-bit proposed {added} candidates (cost ${agent['cost']:.2f})")

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
                save_state(cid, state)
                self.set_status(cid, "queued", decision["reason"], priority=decision["priority"])
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
        if result["ok"]:
            self.set_status(cid, "ready_for_judge", "driver rebuild, verify and gate passed")
        else:
            self.set_status(cid, "downloaded", "driver rebuild check failed")

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
        write_atomic(report_path, out["report_markdown"].rstrip() + "\n")
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
        self.set_status(cid, "accepted", one_line(out.get("registry_reason") or out.get("summary", ""), 400))
        try:
            name = tomllib.loads((target / "manifest.toml").read_text(encoding="utf-8")).get("name") or cid
        except tomllib.TOMLDecodeError:
            name = cid
        paths = [f"datasets/{cid}", str(report_path.relative_to(REPO_ROOT)), *SHARED_FILES, "pipeline"]
        if commit(paths, f"Add {name}\n\nAccepted by the autocollect judge ({row['novelty_kind'] or 'novelty unlabeled'})."):
            self.terminal_this_run += 1
            sha = git("rev-parse", "--short", "HEAD").stdout.strip()
            have = len(progress()[int(width)])
            notify(self.cfg, f"autocollect accepted {cid} ({width}-bit, {row['novelty_kind']}): {name}. "
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
        write_atomic(attempt_path, markdown.rstrip() + "\n")
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

    def goal_reached(self) -> bool:
        return all(deficit <= 0 for deficit in self.deficits().values())

    def run(self) -> int:
        def on_signal(signum, frame):  # noqa: ARG001
            if self.stopping:
                log("second interrupt: killing in-flight work")
                for pgid in list(LIVE_GROUPS):
                    try:
                        os.killpg(pgid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                raise SystemExit(130)
            self.stopping = True
            log("interrupt: finishing in-flight work, launching nothing new (interrupt again to kill)")

        signal.signal(signal.SIGINT, on_signal)
        signal.signal(signal.SIGTERM, on_signal)
        log(f"driver start: {dataclasses.asdict(self.cfg)}")
        while True:
            done = [future for future in self.futures if future.done()]
            for future in done:
                meta = self.futures.pop(future)
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001
                    log(f"task {meta} crashed: {exc!r}")
                    continue
                self.apply(meta, result)
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
    groups = [
        ("proposed", {"proposed"}),
        ("queued", {"queued"}),
        ("building", {"ready_for_download", "downloaded", "built", "needs_repair"}),
        ("judging", {"ready_for_judge"}),
        ("accepted", {"accepted"}),
        ("screened_out", {"screened_out"}),
        ("not_accepted", set(REGISTRY_TERMINALS)),
        ("paused", {PAUSED}),
    ]
    print(f"baseline {baseline['created']}, target +{target} accepted families per width\n")
    print(f"{'width':>5} {'base':>5} {'new':>7}  " + " ".join(f"{name:>12}" for name, _ in groups))
    for width in WIDTHS:
        counts = [sum(1 for row in ledger if row["width"] == str(width) and row["status"] in statuses) for _, statuses in groups]
        print(f"{width:>5} {baseline['accepted_per_width'][str(width)]:>5} {len(new[width]):>3}/{target:<3}  " + " ".join(f"{count:>12}" for count in counts))
    print(f"\ntotal agent cost: ${total_cost():.2f}")
    if PAUSE_PATH.exists():
        print(f"GLOBAL PAUSE: {json.loads(PAUSE_PATH.read_text())['reason']}  (inspect, then `driver.py unpause`)")
    if HEARTBEAT_PATH.exists():
        beat = json.loads(HEARTBEAT_PATH.read_text())
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


def cmd_requeue(args) -> int:
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
    run = sub.add_parser("run", help="run the pipeline until the goal, a stop condition, or an interrupt")
    run.add_argument("--agents", type=int, default=3, help="concurrent agent sessions")
    run.add_argument("--downloads", type=int, default=2, help="concurrent download/rebuild subprocesses")
    run.add_argument("--widths", default=",".join(str(width) for width in WIDTHS))
    run.add_argument("--max-cost-usd", type=float, default=None, help="stop launching agents after this much spend in this run")
    run.add_argument("--stop-after", type=int, default=None, help="stop launching new work after N terminal decisions (pilot runs)")
    run.add_argument("--model", default=None)
    run.add_argument("--effort", default=None, choices=["low", "medium", "high", "xhigh", "max"])
    run.add_argument("--download-cap-gb", type=float, default=5.0)
    run.add_argument("--disk-budget-gb", type=float, default=500.0)
    run.add_argument("--keep-rejected-data", action="store_true")
    run.add_argument("--notify-cmd", default=None, help="shell command receiving each milestone message on stdin (e.g. a pingme script)")
    requeue = sub.add_parser("requeue", help="reset a candidate's status (e.g. after a pause)")
    requeue.add_argument("candidate_id")
    requeue.add_argument("--status", default="queued", choices=ACTIVE_STATUSES)
    sub.add_parser("unpause", help="clear a global pause after inspecting its cause")
    args = parser.parse_args()
    return {"init": cmd_init, "status": cmd_status, "activity": cmd_activity, "run": cmd_run, "requeue": cmd_requeue, "unpause": cmd_unpause}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
