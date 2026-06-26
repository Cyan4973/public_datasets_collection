# Pfam Seed Alignments

This staged recipe collects the official Pfam-A seed Stockholm alignment file and emits one `uint8` sample per qualifying protein-family seed alignment.

The natural record is one Stockholm family block. The build writes only aligned residue/gap symbols, row-major, and does not concatenate families to pass the median-sample floor.

Default knobs:

```sh
PFAM_MIN_SAMPLE_BYTES=1000
PFAM_MAX_FAMILIES=0
PFAM_MAX_PRIMARY_BYTES=950000000
```

`PFAM_MAX_FAMILIES=0` means no explicit family-count cap; the byte cap still applies.

Usage after the user-run external download:

```sh
bash staging/pfam_seed_alignments_u8/download.sh
bash staging/pfam_seed_alignments_u8/build.sh
bash staging/pfam_seed_alignments_u8/verify.sh
```

Do not promote to `datasets/` until the current `download.sh`, `build.sh`, and `verify.sh` have succeeded locally.
