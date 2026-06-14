# NCBI RefSeq Viral Genome FASTA Bytes (uint8)

This staging recipe extracts viral genomic FASTA records from the NCBI RefSeq
release archive and emits one raw uint8 sample per source FASTA record.

The emitted bytes are source sequence-letter bytes with FASTA headers and line
wrapping removed. The build does not remap, pack, pad, or concatenate records.
