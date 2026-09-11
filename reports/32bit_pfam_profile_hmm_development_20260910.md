# Pfam profile-HMM match-emission float32 development

## Outcome

Accepted `pfam_profile_hmm_match_emissions_f32` from the immutable official
Pfam 38.2 release.

This family is distinct from the accepted `pfam_seed_alignments_u8` recipe.
The earlier recipe preserves observed aligned residue and gap symbols. This
recipe preserves the fitted numerical match-emission parameters of each
protein-family profile hidden Markov model.

## Source and rights

- Source: official EMBL-EBI Pfam 38.2 `Pfam-A.hmm.gz`
- Compressed bytes: 418,160,514
- Published MD5: `7ab3c4e215d0daaea3004e37c4e24f8a`
- SHA-256: `2d82087b6c5c60d762cc767f98e8260b273134c215ab7efccf7440614a4e5dab`
- License: CC0 1.0

The pinned release notes explicitly apply CC0 1.0 to the Pfam database of
protein-domain family alignments and HMMs and state that it may be copied,
modified, distributed, and performed commercially without permission.

## Shape and conversion

Each natural record is one complete Pfam family profile. A retained sample is
the variable-length `profile_position × 20 amino acids` match-emission matrix,
flattened row-major. Decimal HMMER scores are rounded once to IEEE-754 float32
and written explicitly little-endian.

COMPO rows, insert emissions, transitions, annotations, and node indices are
not mixed into the primary stream. All match-emission tokens are finite. The
90,402 observed `*` sentinels occur only in excluded transition fields.

Profiles shorter than 50 positions are excluded because their natural records
contain fewer than 1,000 values.

## Accepted output

- Source profiles validated: 30,134
- Profiles excluded below 50 positions: 2,638
- Primary samples: 27,496
- Primary values: 93,130,540
- Primary bytes: 372,522,160
- Minimum sample: 1,000 values
- Median sample: 2,580 values
- Maximum sample: 47,440 values
- Aggregate decoded SHA-256:
  `4081830cbdcccc1ffda780605a7a32c2fc5c2907552c68bd1e5d591aa8d70a4f`

The local build and independent byte-for-byte verification both completed
successfully against the pinned archive.
