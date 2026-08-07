# Blocked: Zenodo Illumina cycle-intensity int16 — 2026-08-07

## Intended family

`zenodo_illumina_cif_i16` targeted binary Illumina cycle-intensity `.cif`
files with native two-byte storage. These files would provide signed-int16
four-dye fluorescence arrays over sequencing cycles and spatial clusters, a
numeric process distinct from Sanger chromatograms and called-base files.

## License and safety gates

Discovery admitted only CC0/CC BY records with explicit non-human, microbial,
plant, viral, synthetic, or spike-in context. Records containing human,
patient, clinical, cancer, biopsy, or ambiguous-organism context were rejected
before file probing.

## Bounded discovery

Seven targeted Zenodo queries returned 223 unique records. After exact
word-boundary semantic filtering, 23 records were both permissively licensed
and explicitly non-human. Their exposed payloads were primarily FASTQ/FASTA,
scripts, processed tables, figures, or generic tar archives. Four qualifying
ZIP archives were inspected by remote central-directory reads.

The probe fetched only metadata, ZIP directories, and 13-byte candidate
headers. A binary file would have qualified only if it declared:

- ASCII magic `CIF`;
- format version 1;
- two-byte native storage;
- positive cycle and cluster counts; and
- exact size `13 + cycles × clusters × 4 channels × 2 bytes`.

## Outcome

No direct or ZIP-contained binary Illumina CIF file was exposed by the bounded
licensed/non-human search. No sequencing intensity payload was downloaded.

An earlier exploratory run also encountered `.cif` crystallographic text
files; their missing binary `CIF` magic correctly rejected them. A short-term
classifier bug that matched `rat` inside unrelated words was fixed by exact
word-boundary matching before the final counts above were produced.

## Retry condition

Retry only with an exact CC0/CC BY non-human Illumina run-folder archive known
in advance to contain binary files under an `Intensities` hierarchy. Generic
FASTQ deposits and unverified tar archives are not sufficient evidence.
