# Blocked: EMDB Cryo-EM Density Maps Float32

- Date: 2026-08-25
- Candidate: `emdb_cryoem_density_maps_f32`
- Intended domain: reconstructed cryo-electron-microscopy molecular density
  volumes
- Intended representation: native MRC/CCP4 mode-2 float32 voxels
- Decision: blocked for training because the current reuse grant is unclear

## Technical result

The bounded preflight was technically successful. It fetched official entry
XML, HTTP metadata, and only the first 131,072 compressed bytes of each map,
then decoded and validated the 1,024-byte MRC headers.

Ten entries exposed native little-endian MRC mode-2 float32 volumes:

| Entry | Shape | Decoded voxel bytes | Compressed bytes |
|---|---:|---:|---:|
| `EMD-1080` | 100 x 100 x 100 | 4,000,000 | 633,614 |
| `EMD-3061` | 180 x 180 x 180 | 23,328,000 | 21,796,317 |
| `EMD-8117` | 192 x 192 x 192 | 28,311,552 | 26,080,678 |
| `EMD-30210` | 192 x 192 x 192 | 28,311,552 | 18,950,940 |
| `EMD-10028` | 197 x 209 x 247 | 40,678,924 | 15,077,086 |
| `EMD-5778` | 256 x 256 x 256 | 67,108,864 | 48,375,630 |
| `EMD-6287` | 300 x 300 x 300 | 108,000,000 | 18,295,761 |
| `EMD-2660` | 360 x 360 x 360 | 186,624,000 | 174,797,019 |
| `EMD-11657` | 360 x 360 x 360 | 186,624,000 | 175,305,733 |
| `EMD-21452` | 400 x 400 x 400 | 256,000,000 | 241,254,665 |

Two additional native-float32 maps were excluded by the bounded-output rules:
`EMD-24827` decodes to 322,486,272 bytes, above the per-map selection target,
and `EMD-36531` decodes to 2,048,000,000 bytes, above the repository's complete
primary-output ceiling by itself.

A nine-map selection could have supplied 672,986,892 primary float32 bytes,
with one complete reconstructed density volume per natural sample. The format,
shape, volume, decoder complexity, and domain diversity are all suitable.

## Rights investigation

The investigation checked:

- `https://www.ebi.ac.uk/emdb/documentation/policies`
- `https://www.ebi.ac.uk/licencing`
- `https://www.ebi.ac.uk/about/terms-of-use/`
- the selected entries' official EMDB XML headers

The EMDB-specific policy page and entry headers supplied no CC0, CC BY, public
domain, or equivalent reuse grant.

The EMBL-EBI licensing page contains strong CC0 language, but it describes a
plan to adopt Creative Commons licensing across resources “in the next 5
years.” It says CC0 is preferred and explains why CC0 enables academic and
commercial reuse; it does not state that EMDB or these records are currently
licensed CC0.

The binding EMBL-EBI terms are explicitly cautious:

- community contributors remain the original data owners;
- EMBL-EBI places no *additional* restrictions beyond those owners' terms;
- original data may remain subject to patent, copyright, or other third-party
  rights; and
- users are responsible for ensuring that their exploitation does not infringe
  those rights.

Open access and unrestricted retrieval therefore do not establish permission
to use these deposited maps as model-training material. The future CC0 roadmap
cannot be treated as a present license.

## Decision and retry condition

Do not download or promote these EMDB maps for training under the current
evidence. Retry only if one of the following becomes available:

1. EMDB publishes an explicit current resource-wide CC0, CC BY, public-domain,
   or equivalently permissive license covering deposited map data; or
2. the selected EMDB records expose explicit record-level licenses with those
   terms.

Do not repeat this attempt based only on public availability, open-access
deposit, EMBL-EBI's no-additional-restrictions statement, or its aspirational
CC0 licensing roadmap.

No complete map payload was downloaded. Evidence remains in the ephemeral
preflight outputs under `.data/discovery/emdb_cryoem_density_maps_f32/` and
`.data/logs/emdb_cryoem_density_maps_f32/`.
