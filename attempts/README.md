# Acquisition Attempts

This directory records dataset acquisition attempts that did not produce an
accepted recipe.

Use one markdown file per attempt, named:

- `YYYYMMDD_<dataset_id>.md`

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
- source URLs
- expected value of the dataset
- concrete reason the attempt failed or was rejected
- evidence, including relevant log paths
- whether the failure is permanent, likely transient, or worth retrying later
- what would need to change before retrying

The goal is to preserve negative results so future sessions do not repeat the
same dead ends blindly.
