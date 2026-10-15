# AnyCam MCV Wan2.1 video VAE latent bfloat16 development

## Outcome

Accepted `hf_anycam_mcv_wan21_vae_latents_bf16`. It comes from a pinned, public, Apache-2.0 precomputed latent cache. Each sample is the complete Wan2.1 VAE latent of one target-camera clip from a MultiCamVideo (ReCamMaster) Unreal Engine 5 scene. The publisher stores the tensor natively as bfloat16, and the recipe emits it verbatim.

This is the corpus's second video-VAE-latent family. The first, `hf_vbvr_wan22_vae_latents_bf16`, differs in two ways:

- **Encoder.** VBVR uses Wan2.2-TI2V-5B: 48 channels, 16x spatial compression. This family uses the Wan2.1 VAE: 16 channels, 8x spatial compression, its own normalisation.
- **Content.** VBVR is flat-shaded 2-D procedural reasoning clips. This family is photoreal 3-D renders with an animated character and a moving camera.

It is therefore new content in an existing modality, not a new modality. The zlsim breadth measurement is OK. The nearest family is `hf_qwenmath_qwen25_7b_lastlayer_hidden_bf16`, at feature distance 0.0608 with compression loss 0.0273; VBVR is not the nearest. No fill warnings.

## Source and rights

- **Latent cache:** `wlyu/AnyCam_MCV_480p_wan21_latent` at revision `acb9cc2a3851b1e987a9dbf02895a311d263d5a8`.
  - The card (1,259 bytes, SHA-256 `3d8a0eb6…5af1`) declares `license: apache-2.0`. It documents the exact per-scene `.pt` format: `latents` {source, source_cond, target, target_cond} as bf16 [16,21,60,104], encoded with the Wan2.1-Fun-1.3B-InP VAE through DiffSynth with `tiled=False`, already normalised.
  - HF API at the pinned revision: public, not gated, tag `license:apache-2.0`, 7,814 `.pt` files totalling 142,866,910,336 bytes.
- **Intermediate pairs:** `wlyu/AnyCam_MCV_480p` @ `3e7bacb2f216c305abc1b80a6c7453eaec14ca7a`. The card (4,144 bytes, `1ea2b98a…0fcf`) declares `license: apache-2.0`. It documents the target clip as one MultiCamVideo camera, crop-rescaled to 832x480, 81 frames.
- **Source renders:** `KlingTeam/MultiCamVideo-Dataset` (formerly KwaiVGI) @ `4e7d995480cfa915f7c3721e616ed14789d87ff7`. The card (9,009 bytes, `97bc2df4…456d`) declares `license: apache-2.0`.
  - The renders use 37 Fab environments and 66 characters and 93 animations from Fab and Mixamo. The dataset authors release the renders under Apache-2.0; the asset licenses themselves are not separately verified. This matches the accepted Unreal-rendered `tartanair_optical_flow_f32`.
- **Encoder:** `alibaba-pai/Wan2.1-Fun-1.3B-InP` @ `9bcbbcf673c0e6a996df6f3f25bee596ffa36d47`. The card (13,018 bytes, `c3441cf7…58ed`) declares `license: apache-2.0`.
- **Discarded inputs:** the Qwen3-VL prompts, the umT5 text embedding and the SAM-derived control latents are all thrown away, so their terms do not reach the output.
- **Checks in the recipe:** `download.sh` pins all four cards by size and SHA-256. The decoder refuses to run unless each card's frontmatter still says `apache-2.0`.
- **Safety:** no credentials in any script. No real people and no personal data.

## Shape and conversion

Each natural record is one per-scene `torch.save` zip archive. The recipe takes only `latents['target']`: shape (16, 21, 60, 104) in C,T,H,W order, which is 2,096,640 values (4,193,280 bytes).

What is left out, and why:

- `source`: a synchronised second camera of the same scene, so a correlated view.
- `source_cond` and `target_cond`: object-only renders on white, a different regime.
- The text embedding, the prompt and the metadata.

**Download.** `download.sh` makes three pinned HTTP Range requests per archive:

- the head, holding `data.pkl` and `byteorder`;
- the target storage member;
- the central directory.

That keeps the download at 503.8 MB for 503.2 MB kept. Integrity rests on the zip CRC-32s of `data.pkl` and the target member, which are checked against pinned values. The whole-file LFS SHA-256 is recorded for provenance only.

**Build.** A hand-written zip reader and a restricted unpickler do the decoding. The unpickler resolves only `_rebuild_tensor_v2`, `OrderedDict` and `BFloat16Storage`; there is no torch import and no code execution. The build checks:

- all four latents: dtype, shape, contiguous strides, offset 0 and numel;
- `vae == 'Wan2.1_VAE'`, `tiled == False` and byteorder `little`.

It then writes the stored target bytes verbatim. **Verify** decodes a sparse reassembly of each archive with the stdlib `zipfile` module, which is an independent path.

`derived_operational_numeric` is the right class, as for the VBVR precedent. The latents are a deterministic, pinned, machine-facing, published artifact; the recipe performs no inference, remap or widening.

## Accepted output

- **Series:** `wan21_vae_target_latent_bf16` (primary, float, 16-bit bfloat16, little-endian, `derived_operational_numeric`)
- **Natural record kind:** `complete_video_clip_vae_latent_tensor`
- **Primary samples:** 120, which is 30 per focal group (f18, f24, f35, f50). They are evenly spaced through each group's sorted list at `floor((2i+1)n/60)` out of 2,366, 2,247, 1,890 and 1,311 scenes.
- **Values per sample:** 2,096,640; primary values 251,596,800; primary bytes 503,193,600; median sample 2,096,640 values.
- **Per-sample distribution:**
  - std 0.514–1.406; value range -4.4375 to 4.78125; no non-finite values;
  - zeros 524–1,891 per sample;
  - distinct BF16 codes 2,284–2,565; most common code at most 0.52%;
  - order-0 entropy 9.90–10.47 bits per value;
  - horizontal equal neighbours 0.62–4.16% (median 0.91%).
- **Digest** of the sorted per-sample SHA-256 values (concatenated): `ed4382b63cdabced1ca4d8a9945642ed9790308f29192fe162ab614c9eb2be79`

The driver's download, build and verify, and my own independent verify run, all completed successfully against the pinned resources on 2026-10-14.

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/hf_anycam_mcv_wan21_vae_latents_bf16` passed with no warnings: 251,596,800 values, 503,193,600 bytes, 120 samples, width 16.
- **Reproducibility:**
  - I ran `bash staging/hf_anycam_mcv_wan21_vae_latents_bf16/verify.sh` myself and it succeeded. It decodes independently with zipfile and compares bytes, index and stats.
  - `build.sh` and `verify.sh` read only local fragments and cards.
  - `download.sh` is curl-only and has no tokens or authorization headers.
- **Container:** `pickletools` disassembly of `mcv_f24_scene1590.pt/data.pkl` shows `target` -> `_rebuild_tensor_v2(BFloat16Storage '2')`. The other storages are source `'0'`, source_cond `'1'`, target_cond `'3'` and text embedding `'4'`, alongside `vae='Wan2.1_VAE'`. The emitted member is therefore the claimed tensor.
- **Bytes (stdlib, all 120 samples):**
  - the ranges above; exponents concentrated at 123–127 with the full mantissa used, so the width is honest;
  - per-channel means move from scene to scene, between -1.04 and +1.14.
- **Near-duplicates:** over all 7,140 pairs, positional code identity is at most 0.43%. The top correlation, about 0.67, reflects shared channel-mean structure. Same-numbered scenes in different focal groups are unrelated (r 0.15–0.23).
- **Population and selection:** the HF API at the pinned revision lists 7,814 `.pt` files (2,366, 2,247, 1,890 and 1,311 per group). The selection TSV reproduces exactly from the even-spacing formula.
- **Rights:** I read all four pinned cards on disk; each frontmatter says `license: apache-2.0`. I confirmed through the HF API that the cache is public, not gated and tagged apache-2.0.
- **Novelty:**
  - `novelty.py --url` on the cache, MultiCamVideo and encoder URLs, with terms anycam, multicamvideo, recammaster, wan2.1, wan21 and KwaiVGI, found only this staging recipe and its ledger row.
  - `--type video_vae_latent` returns only `hf_vbvr_wan22_vae_latents_bf16`; `--instrument wan21_vae_16ch` and `--archive huggingface.co/wlyu` return 0.
  - Labelled `new_content_same_modality`. The zlsim verdict is OK.
