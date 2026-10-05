# Autocollect Ledger

Committed state of the autocollect pipeline (`tools/autocollect/`):

- `baseline.json`: accepted recipes when collection began and the target of
  new families per width
- `candidates.tsv`: every candidate the scouts proposed, with its current
  status and last reason
- `cards/<id>.md`: the scout's evidence for each candidate

This is a work ledger, not the corpus. Accepted recipes are only those under
`datasets/`; outcomes of attempted candidates are in
`attempts/dataset_status.tsv`. Only the driver writes here.
