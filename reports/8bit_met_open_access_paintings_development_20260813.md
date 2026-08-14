# Met Open Access painting RGB planes uint8 development — 2026-08-13

## Outcome

Accepted `met_open_access_paintings_u8`, 30 original-resolution unsigned-byte
RGB color planes decoded from ten reviewed European painting reproductions in
The Metropolitan Museum of Art Open Access collection.

This fills a missing 8-bit image regime. Existing CIFAR-10 and PathMNIST
families provide many tiny fixed-shape images; this family provides a small
number of large, variable-shape natural image planes, each approximately
9.6–13.3 million values.

## Selection

Metadata-only discovery queried ten visual themes in the European Paintings
department. Automated first matches were reviewed and replaced where their
visual relevance was weak. The accepted selection contains:

- *Tiger in Repose* — animal texture;
- *Interior of the Oude Kerk, Delft* — architectural lines and perspective;
- *Basket of Flowers* — fine color and edge detail;
- *The Forest in Winter at Sunset* — dark textured gradients;
- *The Garden of the Tuileries on a Spring Morning* — dense outdoor detail;
- *A Brazilian Landscape* — broad landscape regions;
- *Night Scene on the Volga* — low-light tonal structure;
- *Whalers* — sea, sky, and atmospheric edges;
- *Rue Eugène Moussoir at Moret: Winter* — bright snow structure; and
- *Still Life with a Skull and a Writing Quill* — controlled objects and dark
  background.

Every exact object ID declares `isPublicDomain=true`, belongs to the European
Paintings department and Paintings classification, and exposes an official
`images.metmuseum.org` original JPEG. The tracked selection pins object and
image URLs, dimensions, source sizes, and SHA-256 hashes.

## Decoding and sample boundaries

All ten sources are 8-bit, three-component JPEGs between 2.7 and 13.3
megapixels. FFmpeg decodes each image once to original-resolution RGB24 with
one thread and fixed `bitexact`, `accurate_rnd`, and `full_chroma_int` flags.
The recipe performs no resizing, cropping, normalization, or artistic color
adjustment. It then deinterleaves R, G, and B into three row-major uint8
planes. One complete painting color plane is one natural sample.

The accepted material contains:

- 10 source images and 30 RGB-plane samples;
- 109,870,818 pixels and 329,612,454 primary values/bytes;
- 9,577,043–13,256,000 values per plane, median 10,817,869.5;
- 30 unique decoded-plane hashes, all pinned in `expected_planes.tsv`;
- 131–256 distinct byte values per plane; and
- zlib-9 ratios from 0.5525 to 0.8328, median approximately 0.7252.

The per-plane form preserves strong two-dimensional spatial predictability
without offering the model immediate inter-channel prediction. It also avoids
the opaque compressed JPEG byte stream as training material.

## Verification, license, and safety

The accepted-path build generated all 30 samples. Verification independently
revalidated policy evidence, object metadata, source identities, decoder
parameters, output dimensions, and pinned plane hashes; freshly decoded bytes
were compared to every output, and stale or extra files were rejected.

The Met's official Open Access page identifies public-domain material under
CC0, and each selected object independently carries the public-domain flag.
Artwork object IDs, titles, artists, and official object URLs remain in the
sample index for attribution and provenance. The numeric samples contain only
painting pixels; no personal or sensitive data is present.
