# Acquisition Attempts

This directory records dataset acquisition attempts that did not produce an
accepted recipe.

`dataset_status.tsv` is the machine-readable status registry for attempt IDs
that are easy to confuse with active candidates. Check it before treating any
historical report, runbook, or attempt file as a current recommendation.

Use one markdown file per non-accepted attempt, named:

- `YYYYMMDD_<status>_<dataset_id>.md`

Registry status values:
- `accepted`
- `rejected`
- `blocked`
- `deferred`
- `transient_failure`
- `needs_tooling`
- `superseded`

Attempt filenames normally use only non-accepted statuses. `accepted` and
`superseded` are registry statuses used to connect old IDs to active successor
recipes.

Record an attempt here when any of the following happens:
- the source is no longer reachable
- the source license or terms are not permissive enough
- the download or output size is not acceptable for this repository
- the upstream structure makes the recipe non-reproducible
- the source content turns out to be outside the repository scope
- the implementation cost is disproportionate to the likely value

Each attempt record should include:
- candidate dataset id and title
- date attempted
- status
- source URLs
- expected value of the dataset
- concrete reason the attempt failed or was rejected
- evidence, including relevant log paths
- whether the failure is permanent, likely transient, or worth retrying later
- what would need to change before retrying

The goal is to preserve negative results so future sessions do not repeat the
same dead ends blindly.

For `rejected`, `blocked`, `deferred`, `transient_failure`, `needs_tooling`, or
`superseded` rows in `dataset_status.tsv`, the dataset ID must not appear as an
active recipe under `datasets/`. If a retry succeeds, update the registry row to
`accepted` and set `active_path`, or add a new accepted successor and mark the
old ID `superseded`.

For `needs_tooling` attempts, also maintain a grouped roadmap in
`needs_tooling_roadmap.md` so related decoder or importer gaps are tracked as
shared tooling work instead of isolated one-off failures.
