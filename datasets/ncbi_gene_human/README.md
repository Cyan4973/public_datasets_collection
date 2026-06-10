Dataset ID: `ncbi_gene_human`

Scope:
- NCBI Gene `gene_info` and `gene2pubmed`
- deterministic subset: human only (`tax_id = 9606`)

Why this subset:
- the full `gene_info.gz` source is over the repository size cap
- a taxon-bounded subset is coherent, reproducible, and preserves real upstream numeric content

Outputs:
- `ncbi_gene_info_gene_id_u32`
- `ncbi_gene_info_modification_date_u32`
- `ncbi_gene2pubmed_gene_id_u32`
- `ncbi_gene2pubmed_pubmed_id_u32`

Download behavior:
- streams the upstream gzip payloads
- filters rows at download time to `tax_id = 9606`
- stores only the filtered subset under `.data/downloads/ncbi_gene_human/`
