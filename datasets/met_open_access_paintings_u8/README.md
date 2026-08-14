# Met Open Access Paintings U8 — discovery

This staging family targets a small, coherent selection of public-domain
European paintings from The Metropolitan Museum of Art Open Access program.
The eventual numeric material will be decoded uint8 image intensities, with
one natural sample per nonconstant R, G, or B plane at original resolution.

The first step fetches metadata and rights evidence only; it does not download
image payloads:

```bash
bash datasets/met_open_access_paintings_u8/discover.sh
```

Discovery queries ten visual themes, validates each selected object's
`isPublicDomain` flag, department, painting classification, and original-image
URL, and writes the exact candidate metadata under
`.data/discovery/met_open_access_paintings_u8/` for review before acquisition.

After review, acquire the ten selected original JPEGs with:

```bash
bash datasets/met_open_access_paintings_u8/download.sh
```

The downloader revalidates every object's public-domain metadata, requires an
8-bit three-component JPEG between one and 100 megapixels, and enforces the
projected one-gigabyte decoded-output cap.

After acquisition, decode and independently verify the RGB planes with:

```bash
bash datasets/met_open_access_paintings_u8/inspect.sh
bash datasets/met_open_access_paintings_u8/build.sh
bash datasets/met_open_access_paintings_u8/verify.sh
```

FFmpeg is the only external decoder dependency. The recipe uses one thread and
fixed bit-exact RGB24 conversion flags, preserves original dimensions, and
emits 30 natural samples: one row-major uint8 plane for each R, G, and B
channel of each painting.
