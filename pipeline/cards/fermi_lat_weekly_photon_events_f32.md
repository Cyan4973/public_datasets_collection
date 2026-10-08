# Fermi LAT Weekly All-Sky Photon Event Files (P305): Reconstructed Photon Energy, Sky Direction and Instrument Angles, Native Float32

- Candidate id: `fermi_lat_weekly_photon_events_f32`
- Width: float32
- Quantity: Per-photon reconstructed gamma-ray energy (MeV), celestial direction RA/DEC (deg) and instrument-frame incidence angles THETA/PHI (deg) from the Fermi Large Area Telescope
- Source: https://heasarc.gsfc.nasa.gov/FTP/fermi/data/lat/weekly/photon/
- Resources: https://heasarc.gsfc.nasa.gov/FTP/fermi/data/lat/weekly/photon/lat_photon_weekly_w800_p305_v001.fits, https://heasarc.gsfc.nasa.gov/FTP/fermi/data/lat/weekly/photon/
- License: LicenseRef-NASA-SMD-Open-Data
- License evidence: https://fermi.gsfc.nasa.gov/ssc/data/policy/
- License quote: Since the beginning of the second year of operations, all LAT science data has been released as early as possible, typically within a day or two of acquisition. The LAT public archive includes the science data acquired in the first year that was initially proprietary. (Same NASA SMD open-data basis as accepted HEASARC recipes.)
- Natural record: One weekly photon FITS file (EVENTS BINTABLE): ~2.05 million photons for week 800 (NAXIS2=2051003), one sample per week per field
- Estimated samples: 10
- Estimated primary values: 100,000,000
- Estimated download bytes: 2,000,000,000
- Estimated primary bytes: 400,000,000
- Decode path: curl ~10 evenly spaced weekly files (w009..w958 listed; ~200 MB each); pure-stdlib FITS: read 2880-byte header blocks, locate EVENTS BINTABLE (NAXIS1=98, TFORM1-9 'E'), slice big-endian float32 columns ENERGY (offset 0), RA (4), DEC (8), THETA (20), PHI (24) per row, struct-unpack '>f' and repack '<f'. Primary series: ENERGY plus direction/angle fields as separate series.
- Novelty kind: new_quantity
- Measurement type: photon_event_attributes
- Instrument line: fermi_lat
- Archive collection: heasarc.gsfc.nasa.gov/FTP/fermi/data/lat/weekly
- Novelty evidence: novelty.py --url heasarc .../lat/weekly/photon/ --terms 'fermi lat' lat_photon 'photon energy': only same-host hits (NICER u8/i16, SDO AIA) and NICER PI (integer energy channel, X-ray, 16-bit). fermi_gbm_tte_nai_photon_arrival_times_f64 is a different instrument (GBM) and quantity (arrival time, f64). No float32 photon energy or photon direction family anywhere locally or downstream.
- Homogeneity: Single instrument, single event reconstruction (P305), fixed column definitions; each field is its own series with one unit. Weekly files are uniform all-sky survey exposures.
- Risks: HEASARC host already has 3-4 accepted recipes (NICER x2, BATSE, Fermi GBM), so acceptance likely waits for user sign-off under the same-host rule. Few, large natural records (~10 weeks) — sample count is at the low end; more weeks raise download (~200 MB each). Outside this round's focus domains. RA/DEC of photons may be near-uniform noise-like floats.
- Probe evidence: Directory listing shows 949 weekly files w009..w958 (lat_photon_weekly_wNNN_p305_v001.fits). HEAD w800: HTTP 200, Content-Length 201,029,760. Range GET 0-40,000: EVENTS BINTABLE NAXIS1=98, NAXIS2=2,051,003; TTYPE1 ENERGY 'E' MeV, RA/DEC/L/B/THETA/PHI/ZENITH_ANGLE/EARTH_AZIMUTH_ANGLE 'E' deg, TIME 'D', EVENT_ID 'J', ...

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_32bit/scout.20261008_162828.jsonl`).
