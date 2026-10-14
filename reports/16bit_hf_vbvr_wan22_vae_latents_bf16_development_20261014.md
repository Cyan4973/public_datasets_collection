# VBVR Wan2.2-TI2V-5B video VAE latent bfloat16 development

## Outcome

Accepted `hf_vbvr_wan22_vae_latents_bf16` from a pinned, published Apache-2.0 precomputed latent cache. Each sample is the complete Wan2.2-TI2V-5B VAE latent of one synthetic VBVR reasoning clip. The tensor is stored natively as bfloat16 by the publisher and emitted verbatim.

This is the corpus's first family of learned latent activations. The existing 16-bit ML families, local and downstream, are model weight tensors. The closest relative at any width is the 8-bit AlphaEarth embedding rasters, which are a different model, quantity and encoding. Byte-level breadth is STRONG: own_ratio 3.3712, nearest family `noaa_isd_lite:isd_slp` at feature distance 0.1314 with 10.6% compression loss, and every top-10 neighbour has loss of at least 9.7%.

One judge repair round corrected the scope text (36 G-series generators, not 100) and pinned the Diffusers-format encoder card that the cache names. The output bytes were unchanged.

## Source and rights

- Latent cache: `Central-Cat/vbvr-latent-cache-832x832x33f-t2v-only` at revision `951c2880a946f0a947bc32c9f48df30767102175`. The card (9,841 bytes, SHA-256 `0faf4631…264c`) declares `license: apache-2.0` and says it "Inherits the upstream VBVR-Dataset license (Apache-2.0)". The repository is public and not gated.
- Source videos: `Video-Reason/VBVR-Dataset` at `7ef37ad3706c1a146143f9ab7611730487bd8c70`. The card (9,344 bytes, `36d9c18a…aec2`) declares `license: apache-2.0`, and its License section repeats it. The videos are programmatically generated reasoning scenes with no people.
- Encoder actually used, as named in the cache card's model table: `Wan-AI/Wan2.2-TI2V-5B-Diffusers` at `b8fff7315c768468a5333511427288870b2e9635`. The card (17,633 bytes, `b7120bb2…c2c0c`) declares `license: apache-2.0` and states "We claim no rights over the your generated contents".
- Original-format encoder repository, kept as secondary evidence: `Wan-AI/Wan2.2-TI2V-5B` at `921dbaf3f1674a56f47e83fb80a34bac8a8f203e`. The card (15,935 bytes, `e357cb3a…bf69`) declares `license: apache-2.0`.
- The UMT5 text embeddings and the prompts in each cache file are discarded, so their terms do not matter. The chain is permissive end to end.
- `download.sh` pins all four cards by size and SHA-256, and the decoder refuses to run unless each card's frontmatter still says `apache-2.0`.
- There are no credentials in any script and no personal data.

## Shape and conversion

Each natural record is one cache file holding the latent of one clip. The card documents the upstream pipeline:
- uniform 33-frame subsample of the 1024x1024 16 fps MP4;
- scale to [-1, 1], then bilinear resize to 832x832;
- Wan2.2 VAE encode, taking `posterior.mode()` (no sampling, no augmentation);
- per-channel normalization with the VAE config's `latents_mean`/`latents_std`;
- cast to bf16.

The result is `x0` with shape (48, 9, 52, 52) in C,T,H,W order: 48 learned channels, 9 latent frames (4x temporal compression after the first frame) and a 52x52 grid (16x spatial). That is 1,168,128 values (2,336,256 bytes) per sample.

The recipe decodes each `torch.save` zip with a restricted unpickler. Only `_rebuild_tensor_v2`, `OrderedDict` and the torch storage classes are resolved, so no code from the archive can run. It requires `x0` to be BFloat16Storage, contiguous (strides 24336, 2704, 52, 1), at offset 0, with `latent_shape`/`source_shape` metadata matching, from a little-endian archive. It then writes the `data/0` storage bytes verbatim. Nothing is converted, widened or remapped. `text_embeds`, `prompt` and the shape metadata are discarded.

**Representation class.** `derived_operational_numeric` is correct. The tensor is:
- Deterministic: posterior mode with fixed normalization constants, a documented deterministic function of the source MP4.
- Pinned: cache commit, per-file size and SHA-256, and the video and encoder revisions.
- Machine-facing: the tensor a diffusion training loop consumes; the card calls the repository a working cache that exists to skip the encode step.
- Operationally real: a published upstream artifact copied byte for byte.

None of the rejection categories applies: no local remap, no width mirror (bf16 is the stored dtype and the 16 bits are fully used), no overlay, no local feature engineering, no duplicated view. This matches accepted precedent for published model outputs (`alphafold_db_pae_matrices_f32`, `google_alphaearth_satellite_embeddings_i8`) and for deterministic machine representations (`tokens_t5_gutenberg`). The derived label is more honest than `native_numeric`, because the values are a learned representation of video, not measurements. The card calls itself "a working cache, not a primary dataset". Pinning means any later removal fails loudly rather than silently.

**Rule 2.** Satisfied. The source videos are synthetic, but they were produced upstream by the published VBVR generators and released under Apache-2.0. The latents were computed upstream as well; the recipe invents no numbers. The corpus already accepts upstream-rendered or simulated material: `blender_open_movies_yuv420_u8`, `apple_hypersim_normal_cam_f16`, `zenodo_zeroswarm_tcp_sequence_u32`, `the_well_post_neutron_star_merger_density_f32`, `sxs_bbh_extrapolated_strain_modes_f64` and `zenodo_calochallenge_showers_f64`. The recipe states the synthetic origin and says explicitly that flat-shaded 2-D scenes are not a stand-in for natural-video latents. The bytes back that up: the natural-video normalization constants leave per-channel means between -2.40 and +2.46.

**Rule 1 homogeneity.** One coherent material; no split. All samples share:
- the same encoder weights and the same normalization constants;
- the same input geometry and the same posterior mode;
- the same bf16 lattice and the same tensor layout.

The value scale is uniform. Per-sample std is 1.307–1.721, the extremes are -9.125 and 9.625, there are 2,340–2,967 distinct codes per sample, and order-0 entropy is 9.47–10.33 bits. All 36 generators are VBVR G-series (geometry and graph) scenes from one suite. What differs between generators is scene content, and that shows up only as spatial redundancy:
- equal horizontal neighbours: 2.0–3.0% for the grid generators G-12, G-14, G-17 and G-18, 9.3% for G-41, and up to 66.6% for flat-background G-11;
- zlib -9 ratio: 1.56–5.38 on the samples checked.

This is scene variation within one quantity, not a change of unit, scale, lattice or process. Thirty-six families of six samples would fragment one quantity.

**Rule 9.** The cache card describes 100 families and about 104,225 samples of the parent cache. The pinned `-t2v-only` revision holds exactly 36 generator directories, all G-series; none of the 37 O-series generators is present. The manifest description, `[safety].provenance_notes`, the series `filtering` and the README all state these 36, and the output realizes 6 × 36 = 216. The only mention of 100 is the README sentence explaining the discrepancy.

**Selection.** The first six lexicographic files of each directory, pinned with LFS sizes and SHA-256 in `scripts/selected_files.tsv`. Each directory holds more than 1,000 clips (the card says about 1,000–1,050 per family), so this is a bounded deterministic subset of a population of tens of thousands of clips. It sits well above the roughly 100 MB a family needs and well under the 1 GB cap. The download is 216 files and 1,411,161,368 bytes, a 2.8x ratio caused by the 4 MiB of text embeddings bundled in each file; no leaner source exists.

## Accepted output

- Series: `wan22_ti2v_vae_latent_bf16` (primary, float, 16-bit bfloat16, little-endian, `derived_operational_numeric`)
- Natural record kind: `complete_video_clip_vae_latent_tensor`
- Primary samples: 216 (36 generators × 6)
- Values per sample: 1,168,128, shape (48, 9, 52, 52)
- Primary values: 252,315,648
- Primary bytes: 504,631,296
- Median sample: 1,168,128 values
- Per-sample std: 1.307–1.721; value range -9.125 to 9.625; zero and non-finite counts 0
- Distinct BF16 codes per sample: 2,340–2,967; most common code at most 0.87% of a sample
- Order-0 entropy: 9.47–10.33 bits per value; mantissa entropy about 6.9 of 7 bits
- Digest of the sorted per-sample SHA-256 values in the index (concatenated): `0d5966dac431bdf2d54e87499d289745adbe40036ab282d94fb5b75dae672c73`

Local download, build and independent byte-for-byte verification all completed successfully against the pinned resources on 2026-10-14.

## Judge checks

- Gate: `python3 tools/autocollect/gate.py staging/hf_vbvr_wan22_vae_latents_bf16` passed with no warnings: 252,315,648 values, 504,631,296 bytes, 216 samples, width 16. I ran it before and after the repair.
- Reproducibility: I ran `bash staging/hf_vbvr_wan22_vae_latents_bf16/verify.sh` myself before and after the repair and it succeeded both times. It re-hashes all inputs, re-decodes every archive, and compares the output bytes, the index and the stats. `build.sh` and `verify.sh` read only local files; no script contains network imports, tokens or authorization headers. The 216 `.pt` files total 1,411,161,368 bytes, matching the manifest.
- Repair is byte-neutral: the per-sample mean and std in the index are identical to my first-review snapshot, the first row's SHA-256 is unchanged (`9e17a320…`), and the sorted-hash digest matches the one recorded before the repair. The new Diffusers card on disk is byte-identical to the copy I fetched independently.
- Container: `pickletools` disassembly shows `x0` = `_rebuild_tensor_v2(BFloat16Storage '0', numel 1168128, offset 0, (48,9,52,52), (24336,2704,52,1))`, with `text_embeds` in storage `1` (discarded), matching the card.
- Bytes, all 216 samples, standard-library Python: the ranges above, all sample hashes distinct, and exhaustive horizontal-neighbour equality computed per generator. Identical full 48-channel neighbour vectors run from 0% in grid generators to 26.7% in flat-background ones.
- Near-duplicates: across 540 within-generator pairs, positional identity is 2.4–55.1% (median 32.3%) and mean absolute difference is 0.016–0.953 (median 0.215). Random cross-generator pairs give 0.5–41.0% and 0.098–1.094. The closest pair (G-11 00000001 vs 00000050) is 48.7% identical by position, with only 0.5% of positions differing by more than 0.5: a shared rendered background with a moving object, not a duplicate.
- README figures: the README quotes the exhaustive ranges rounded (order-0 entropy 9.5 to 10.3 bits, up to two thirds of horizontal neighbours equal in flat-background generators).
- Population and selection: the HF tree API at the pinned revision lists 36 generator directories. Both directories I checked (G-11, G-43) paginate past 1,000 files, and their first six lexicographic names match the selection TSV.
- Novelty: `novelty.py --url` on all origins and terms found no prior local, staging, registry, ledger or downstream use. `--type video_vae_latent --instrument wan22_ti2v_5b_vae --archive huggingface.co/central-cat` returned 0/0/0. The vocabulary's nearest types are `geo_embedding_raster`, `nn_weights`, `video_frames` and `rendered_gbuffer`. Breadth is STRONG per the zlsim measurement, with no fill warnings.
- Rights: I read all four pinned cards and confirmed the license metadata of the cache and both encoder repositories through the HF API (apache-2.0; cache public and not gated).
