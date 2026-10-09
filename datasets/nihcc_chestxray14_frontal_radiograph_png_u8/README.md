# NIH ChestX-ray14 frontal chest radiographs (uint8)

This recipe collects frontal-view (PA/AP) chest X-ray images from the NIH
Clinical Center ChestX-ray14 release (112,120 images of 30,805 patients;
<https://nihcc.app.box.com/v/ChestXray-NIHCC>). NIH extracted the images from
the hospital PACS, windowed them and resized them to 1024x1024, and
publishes them only as 8-bit grayscale PNGs (FAQ Q06) in 12 tarballs of
2.0-4.2 GB.

One sample is one image: the decoded 1024x1024 uint8 grayscale raster
(1,048,576 values), written row by row from the top.

## Scope

The full release is about 45 GB, so the recipe takes a bounded subset that can
be fetched directly. For each of the 12 tarballs it downloads only the first
14 MiB (HTTP Range) and keeps every PNG member whose data lies wholly inside
that prefix. Tar order within a tarball is not sorted by patient (for example
`00027725_036`, `00025512_001`, `00025600_002`), so each prefix spans many
patients. The realized build keeps 430 images (34-38 per tarball, 429
distinct patient indices), 450,887,680 bytes in total.

PNGs that are not 1024x1024 8-bit grayscale (ChestX-ray14 is known to contain
a few RGBA / grey+alpha images) are skipped and listed in
`filtered/<id>/ingest_stats.json`. They are never converted. Two of the 432
whole members were skipped, both 1024x1024 RGBA (colour type 6):
`images_003` `00004882_001.png` and `images_004` `00006757_000.png`.

Some radiographs are smaller or rotated and NIH padded them with black (0)
to 1024x1024. Three images are 48-52 % zero. The padding is kept as
published.

## Licence

`FAQ_CHESTXRAY.pdf` in the official Box folder (72,223 bytes, SHA-256
`674665256e6a14c8ebaa93648f438c2b4ca21205167839559bab3ecc89b6b83a`), Q04:

> Are there any restrictions in using this dataset?
> A: The usage of the data set is unrestricted. But you should provide the link
> to our original download site, acknowledge the NIH Clinical Center and
> provide a citation to our CVPR 2017 paper.

`download.sh` fetches this PDF on every run and fails unless its size,
SHA-256 and extracted Q04 sentence still match. Citation: Wang X, Peng Y, Lu
L, Lu Z, Bagheri M, Summers RM. *ChestX-ray8: Hospital-scale Chest X-ray
Database and Benchmarks on Weakly-Supervised Classification and Localization
of Common Thorax Diseases.* IEEE CVPR 2017. Original download site:
<https://nihcc.app.box.com/v/ChestXray-NIHCC>. Acknowledgement: NIH Clinical
Center.

## Privacy

The images are de-identified clinical radiographs. The recipe emits only
pixels. Labels (`Data_Entry_2017.csv`), bounding boxes, age, sex and view
position are not downloaded. The index keeps the tar member name
(`images/<patient index>_<follow-up>.png`) for provenance only.

## Access notes

- The static links `https://nihcc.box.com/shared/static/<hash>.gz` come from
  NIH's `batch_download_zips.py`. They redirect to short-lived signed
  `public.boxcloud.com` URLs, so every request restarts from the static link
  with `-L`. HEAD returns 404, but ranged GET returns 206.
- `download.sh` requires HTTP 206, the expected `Content-Disposition`
  filename and the pinned `Content-Range` total. `--max-filesize` aborts any
  response that ignores the Range header. Interrupted prefixes resume by
  requesting the missing byte range.
- The prefix SHA-256 values, the sample total and the aggregate sample hash
  from the 2026-10-08 download and build are pinned in `scripts/nih_pins.py`.

## Scripts

- `scripts/nih_decode.py`: build side, with gzip-prefix inflate, ustar walk,
  strict PNG decode and the `check-prefix` download validation.
- `scripts/nih_verify.py`: independent re-derivation (manual gzip header parse
  plus raw inflate, `tarfile`, separate PNG chunk walker and unfilter).
- `scripts/selftest.py`: synthetic PNG round trips (all five filter types),
  malformed-PNG rejections and tar-prefix cut tests.
- `scripts/faq_check.py`: licence-evidence check.
- `scripts/nih_pins.py`: pinned URLs, sizes, thresholds and hashes.
