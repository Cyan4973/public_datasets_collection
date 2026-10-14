# hf_fluxreason_flux2_vae_latents_f16

- Date: 2026-10-14
- Status: blocked
- Candidate dataset: FLUX-Reason-6M FLUX.2 Image VAE Latents Float16 (QLNI/FLUX-Reason-6M-flux2-latents, Aesthetics-Part01 shard 00100: lat (5000,128,16,16) '<f2')
- Source: https://huggingface.co/datasets/QLNI/FLUX-Reason-6M-flux2-latents (revision d5646a9ab02485008bbf6183a68f7dbb0c13732f)
- Why it looked promising: Native IEEE float16 learned image-VAE latents (FLUX.2 encoder, patchified 2x2, BatchNorm-normalised). The corpus has no image-VAE latent family and no binary16 activation family; the nearest is the bf16 Wan2.2 video latent family. Decoding is trivial: an uncompressed npz/npy whose first member is lat.npy. One 332.7 MB shard gives 5,000 samples of 65,536 B each.
- Failure class: license (conflicting upstream terms)
- What happened: Author-phase probing confirmed the technical path and pinned these items:
  - The cache card (1,570 B, sha256 adec42a0...) says 'license: apache-2.0'.
  - FLUX-Reason-6M card @a92fe58364cbd2273dc10938184f995388052185 (8,224 B, sha256 13a0593b...) says 'license: apache-2.0' and states the images were 'synthesized by the state-of-the-art FLUX.1-dev model'.
  - FLUX.2-small-decoder card @a3efc24f613ef42d9428af62fdbd6f5fd8856c4a (3,862 B, sha256 b8e19f40...) says apache-2.0.
  - Shard 00100 LFS: 332,669,146 B, sha256 d05631454d42374cb165457e5c3f49c7d5d06b64b4431a68088932246091c504.

  Then I read the full pinned FLUX.1 [dev] Non-Commercial License v1.1.1 (github black-forest-labs/flux @474dc4205306cb76c46ba510e35eec7bbed5efd1, model_licenses/LICENSE-FLUX1-dev, 18,621 B, sha256 6f7b3d94ddd94380a4dc2d1211ed57883d320dea96f4393b34d4a454041029e1). Two clauses bear on outputs:
  - Clause 2.d allows Output 'for any purpose (including for commercial purposes), except as expressly prohibited herein', and forbids training a model competitive with FLUX.1 [dev]. Our compression transformer is not competitive with an image generator, so 2.d alone would not apply.
  - Section 4.a(i) says the licensee 'will not, and will not permit, assist or cause any third party to ... use, modify, copy, reproduce ... or Distribute the FLUX.1 [dev] Model (or any Derivative thereof, or any data produced by the FLUX.1 [dev] Model), in whole or in part, (i) for any commercial or production purposes'.

  So the generator's licence explicitly restricts third-party commercial or production use of model-produced data. That conflicts with the Apache-2.0 label on the images and on the derived latents, and corpus training plausibly counts as production use. Counter-argument: BFL 'claim[s] no ownership rights in and to the Outputs' (2.d), and the restriction is contractual on the licensee, so it may not run with the data. Settling that is a legal judgement outside autocollect's remit. The card and screener cited only 2.d.

  Secondary concern: the upstream 'Entity' characteristic includes generated depictions of real named people (e.g. athletes), and the card says the latents decode back to the pictures at about 36 dB.
- Evidence: Pinned licence text above, lines '2.d Outputs' and '4. Restrictions ... a.'. HF API ?blobs=true at revision d5646a9a: gated False, license apache-2.0, 1,182 files. Precedents for conflicting terms: deepmind_alphamissense_substitution_scores_f32 (blocked), zenodo_wallhack18k_esp32_wifi_csi_i8 (blocked), nhanes_paxraw_d_actigraph_intensity_u16 (screened out over a field-of-use restriction). An HF search for other FLUX.2 latent caches found only license:other or unlabelled repos, plus one MIT synthetic cache with unchecked provenance.
- Logs: none (no download run; probes totalled ~40 KB of cards and API JSON in /tmp/autocollect/hf_fluxreason_flux2_vae_latents_f16/)
- Decision: Block. Do not collect latents of FLUX.1-dev-generated images while section 4.a(i) of the generator's licence conflicts with the downstream Apache-2.0 label.
- Retry conditions: (a) A maintainer or legal policy note rules that the FLUX.1 [dev] licence restrictions bind only the generating licensee and do not reach downstream users of Apache-2.0-relicensed outputs, or BFL publishes a clarification or licence revision removing 'any data produced by the FLUX.1 [dev] Model' from 4.a(i). Then the recipe is straightforward: one shard >= 60 without dino (e.g. 00100, sha256 d0563145...), 5,000 x 65,536 B f16 samples. (b) Alternatively, find a FLUX.2-VAE (or other image-VAE) f16 latent cache whose source images are real photographs or renders under an explicit permissive licence with no generator-model terms.
