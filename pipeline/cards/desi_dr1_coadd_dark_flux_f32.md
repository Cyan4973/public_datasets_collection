# DESI DR1 (iron) Main-Survey Dark-Program HEALPix Coadded Spectra: B/R/Z-Arm Calibrated Flux Density, Native Float32

- Candidate id: `desi_dr1_coadd_dark_flux_f32`
- Width: float32
- Quantity: Coadded calibrated spectral flux density (1e-17 erg/s/cm^2/Angstrom) of galaxies/quasars per DESI spectrograph arm (B 2751, R 2326, Z 2881 wavelength pixels)
- Source: https://data.desi.lbl.gov/public/dr1/spectro/redux/iron/healpix/main/dark/
- Resources: https://data.desi.lbl.gov/public/dr1/spectro/redux/iron/healpix/main/dark/100/10000/coadd-main-dark-10000.fits, https://data.desi.lbl.gov/public/dr1/spectro/redux/iron/healpix/main/dark/100/10000/redux_iron_healpix_main_dark_100_10000.sha256sum, https://data.desi.lbl.gov/doc/acknowledgments/
- License: CC BY 4.0
- License evidence: https://data.desi.lbl.gov/doc/acknowledgments/
- License quote: The Dark Energy Spectroscopic Instrument (DESI) data are licensed under the Creative Commons Attribution 4.0 International License ("CC BY 4.0"). (DR1 page: 'The DR1 data are released under the Creative Commons Attribution 4.0 International License (CC BY 4.0).')
- Natural record: One healpix coadd file's per-arm FLUX image HDU (B_FLUX / R_FLUX / Z_FLUX, NTARGET x NWAVE float32, e.g. 417 x 2751); alternative: one target's coadded spectrum per arm (>=2326 values, above the 1000 floor)
- Estimated samples: 120
- Estimated primary values: 130,000,000
- Estimated download bytes: 540,000,000
- Estimated primary bytes: 520,000,000
- Decode path: FITS image HDUs, uncompressed BITPIX=-32 big-endian. download.sh walks HDU headers with small curl -r range GETs (FIBERMAP, EXP_FIBERMAP, B_WAVELENGTH, B_FLUX...) and fetches only the three *_FLUX data ranges (~4.6 MB each per file, offsets computed from NAXIS/PCOUNT; e.g. file 10000: B_FLUX header at 256320). struct '>f' -> little-endian float32. Verify against per-dir sha256sum is not possible for ranges, so validate header cards (EXTNAME, BUNIT, NAXIS1 in {2751,2326,2881}).
- Novelty kind: new_source
- Measurement type: spectrum_1d
- Instrument line: desi_mayall_spectrograph
- Archive collection: data.desi.lbl.gov/public/dr1
- Novelty evidence: novelty.py --url data.desi.lbl.gov and --terms desi/coadd: no matches in recipes, registry, ledger, downstream. spectrum_1d at 32-bit holds only lab spectra (soil FTIR, marine DOM MS1, powder XRD); no astronomical optical spectra in the corpus (sdss_corrected_frame_fits_i16 was images, transient failure).
- Homogeneity: Restrict to survey=main, program=dark (faint ELG/LRG/QSO targets) so flux scale is coherent; exclude bright/backup/sv/cmx. Same unit across arms; builder may emit one series per arm or one combined flux series. Exclude IVAR, MASK, RESOLUTION, WAVELENGTH (auxiliary at most).
- Risks: Natural-record choice (HDU image vs per-target row) may be challenged as concatenation; per-target samples are each >1000 values so either passes the floor. Range-download logic is more complex than whole-file. Some rows (fibers with no data) may be all-zero flux; verify should reject degenerate rows/HDUs. data.desi.lbl.gov is NERSC-hosted; transfer speed variable.
- Probe evidence: Listing 200 OK: main/dark has 223 healpix groups (group 100 holds 100 healpix dirs). coadd-main-dark-10000.fits = 186,281,280 bytes. HDU walk via range GETs: B_FLUX BITPIX=-32 [2751,417] BUNIT '10**-17 erg...' at offset 256320; R_FLUX [2326,417] at 64540800; Z_FLUX [2881,417] at 118906560. License page fetched (CC BY 4.0).

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_32bit/scout.20261008_164906.jsonl`).
