# Pfam profile-HMM match emissions float32

This recipe collects the position-specific match-emission score matrices in
the official Pfam-A HMMER profile archive. Each protein family produces
one variable-length row-major matrix with 20 homogeneous float32 values per
profile position, in HMMER amino-acid column order.

This is numerically distinct from the accepted `pfam_seed_alignments_u8`
family. That recipe stores observed residue and gap symbols from seed multiple
sequence alignments. This recipe stores the fitted numerical parameters of
the profile hidden Markov model derived for each family.

Only match-emission rows are primary material. Insert emissions,
transition parameters, node indices, annotations, and other fields must not be
interleaved with them. Decimal source tokens are converted once to canonical
little-endian IEEE float32. HMMER `*` sentinels are never assigned an arbitrary
finite value.

Metadata discovery identified Pfam release 38.2, containing 30,134 families.
The official `Pfam-A.hmm.gz` object is 418,160,514 compressed bytes and has the
published MD5 `7ab3c4e215d0daaea3004e37c4e24f8a`. The release notes explicitly
place the Pfam alignments and HMMs under CC0 1.0.

Run from the repository root:

```bash
bash datasets/pfam_profile_hmm_match_emissions_f32/download.sh
bash datasets/pfam_profile_hmm_match_emissions_f32/build.sh
bash datasets/pfam_profile_hmm_match_emissions_f32/verify.sh
```

The downloader uses the immutable Pfam 38.2 release path and validates the
exact published size and MD5. The local build streams the gzip without
extracting it and validates every HMMER record.

Downloads are written below
`.data/downloads/pfam_profile_hmm_match_emissions_f32/` and logs are below
`.data/logs/pfam_profile_hmm_match_emissions_f32/`.

The accepted build retains 27,496 profiles of at least 50 model positions. It
emits 93,130,540 float32 values in 372,522,160 bytes, with a median natural
sample size of 2,580 values. All match-emission tokens are finite. The 90,402
observed `*` sentinels occur only in transition fields, which are validated but
not emitted. The aggregate decoded-byte SHA-256 is
`4081830cbdcccc1ffda780605a7a32c2fc5c2907552c68bd1e5d591aa8d70a4f`.
