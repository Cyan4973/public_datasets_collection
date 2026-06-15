# Deferred: SDSS Corrected Frame FITS Int16

Dataset id: `sdss_corrected_frame_fits_i16`

Status: deferred from the active 2026-06-14 16-bit hunt benchmark.

Reason:

- The staged download script attempted to discover `frame-*.fits.bz2` files from selected SDSS DR17 frame directories.
- The user-run download produced HTTP 503 responses for every selected directory and created an empty `download_plan.tsv`.
- No frame payload was downloaded, so the candidate could not satisfy the local reproducibility requirement.

This is not a rejection of SDSS imaging as material. It is a rejection of the current access strategy. A future attempt needs exact stable direct frame URLs, plus local validation that the selected FITS primary images are simple two-dimensional `BITPIX = 16` products.
