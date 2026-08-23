# Blender Open Movies YUV420 Uint8 — 2026-08-23

## Outcome

`blender_open_movies_yuv420_u8` adds the corpus's first decoded video-frame
material: temporal Y, Cb, and Cr plane tensors from *Big Buck Bunny*, *Sintel*,
and *Tears of Steel*. Four deterministic 80-frame windows are retained from
each film at 20%, 40%, 60%, and 80% of its duration.

The result is 36 independent three-dimensional samples and 491,904,000 uint8
values/bytes. Luma contributes 327,936,000 bytes; each half-resolution chroma
family contributes 81,984,000 bytes. Keeping 80 consecutive frames inside each
sample preserves temporal adjacency as well as spatial image structure.

## Source and rights

All three Blender Foundation open movies and their Wikimedia Commons
transcodes are explicitly marked CC BY 3.0. The tracked inventory preserves
the movie title, derivative URL, attribution, license URL, exact size,
SHA-256, dimensions, frame rate, and duration.

The initial official Blender download-directory discovery was blocked by a
Cloudflare HTTP 403 challenge. Wikimedia Commons provided a reproducible
machine-readable alternative with explicit license metadata and generated VP9
transcodes. The selected 480p files total 258,722,580 compressed bytes, avoiding
the 571 MB to 3.5 GB original masters while retaining full-film provenance.

## Selection and representation

The pinned videos are VP9 WebM with native 8-bit `yuv420p` decoded output:

- *Big Buck Bunny*: 854×480 at 60 fps;
- *Sintel*: 854×364 at 48 fps; and
- *Tears of Steel*: 854×356 at 24 fps.

Window centers are fixed duration fractions rather than hand-picked content.
Each decoded frame is split according to the YUV420 layout without conversion
to RGB, resizing, chroma upsampling, normalization, or value remapping. Y is
kept at full resolution; Cb and Cr retain their native half-width and
half-height grids.

## Verification

Build and fresh-decode verification passed on 2026-08-23 with FFmpeg 8.0.1.
All 36 generated files byte-match an independent decode from the pinned
sources. Luma samples contain 152–256 distinct values; chroma samples contain
29–172. Every sample has hundreds of thousands to millions of adjacent-value
transitions, no dominant byte exceeds 41%, and no decoded sample is duplicated.

Every output is a raw uint8 tensor with shape `[80, height, width]`. Byte order
is inherently irrelevant for one-byte values and is recorded as little-endian
to satisfy the corpus contract.
