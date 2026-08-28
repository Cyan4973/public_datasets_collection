# Blocked: DeepMind AlphaMissense Substitution Scores Float32

- Date: 2026-08-27
- Candidate: `deepmind_alphamissense_substitution_scores_f32`
- Intended domain: AI-derived human protein missense-variant pathogenicity
  predictions
- Intended representation: one little-endian float32 pathogenicity-score grid
  per protein, ordered by residue and non-reference amino-acid substitution
- Decision: blocked for training because the exact payload contradicts the
  repository-level license statement

## Expected value

This would be a genuinely new numerical structure for the float32 corpus.  A
natural sample is a narrow, variable-length `residue x 19 substitutions` score
grid.  Unlike the accepted AlphaFold PAE matrices, these values are predicted
variant effects rather than pairwise geometric uncertainty, and the grid is
linear in protein length rather than square.

The official canonical object is
`AlphaMissense_aa_substitutions.tsv.gz` in the public
`dm_alphamissense` Google Cloud Storage bucket.  Discovery pinned repository
revision `fe2dc845f93310abd6c1b0e8955d7a96c2144d66` and object metadata:

- compressed size: 1,207,278,510 bytes;
- MD5: `b9ccb339e0de6cb0a8d1973ad2026576`;
- GCS generation: `1695124973016673`.

## Bounded technical result

The user fetched only bytes 0 through 8,388,607.  The source is BGZF, so the
probe was corrected to walk concatenated gzip members rather than stopping
after the first 65,280-byte member.

The 8 MiB prefix contained 1,444,880 valid score rows across 408 observed
protein identifiers.  Excluding the range-truncated first and last groups:

- 378 of 406 protein groups formed complete residue-by-19 grids;
- 28 groups contained at least one position with two different reference
  residues and must be excluded rather than silently forced into a rectangle;
- complete samples ranged from 133 to 73,017 values, with median 2,223; and
- the full table projects to approximately 207,945,477 scores, or 831,781,908
  bytes when converted to little-endian float32.

The domain, geometry, sample sizes, and projected primary volume are therefore
technically suitable after rejecting anomalous protein groups.

## License conflict

The pinned AlphaMissense repository README explicitly says:

> AlphaMissense predictions are licensed under the Creative Commons
> Attribution 4.0 International License (CC BY 4.0).

However, the exact canonical prediction payload begins with:

> Licensed under CC BY-NC-SA 4.0 license

The object-level notice imposes noncommercial and share-alike restrictions
that are materially different from CC BY 4.0.  Public availability and the
newer repository statement are not enough to assume that the more permissive
terms silently supersede the license embedded in this exact object.

## Decision and retry condition

Do not acquire the complete table or promote it as training material under the
current evidence.  Retry only if DeepMind publishes an unambiguous statement
that explicitly identifies this GCS object or generation and clarifies that CC
BY 4.0 supersedes its embedded CC BY-NC-SA 4.0 notice, or replaces the object
with one carrying consistent permissive terms.

The source might be considered separately for a noncommercial evaluation-only
corpus, but that would require an explicit policy decision about CC BY-NC-SA
and its attribution/share-alike obligations; this attempt does not authorize
that use.

No complete prediction table was downloaded.  Bounded evidence remains under
`.data/discovery/deepmind_alphamissense_substitution_scores_f32/`,
`.data/probes/deepmind_alphamissense_substitution_scores_f32/`, and
`.data/logs/deepmind_alphamissense_substitution_scores_f32/`.
