# cds_codon_start_u8

- Date: 2026-06-01
- Status: rejected
- Candidate dataset: RefSeq codon-start labels
- Source: https://www.ncbi.nlm.nih.gov/refseq/
- Why it looked promising: The upstream genomic source is public, but the emitted values are derived positional labels.
- Failure class: policy_mismatch
- What happened: The output stream is an annotation transform over nucleotide sequences, not a native numeric measurement stream.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest where present.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Reject for this repository.
- Retry conditions: Retry only if derived annotation labels become in-scope.
