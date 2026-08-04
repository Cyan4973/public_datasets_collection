# Blocked: Zenodo Roche/454 SFF Flowgrams UInt16

- Date: 2026-08-04
- Candidate: `zenodo_454_sff_flowgrams_u16`
- Intended domain: Roche/454 pyrosequencing light-intensity flowgrams
- Intended representation: native big-endian uint16 flow values from Standard
  Flowgram Format
- Intended natural sample: one complete SFF run as a `[read, flow]` matrix

## Discovery performed

Zenodo metadata discovery queried for Roche/454 sequencing, pyrosequencing,
Standard Flowgram Format, `.sff` flowgrams, and raw 454 data. It examined 76
unique records and required explicit CC0 or CC BY licensing plus clear
454/pyrosequencing/flowgram semantics.

The search encountered 45 direct files named `.sff` and 50 possible archives,
but 89 relevant files were rejected for non-permissive or absent licensing and
two for missing sequencing semantics. No bounded licensed direct SFF file
remained for binary-header probing.

One bounded archive qualified at the metadata level:

- Zenodo record `4944592`, *C. elegans RNA Sequence for viral discovery*;
- license: CC BY 4.0;
- file: `Celegans-Nodavirus.zip`;
- source bytes: `2,170,743`;
- MD5: `00efece3c78f95e65abac461b3250c2b`.

## Archive result

The exact archive was downloaded and checksum-validated. It expands to two
members totaling 11,044,636 bytes:

- `S1977_TNA_C_Elegans_RNA_1_3012.fa`
- `S1978_TNA_C_Elegans_RNA_2_3013.fa`

Both are assembled FASTA sequence files. Neither has the Roche/454 `.sff`
magic, and the archive contains no flowgram payload, read headers, or native
uint16 measurement arrays. No samples were built.

This attempt is blocked rather than permanently rejected because a different
explicitly licensed repository could expose original SFF runs. A valid retry
requires an exact permissively licensed source or archive known in advance to
contain true Roche/454 `.sff` version-1 payloads. Re-running the same Zenodo
queries or retrying `Celegans-Nodavirus.zip` is not useful.

Ephemeral evidence:

- `.data/logs/zenodo_454_sff_flowgrams_u16/discover.latest.log`
- `.data/logs/zenodo_454_sff_flowgrams_u16/download_probe.latest.log`
- `.data/logs/zenodo_454_sff_flowgrams_u16/inspect_probe.latest.log`
- `.data/discovery/zenodo_454_sff_flowgrams_u16/summary.json`
- `.data/discovery/zenodo_454_sff_flowgrams_u16/archive_candidates.tsv`
- `.data/discovery/zenodo_454_sff_flowgrams_u16/archive_member_inventory.tsv`
- `.data/discovery/zenodo_454_sff_flowgrams_u16/archive_probe_summary.json`
