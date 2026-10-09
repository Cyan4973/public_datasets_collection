# SDO/HMI Carrington-Rotation Synoptic Charts of Radial Photospheric Magnetic Flux Density (hmi.Synoptic_Mr_720s, 3600x1440), Native Float32

- Candidate id: `jsoc_hmi_synoptic_mr_carrington_f32`
- Width: float32
- Quantity: Radial photospheric magnetic flux density Br (Mx/cm^2, i.e. Gauss) on a 0.1 deg Carrington longitude x sine-latitude CEA grid; one full Carrington rotation per chart
- Source: http://jsoc.stanford.edu/data/hmi/synoptic/
- Resources: http://jsoc.stanford.edu/data/hmi/synoptic/hmi.Synoptic_Mr.2200.fits, http://jsoc.stanford.edu/data/hmi/synoptic/, http://jsoc.stanford.edu/data/hmi/synoptic/README.txt
- License: CC0 1.0 (declared in every FITS header; NASA SDO mission data)
- License evidence: http://jsoc.stanford.edu/data/hmi/synoptic/hmi.Synoptic_Mr.2200.fits
- License quote: FITS header card: LICENSE = 'LICENSE ' / CC0 1.0 (also NASA Science Data license page https://science.data.nasa.gov/about/license: 'data that is provided from a NASA-led mission ... are licensed as Creative Commons Zero')
- Natural record: One Carrington-rotation synoptic chart = one FITS primary image of 3600x1440 float32 (5,184,000 values)
- Estimated samples: 30
- Estimated primary values: 155,520,000
- Estimated download bytes: 622,400,000
- Estimated primary bytes: 622,080,000
- Decode path: Uncompressed FITS: primary HDU BITPIX=-32, NAXIS1=3600, NAXIS2=1440, data start at byte 8640 (3 header blocks; walk 2880-byte blocks to END). struct.unpack('>f') big-endian -> write little-endian float32. Missing pixels (MISSVALS ~47k/chart, polar) are NaN; builder decides keep-as-native vs mask. Download whole files with curl -C -.
- Novelty kind: new_quantity
- Measurement type: solar_magnetogram
- Instrument line: sdo_hmi
- Archive collection: jsoc.stanford.edu/data/hmi/synoptic
- Novelty evidence: novelty.py --url jsoc.stanford.edu/data/hmi/synoptic: only same-host match is the AIA synoptic EUV intensity recipe (nasa_sdo_aia_synoptic_i32, int32 RICE codes of EUV images). No magnetogram/magnetic-field-map family anywhere locally or downstream; --type solar_magnetogram returns 0. Different instrument (HMI vs AIA), different physical quantity (signed B field, heavy-tailed around 0 vs positive EUV counts), different width/representation (native float32 vs int32).
- Homogeneity: Single product series hmi.Synoptic_Mr_720s only (exclude Ml, Br/Bp/Bt vector, _small, _nrt, polfil). Same unit, grid, processing (CALVER64) across rotations. 220 rotations CR2096-2315 available; take ~30 evenly spaced across 2010-2026 for solar-cycle coverage.
- Risks: Third JSOC acceptance? No: AIA is the only prior from jsoc.stanford.edu. Values are mostly near-zero noise with a long active-region tail (RMS ~16 G, |max| ~2000 G); NaN fraction ~1% must be handled consistently by build and verify. HTTP (not HTTPS) host; JSOC occasionally slow. 1 GB cap means no more than ~45 charts.
- Probe evidence: Directory listing 200 OK (2422 entries; 220 hmi.Synoptic_Mr.CCCC.fits each 20,744,640 bytes). Range GET of bytes 0-8639 of hmi.Synoptic_Mr.2200.fits returned header: BITPIX=-32, NAXIS1=3600, NAXIS2=1440, BUNIT='Mx/cm^2', CONTENT='Carrington Synoptic Chart Of Br Field', TOTVALS=5184000, MISSVALS=47292, LICENSE=CC0 1.0.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_32bit/scout.20261008_164906.jsonl`).
