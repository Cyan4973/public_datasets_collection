# Blender Open Movies YUV420 Uint8

This candidate targets decoded 8-bit Y, Cb, and Cr frame planes from three
Blender Foundation open movies. Video frames would add temporal image structure
that is absent from the accepted corpus while retaining natural plane and frame
boundaries.

The intended bounded profile is 320 frames from a Wikimedia-generated 480p
VP9 transcode of each of three movies. This should produce roughly 492 million
uint8 values/bytes: one full-resolution luma plane and two half-width,
half-height chroma planes per frame. Exact pixel formats, frame rates, source
sizes, and identities must be established before build implementation.

Run the discovery step first:

```bash
bash datasets/blender_open_movies_yuv420_u8/discover.sh
```

It queries only Wikimedia Commons metadata for the exact three full-film
titles and their generated video derivatives. It does not download movie
payloads. Candidate 720p transcode URLs, dimensions, MIME types, and
machine-readable licenses are written to
`.data/discovery/blender_open_movies_yuv420_u8/candidates.tsv` for review. This
route avoids the Cloudflare challenge currently blocking Blender's directory
indexes.

After discovery, download the three selected 480p transcodes:

```bash
bash datasets/blender_open_movies_yuv420_u8/download.sh
```

The downloader enforces the pinned local size and SHA-256 identities and uses
`ffprobe` to require VP9, 8-bit YUV420, and the expected frame geometry, rate,
and duration.

Build and verify after acquisition:

```bash
bash datasets/blender_open_movies_yuv420_u8/build.sh
bash datasets/blender_open_movies_yuv420_u8/verify.sh
```

For each movie, the recipe takes four 80-frame windows centered at 20%, 40%,
60%, and 80% of the duration. Each window becomes three independent temporal
plane tensors: Y shaped `80×height×854`, and Cb/Cr shaped
`80×(height/2)×427`. This systematic selection avoids content-based
cherry-picking and preserves both spatial and temporal adjacency.
