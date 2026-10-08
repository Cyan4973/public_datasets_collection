# Bosch CNC milling CISS vibration int16 development

## Outcome

Accepted `bosch_cnc_milling_ciss_vibration_i16`. Each sample is the complete
tri-axial accelerometer recording of one machining-operation run on a
brownfield CNC milling machine, taken from the Bosch CNC_Machining dataset
(Tnani, Feil, Diepold, Procedia CIRP 107, 2022). The recipe takes every
published run of machines M01 and M02.

The family adds industrial machine-tool vibration to the 16-bit inertial/vibration
modality. That modality already holds `zenodo_accelerometer_pcm16` (honeybee hive),
and at other widths `luh_lumo_tower_acceleration_f32` and
`monado_msd_valve_index_imu_f64`. It is new content and a new source within an
existing modality, not a new modality. Measured breadth (zlsim) is OK: the
nearest family is downstream `v16_nb_iot_iq_ci16` at distance 0.0605.

## Source and rights

- Source: <https://github.com/boschresearch/CNC_Machining> at commit
  `d60581d6a3ab6015dcc5488c3d76112bb8e1bcb1`. This is still `main` per
  `git ls-remote`, and the repository has been archived read-only since Feb 2026.
- Pinned selection: 1,163 HDF5 files, 642,164,273 bytes. Each file is pinned by
  size and git blob SHA-1 in `sources.tsv` and fetched anonymously from
  raw.githubusercontent.com.
- License: CC BY 4.0 for the `data/` directory. The pinned README (blob
  `76e64e205cf889ae10a2ffdbb9c29e4205cb1738`) says: "The dataset created for the
  research located in the directory [data](data) are licensed under a Creative
  Commons Attribution 4.0 International License (CC-BY-4.0)." The BSD-3-Clause
  LICENSE covers only the loader code, which is not used. `download.sh`
  re-fetches the README by blob SHA-1 and grep-checks this statement.
- Safety: the data is machine vibration only, with no personal data.

## Shape and conversion

- Natural record: one HDF5 file holds one execution of one operation
  (OP00–OP14) on one machine. Its `vibration_data` dataset has shape
  `(n, 3)`, with columns X, Y and Z at 2 kHz.
- Emission: each record becomes one little-endian int16 sample, row-major and
  interleaved X,Y,Z. There is no concatenation, sharding, or helper series.
- Container dtypes: the publisher stored the same integer readings as int64
  (566 files), float64 (470) or float32 (127), chosen per file.
- Width policy: a file is kept only if every value is finite, exactly
  integral, and within int16. Values are never rounded, clipped or rescaled.
  Result: 0 files dropped and 0 negative zeros.
- Value lattice: the values are milli-g on a step-≈1.953 lattice with doubled
  integer points about every 41 values, which fits a 14-bit ±16 g sensor
  converted to mg. The lattice is identical in all three container dtypes, so
  int16 is the honest native width and the dtype differences are export
  artifacts.
- Decoder: pure stdlib. It handles superblock v0, a symbol-table root group
  with exactly one link, v1 object headers, layout v3 chunked storage, v1 chunk
  B-trees, and deflate/shuffle with filter masks. It rejects everything else.
  Every file in this selection uses `(k,1)` column chunks with deflate only.
  A 15-case synthetic self-test runs at the start of every build.
- Subset: machine M03 (539 runs, 336,474,750 int16 bytes) is excluded because
  the full set would be 1,071,607,440 bytes, over the 1 GB cap. The selection
  keeps whole machines and splits no timeframe, operation or label.

## Accepted output

- Primary samples: 1,163 (M01 519, M02 644)
- Primary values: 367,566,345
- Primary bytes: 735,132,690
- Sample size: minimum 80,379, median 264,192, maximum 952,320 values
- Labels: good 1,102, bad 61 (61 of the 70 bad runs upstream)
- Operations: all 15, with 53–102 runs each
- Timeframes: Feb 2019 124, Aug 2019 471, Feb 2020 143, Aug 2020 62
  (M02 only), Feb 2021 287, Aug 2021 76
- Value range: −6,668..6,074
- Dropped files: 0
- Aggregate SHA-256:
  `539cccdadbcc24eb4432ffa16096c842c0ae2ad80f468aa4a85efed80ce959d2`

## Judge checks

- **Gate:** `tools/autocollect/gate.py` passed with no warnings.
- **Verify:** I ran `verify.sh` myself and it passed. Totals and the aggregate
  SHA-256 match the manifest and `ingest_stats.json`.
- **Local-only build:** `build.sh` and its Python scripts make no network
  calls and contain no credentials. The self-test log shows 15/15 cases.
- **Scope:** I fetched the pinned commit's tree via the GitHub API (judge-side
  metadata only). It lists 1,702 `.h5` files (M01 519, M02 644, M03 539;
  952,229,265 B). `sources.tsv` equals exactly the M01+M02 subset, with
  identical size and blob SHA-1 pins.
- **Bytes (12 samples, every machine × dtype group):**
  - Z mean is −1014 to −1050 and X/Y means are near 0.
  - X has lag-1 autocorrelation 0.74–0.95, which is plausible vibration.
  - The mg lattice is identical across dtypes.
- **Decode correctness:** verify reuses the recipe's own HDF5 decoder, so I
  tested decoding on the bytes. Across 200 random samples:
  - all 20,880 chunk-length segments carry the correct axis signature
  - the mean |diff| at chunk boundaries vs interior has median ratio 0.99

  Together these rule out misplaced chunks or swapped columns.
- **Duplicates:** there are no head or mid-file fingerprint collisions among
  the 1,163 samples. The 52 good/bad basename repeats are distinct recordings.
  There are 260 distinct run lengths, no constant axes, and fill mode_share is
  0.0134.
- **Rights:** I read the license statement in the downloaded pinned README and
  on the live repository page.
- **Novelty:** `novelty.py` (URL and terms, vocabulary, type) found no prior
  recipe, registry or downstream hit for this source, CNC or milling.
- **Scratch-dir incident:** while confirming scope, a blobless `git clone`
  plus `git ls-tree -l` in my `/tmp` scratch began lazily fetching public
  blobs (about 259 MB of this CC BY data). I stopped it and deleted the
  scratch clone. The repository and `.data/` were not touched.
- **Open caveats (not blocking):**
  - The unit (mg) and the sensor range are inferred from the gravity offset
    and the lattice; they are not documented upstream.
  - Integrity rests on the pinned commit and blob SHA-1s, since there is no
    DOI deposit.
  - Labels are imbalanced: 61 bad vs 1,102 good.
