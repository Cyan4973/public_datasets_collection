# UniProt Protein Sizes (per organism)

UniProtKB reviewed (Swiss-Prot) protein sizes, organized as **one family per quantity**
with **one sample per organism** — "many station-series of the same physical quantity"
(like USGS sites / NIH years). Supersedes the tiny `uniprot_reviewed_human` /
`uniprot_human_reviewed_lengths` recipes.

- Source: https://rest.uniprot.org/uniprotkb/stream (CC BY 4.0)
- Local raw payload: `${DATA_DIR:-.data}/downloads/uniprot_protein_sizes/uniprot_protein_sizes.tsv.gz`

## Families & samples

| family | quantity | type |
|---|---|---|
| `uniprot_length_u16` | sequence length (amino acids) | uint16 |
| `uniprot_mass_u32` | molecular mass (Da) | uint32 |

- **A sample** = one organism's protein lengths (or masses), for organisms with
  **≥1000 reviewed proteins** (e.g. human, mouse, rat, yeast, *E. coli*, *Arabidopsis*…).
- **Samples/family** = number of such organisms (dozens). Each family is one physical
  quantity across organisms; length and mass are never mixed.
- One streamed request fetches the whole reviewed set (~570k entries, gzipped TSV);
  no pagination crawl. De-duplicated by accession.

## Run

```sh
bash datasets/uniprot_protein_sizes/download.sh
bash datasets/uniprot_protein_sizes/build.sh
bash datasets/uniprot_protein_sizes/verify.sh
```

Tuning env vars: `UNIPROT_QUERY` (default `reviewed:true`), `UNIPROT_MIN_PROTEINS` (default 1000). Logs under `${DATA_DIR:-.data}/logs/uniprot_protein_sizes/`.
