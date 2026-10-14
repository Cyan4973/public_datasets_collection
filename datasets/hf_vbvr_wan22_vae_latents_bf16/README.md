# VBVR Wan2.2-TI2V-5B Video VAE Latents BFloat16

Native bfloat16 video VAE latents from a pinned, Apache-2.0 Hugging Face diffusion
training cache (`Central-Cat/vbvr-latent-cache-832x832x33f-t2v-only`). Each sample is the
complete latent of one 33-frame 832x832 clip from `Video-Reason/VBVR-Dataset`, encoded by
the Wan2.2-TI2V-5B VAE: shape `(48, 9, 52, 52)` in C,T,H,W order, 1,168,128 values.

## Why this material

Each sample is a learned latent representation of video rather than a measurement: the
tensor a video VAE produces from 33 frames, published by the cache as native bfloat16. The
corpus has no such material at any width; its 16-bit ML families are model weight tensors.

Measured on the built samples:

- The values are dense: order-0 entropy is 9.5 to 10.3 bits per value and the 7 mantissa
  bits carry 6.9 bits of entropy. Every sample has 2,340 to 2,967 distinct codes, no zeros
  and no fill value.
- The per-channel normalization constants come from the VAE config and do not center this
  synthetic content: per-channel means range from -2.40 to +2.46, and per-sample standard
  deviation is 1.31 to 1.72 rather than 1.
- The latents keep the spatial structure of the scenes. Flat-background generators produce
  long runs of identical latent vectors (up to two thirds of horizontally adjacent values
  are equal), while grid generators produce almost none (2 to 9%).

The source videos are flat-shaded 2-D scenes, so these latents are not a stand-in for
latents of natural video.

## Provenance and license

- Latent cache: Apache-2.0, revision `951c2880a946f0a947bc32c9f48df30767102175`.
- Source videos: VBVR-Dataset, Apache-2.0, revision `7ef37ad3706c1a146143f9ab7611730487bd8c70`;
  programmatically generated reasoning scenes, no people.
- Encoder: the Diffusers-format Wan2.2-TI2V-5B VAE named on the cache card
  (`Wan-AI/Wan2.2-TI2V-5B-Diffusers`, revision `b8fff7315c768468a5333511427288870b2e9635`),
  Apache-2.0. The original-format repository (`Wan-AI/Wan2.2-TI2V-5B`, revision
  `921dbaf3f1674a56f47e83fb80a34bac8a8f203e`) is also Apache-2.0; both cards are pinned.
  Encoding uses the deterministic posterior mode.

## Selection

The cache card describes 100 task families, but the pinned revision holds 36 generator
directories, all of them G-series (geometry and graph) generators; none of the 37 O-series
(object and physics) generators is present. `scripts/selected_files.tsv` pins the first six
files (lexicographic) of each of those 36: 216 files, 1.41 GB to download, 0.50 GB of
primary output. Each cache file also holds UMT5 text embeddings and the prompt; both are
discarded.

## Scripts

- `download.sh`: fetches the four pinned cards (cache, upstream videos, two encoder
  cards) and the 216 selected files, checking each size and SHA-256, then validates every
  archive and checks that each card still declares Apache-2.0.
- `build.sh`: decodes each archive with a restricted unpickler (only the globals
  `torch.save` emits for tensors are resolved; no torch dependency, no code execution) and
  writes `x0` verbatim.
- `verify.sh`: independently re-decodes every archive and compares outputs, index, and
  stats.

## Status

Downloaded, built and verified locally on 2026-10-14: 216 samples, 252,315,648 values,
504,631,296 bytes. Per-sample standard deviation ranges from 1.31 to 1.72, the largest
magnitude is 9.6, each sample holds 2,340 to 2,967 distinct BF16 codes, and no sample has
non-finite values or zeros.
