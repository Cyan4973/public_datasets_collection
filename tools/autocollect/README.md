# Autocollect

Autonomous collection loop for new numeric families. It runs until each
target width (8, 16, 32, 64 bits) has gained the target number of new
accepted recipes since the baseline (50 by default), or until a stop
condition.

```text
scout ──► screener ──► builder (author) ──► driver: download.sh
 (web)    (cheap        writes               (byte cap, disk budget,
           reject)      staging/<id>/         time limit)
                                                   │
                         builder (build) ◄─────────┘
                           build/verify/gate, iterate
                                   │
                         driver: re-run build.sh, verify.sh, gate.py
                                   │
                         judge (fresh, adversarial)
                           accept ─► driver promotes, records, commits
                           repair ─► builder (repair), at most 2 cycles
                           reject/blocked/... ─► attempts/ record, commit
```

## Roles

Each role is a headless `claude -p --agent <name>` session defined in
`.claude/agents/`:

| Role | Agent | Writes | Output |
|---|---|---|---|
| Scout | `autocollect-scout` | nothing | verified candidate cards for one width |
| Screener | `autocollect-screener` | nothing | approve (with priority and builder notes) or reject |
| Builder | `autocollect-builder` | `staging/<id>/` only | `ready_for_download`, `ready_for_judge`, or `abandon` with an attempt record |
| Judge | `autocollect-judge` | nothing | accept, repair, or a registry status, plus the report |

`tools/autocollect/driver.py` schedules the roles and makes every repository
change outside `staging/<id>/`: ledger, cards, registry rows, attempt
records, development reports, promotion to `datasets/`, audit regeneration,
and one local commit per decision. It never pushes.

Shared criteria live in `collection_protocol.md` and
`tools/autocollect/criteria.md`. To change what gets accepted, edit those,
not the driver. The mechanical part is `gate.py`.

## Running

```bash
python3 tools/autocollect/driver.py init              # once: snapshot baseline
python3 tools/autocollect/driver.py run --stop-after 2 --max-cost-usd 150   # pilot
tmux new -s autocollect 'python3 tools/autocollect/driver.py run'           # full run
python3 tools/autocollect/driver.py status            # anytime, from another shell
python3 tools/autocollect/driver.py activity          # latest steps of each recent agent session
```

Agents are separate headless `claude -p` processes, so they do not show up in
an interactive Claude Code session; `activity` reads their streamed
transcripts under `.data/pipeline/logs/`.

`run` refuses to start while `attempts/dataset_status.tsv` or the audit
files have uncommitted changes, while `tools/check_repo_hygiene.py` fails, or
while a global pause is set. Ctrl-C stops launching new work and lets
in-flight work finish; a second Ctrl-C kills it. Restarting resumes from the
ledger; builder sessions resume with their context.

Useful flags: `--agents` (concurrent agent sessions, default 3),
`--downloads` (concurrent downloads/rebuilds, default 2), `--widths 8,16`,
`--max-cost-usd`, `--stop-after`, `--model`, `--effort`, `--download-cap-gb`
(default 5), `--disk-budget-gb` (default 500), `--keep-rejected-data`.

## Guardrails

- Downloads run only through the driver, in their own process group. They are
  killed when every `.data/*/<id>` directory together exceeds the byte cap,
  or at the time limit. A download starts only if free disk stays above a
  200 GB reserve and the pipeline's total footprint stays within the budget.
- Before any judging, the driver re-runs the current `build.sh` and
  `verify.sh` and `gate.py` itself. If `download.sh` changed since its last
  successful run, the driver runs it again first. The judge also runs
  `verify.sh` independently, and `verify.sh` runs once more after the move to
  `datasets/`.
- Permissions: read-only roles have Edit/Write denied. The builder has
  Edit/Write denied on every tracked area except `staging/`. All roles are
  denied state-changing git commands and subagents. Bash can still write
  anywhere, so after every result the driver checks `git status`. Any
  unexpected change outside `pipeline/` sets a global pause.
- Every agent run has a dollar budget and a timeout; repeated agent failures
  pause that candidate (`driver.py requeue <id>` after a look).
- Network: the driver exports the `~/.curlrc` proxy to every child process so
  both curl and Python reach the internet. Recipes still use curl for network
  so they also run standalone.
- Commits pass `tools/check_repo_hygiene.py` and `git diff --cached --check`
  and include only the decision's paths plus `pipeline/`.

## State

| Path | Committed | Content |
|---|---|---|
| `pipeline/baseline.json` | yes | accepted recipe ids at `init`, target per width |
| `pipeline/candidates.tsv` | yes | every candidate with its resting status and last reason |
| `pipeline/cards/<id>.md` | yes | scout card: source, license evidence, estimates, novelty |
| `.data/pipeline/state/<id>.json` | no | sessions, counters, event history |
| `.data/pipeline/logs/<subject>/` | no | agent transcripts, download/build/verify logs |
| `.data/pipeline/costs.tsv` | no | spend per agent run |
| `.data/pipeline/archive/` | no | staging drafts of non-accepted candidates |

Candidate statuses: `proposed` → `queued` (or `screened_out`) →
`ready_for_download` → `downloaded` → `built` → `ready_for_judge` →
`accepted`, or one of the registry statuses (`rejected`, `blocked`,
`deferred`, `transient_failure`, `needs_tooling`). `needs_repair` sends a
recipe back to the builder; `paused` waits for a human.

Progress counts accepted recipes absent from the baseline, by the bit widths
of their primary series. A recipe with primary series at two widths counts
for both.

## Reviewing what it did

- `git log` has one commit per accepted dataset ("Add …") and per terminal
  outcome ("Record rejected …"); the judge's report is in `reports/` or
  `attempts/`.
- `pipeline/candidates.tsv` shows screened-out candidates with reasons.
- Spot-check acceptances. If the judge drifts, tighten
  `tools/autocollect/criteria.md` or the judge definition. A bad acceptance
  is reverted like any commit, plus a registry row.
