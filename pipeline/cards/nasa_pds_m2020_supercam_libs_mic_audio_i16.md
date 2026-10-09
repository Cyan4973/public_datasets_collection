# Mars 2020 SuperCam Microphone Raw Audio Recordings on Mars (LIBS Shot Sequences), Native 16-bit PCM (PDS4 FITS SOUND Table)

- Candidate id: `nasa_pds_m2020_supercam_libs_mic_audio_i16`
- Width: int16
- Quantity: Raw 16-bit microphone samples (SignedMSB2 stored, value_offset 32768) recorded by the SuperCam microphone on the Perseverance mast in the Martian atmosphere, mostly laser-induced breakdown shock waves plus wind/ambient sound
- Source: https://pds-geosciences.wustl.edu/m2020/urn-nasa-pds-mars2020_supercam/data_raw_audio/
- Resources: https://pds-geosciences.wustl.edu/m2020/urn-nasa-pds-mars2020_supercam/data_raw_audio/collection_data_raw_audio_inventory.csv, https://pds-geosciences.wustl.edu/m2020/urn-nasa-pds-mars2020_supercam/data_raw_audio/sol_00100/LS__0100_0675819581_368EA2__0040218SCAM02100_001_LUJ04.xml, https://pds-geosciences.wustl.edu/m2020/urn-nasa-pds-mars2020_supercam/data_raw_audio/sol_00100/LS__0100_0675819581_368EA2__0040218SCAM02100_001_LUJ04.fits
- License: NASA SMD open scientific data policy (NASA PDS Geosciences Node, Mars 2020 SuperCam bundle)
- License evidence: https://science.nasa.gov/researchers/science-data/science-information-policy/
- License quote: It is Science Mission Directorate (SMD) policy, consistent with NASA and Federal policies, that information produced from SMD-funded scientific research activities be made publicly available.
- Natural record: One raw-audio PDS4 product (LS__<sol>_<sclk>...fits): the SOUND binary-table HDU (TFORM 'I', TZERO 32768) holding one microphone recording. Restrict to the dominant configuration, products of 604,800 bytes (~246,240 samples, one LIBS burst recording), so sampling setup and duration are uniform. One sample per product.
- Estimated samples: 600
- Estimated primary values: 148,000,000
- Estimated download bytes: 365,000,000
- Estimated primary bytes: 296,000,000
- Decode path: Pure stdlib FITS: walk 2880-byte header blocks across HDUs to EXTNAME='SOUND' (or use the PDS4 XML Table_Binary offset and records), read NAXIS2 big-endian int16 values and write them little-endian as stored two's-complement PCM (physical = stored + 32768, documented). Discover products from the 13,420-line inventory CSV plus per-sol directory listings with sizes.
- Novelty kind: new_source
- Measurement type: pcm_audio
- Instrument line: Mars 2020 SuperCam microphone
- Archive collection: pds-geosciences.wustl.edu/m2020
- Novelty evidence: novelty.py --url .../data_raw_audio/ is 'same host only' (other PDS Geosciences recipes: MOLA, SHARAD, LOLA, gravity). The term 'supercam' has no hits. The only Mars 2020 recipe is Mastcam-Z frames. pcm_audio exists at 16-bit (LibriSpeech, ESC-50, bat calls, piano, MIMII valves, NSynth) but all are terrestrial. This is the first extraterrestrial acoustic recording: thin CO2 atmosphere, ~6 hPa, strong high-frequency attenuation, and LIBS shock waves.
- Homogeneity: One microphone (SuperCam MIC, Perseverance mast), one product type (raw audio, LS__), one size/duration class (604,800-byte products = same sample count, i.e. the same LIBS recording setup). The 8.46 MB long recordings and other odd-length classes are excluded so sampling rate and mode do not mix.
- Risks: Sampling rate is not in the SOUND HDU header. The builder must confirm from the ODL label table that the 604,800-byte class shares one rate (expected 100 kHz LIBS mode) or filter on the ODL keyword. Mars audio is very quiet, mostly noise plus periodic clicks, so it may look compressible. zlsim could find it near other 16-bit PCM families, the main rejection risk, though the spectra and click statistics are unusual. SuperCam is a LANL/CNES instrument, but the archive is the NASA PDS bundle with no stated restriction.
- Probe evidence: The bundle listing returns 200 with collections data_raw_audio, data_calibrated_audio etc. The inventory CSV (1.5 MB, fetched) lists 13,420 raw-audio products, all ls__. The PDS4 XML (fetched) shows Table_Binary 'SOUND TABLE' with records=4175000, SignedMSB2, value_offset 32768 for an 8.46 MB product. A 2,880-byte range GET of its SOUND HDU header shows XTENSION BINTABLE, NAXIS2=4175000, TFORM1='I', TZERO1=32768. Per-sol listings for sols 140-755 show 604,800-byte products dominant (7-25 per sol). A one-byte range GET returned 206.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_16bit/scout.20261009_010213.jsonl`).
