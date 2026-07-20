# NCBI RefSeq Viral Genome FASTA Bytes (uint8)

This recipe extracts viral genomic FASTA records from the NCBI RefSeq release
archive and emits one raw uint8 sample per source FASTA record.

The emitted bytes are source sequence-letter bytes with FASTA headers and line
wrapping removed. The build does not remap, pack, pad, or concatenate records.

The download and verifier require at least 1,000 FASTA records and 10,000,000
sequence bytes by default, and the download script rejects archives above the
repository's 1 GB per-dataset cap.
