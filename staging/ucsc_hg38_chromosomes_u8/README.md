# UCSC hg38 Chromosome FASTA Bytes (uint8)

This staging recipe extracts the primary hg38 chromosome sequences from the UCSC
FASTA download and emits one raw uint8 sample per natural chromosome record.

The emitted bytes are the source FASTA sequence letters with headers and line
wrapping removed. No nucleotide remapping or packing is performed.
