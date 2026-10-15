# AnyCam MCV 480p Wan2.1 Video VAE Latents BFloat16

Native bfloat16 video VAE latents from a pinned, Apache-2.0 Hugging Face diffusion training cache
(`wlyu/AnyCam_MCV_480p_wan21_latent`). Each sample is the complete Wan2.1 VAE latent of one
81-frame 832x480 target-camera clip of a MultiCamVideo (ReCamMaster) Unreal Engine 5 scene:
shape `(16, 21, 60, 104)` in C,T,H,W order, 2,096,640 values, 4,193,280 bytes.

## Why this material

The closest accepted family is `hf_vbvr_wan22_vae_latents_bf16`, which holds Wan2.2-TI2V-5B latents
(48 channels, 16x spatial compression) of flat-shaded 2-D procedural reasoning videos. This recipe
differs in both encoder and content:

- Encoder: the Wan2.1 VAE, with 16 channels, 8x spatial and 4x temporal compression and its own
  normalisation.
- Content: photoreal 3-D renders with animated characters, moving cameras, lighting and texture.

A one-scene probe (`mcv_f35_scene1646`) showed what that content does to the latents:

- Standard deviation is 0.92, with 2,514 distinct BF16 codes and no single code above 0.25%.
- Only 1.4% of horizontally adjacent values are equal. VBVR's flat backgrounds reach two thirds.
- Per-channel means sit between -0.82 and +0.86.

Whether this is far enough from VBVR is for `zlsim.py gate` to decide after the build.

## Provenance and license

All four links in the chain declare `license: apache-2.0` in pinned card frontmatter. The cards
are downloaded and re-checked:

- Latent cache `wlyu/AnyCam_MCV_480p_wan21_latent` @ `acb9cc2a3851b1e987a9dbf02895a311d263d5a8`
- Pair videos `wlyu/AnyCam_MCV_480p` @ `3e7bacb2f216c305abc1b80a6c7453eaec14ca7a`
- Source renders `KlingTeam/MultiCamVideo-Dataset` @ `4e7d995480cfa915f7c3721e616ed14789d87ff7`
  (formerly KwaiVGI). Its 37 environments, 66 characters and 93 animations come from Fab and
  Mixamo. The renders are released under Apache-2.0; the asset licenses are not separately
  verified. No real people appear.
- Encoder `alibaba-pai/Wan2.1-Fun-1.3B-InP` @ `9bcbbcf673c0e6a996df6f3f25bee596ffa36d47`
  (Wan2.1_VAE, encoded through DiffSynth with `tiled=False`).

## Selection and scope

- The cache holds one archive per scene (7,814 in total): f18 2,366, f24 2,247, f35 1,890 and
  f50 1,311, named after the camera focal length.
- The recipe takes 30 scenes per focal group. They are evenly spaced through each group's sorted
  file list, at index `floor((i + 0.5) * n / 30)`. Scenes with adjacent numbers often share one of
  the 37 environments, so a lexicographic prefix would be much less diverse.
- That gives 120 samples and 503,193,600 bytes of primary output.
- Kept: only `latents['target']`.
- Not kept:
  - `latents['source']`: a second, synchronised camera of the same scene, so a correlated view.
  - `source_cond` and `target_cond`: object-only renders on white, a different regime.
  - The umT5 `text_embedding`, the prompt and the metadata row.

## Download: byte ranges, not whole files

Each archive is an uncompressed (stored) `torch.save` zip of about 18 MB. Instead of fetching it,
`download.sh` makes three HTTP Range requests per scene and stores 503.7 MB in total, about what
is kept. The ranges, pinned in `scripts/selected_files.tsv`, are:

- `head.bin`: bytes `[0, first storage)`, containing `data.pkl` and `byteorder`
- `target.bin`: the local header, stored bytes and data descriptor of the target storage, which
  is `data/2` in every selected archive
- `tail.bin`: the central directory through EOF

Integrity check: the data.pkl and target member CRC-32s from the central directory must match
the pinned values, and the member data must match them too. Every scene is then fully decoded
before the next is fetched. The whole-file LFS SHA-256 is pinned for provenance, but it cannot
be checked without downloading the discarded members.

`scripts/discover.py` records how the TSV was produced. It needs about 8 KB of range requests per
archive and is not part of the download/build path.

## Scripts

- `download.sh`: fetches the four pinned cards and the 360 pinned ranges with curl, then validates
  each scene (CRCs, offsets, restricted unpickle, tensor metadata, statistics).
- `build.sh`: a hand-written zip reader parses each scene's central directory and local headers
  from the fragments. A restricted unpickler then reads `data.pkl`; it resolves only
  `torch._utils._rebuild_tensor_v2`, `collections.OrderedDict` and `torch.BFloat16Storage`, with
  no torch dependency and no code execution. Every latent's dtype, shape `(16,21,60,104)`,
  contiguous strides, offset 0 and numel 2,096,640 are checked, along with `vae == 'Wan2.1_VAE'`,
  `tiled == False` and byteorder `little`. The target storage is written verbatim.
- `verify.sh`: reassembles each archive as a sparse file from its fragments, reads it with the
  standard-library `zipfile` module (an independent zip path, CRC-checked), and compares the
  result to the samples, the index and the stats.

## Status

Authored on 2026-10-14. Downloaded (503,778,684 bytes including logs/cards), built and verified
on 2026-10-14: 120 samples, 251,596,800 bf16 values, 503,193,600 bytes, 30 per focal group.
Across samples: std 0.51-1.41, values in [-4.44, 4.78], at least 2,284 distinct BF16 codes per
sample, and no single code above 0.52% of a sample.
