# Cassini RPWS Wideband Receiver (WBR) Full-Resolution 10-kHz-Mode Ex-Dipole Plasma-Wave Waveforms (native 8-bit DN, 36 us sampling) UInt8

- Candidate id: `nasa_pds_cassini_rpws_wbr_10khz_waveform_u8`
- Width: uint8
- Quantity: Uncalibrated 8-bit waveform data numbers of the electric-field potential at the RPWS preamp input (Ex dipole), 10-kHz baseband mode (0.06-10.5 kHz, 36 microsecond sampling). Zero amplitude is nominally 127.5. These are the audio-band plasma-wave and radio-emission waveforms behind the 'sounds of Saturn'.
- Source: https://space.physics.uiowa.edu/pds/CORPWS_0121/CATALOG/WBFULLDS.CAT
- Resources: https://space.physics.uiowa.edu/pds/, https://space.physics.uiowa.edu/pds/CORPWS_0121/DATA/RPWS_WIDEBAND_FULL/T20083XX/T2008352/, https://space.physics.uiowa.edu/pds/CORPWS_0121/LABEL/RPWS_WBR_WFR_ROW_PREFIX.FMT, https://space.physics.uiowa.edu/pds/CORPWS_0121/DATA/RPWS_WIDEBAND_FULL/T20083XX/T2008350/T2008350_09_10025KHZ4_WBRFR.LBL
- License: NASA SMD open scientific data policy (NASA PDS public data, data set CO-V/E/J/S/SS-RPWS-2-REFDR-WBRFULL-V1.0)
- License evidence: https://science.nasa.gov/researchers/science-data/science-information-policy/
- License quote: It is Science Mission Directorate (SMD) policy, consistent with NASA and Federal policies, that information produced from SMD-funded scientific research activities be made publicly available.
- Natural record: One archived hourly WBR product file (T<yyyyddd>_<hh>_10KHZ<n>_WBRFR.DAT) for the 10-kHz baseband mode. Inside it are fixed-length records: a 32-byte big-endian row prefix (RECORD_BYTES@13, SAMPLES@15, FREQUENCY_BAND@21, GAIN@22, ANTENNA@23, AGC@24) followed by up to 4096 uint8 samples. Recommended sample: the valid samples of every record with ANTENNA==0 (Ex) and the 10-kHz band, in file order, one sample per product file. The alternative is one sample per capture record (2048-4096 values each, which also clears the 1,000-value median).
- Estimated samples: 120
- Estimated primary values: 250,000,000
- Estimated download bytes: 270,000,000
- Estimated primary bytes: 250,000,000
- Decode path: curl the .DAT/.LBL pairs from the CORPWS_xxxx volumes (Apache directory listings, anonymous HTTPS). Parse with Python struct: '>HH' at offset 12 gives record bytes and valid sample count; bytes 20-23 give band, gain and antenna; samples are bytes[32:32+SAMPLES] as uint8, kept verbatim. Check the label: DATA_TYPE=UNSIGNED_INTEGER, ITEM_BYTES=1, OFFSET=-127.5, and SAMPLING_PARAMETER_INTERVAL equal to the 10-kHz value (3.6E-5). Pure stdlib.
- Novelty kind: new_modality
- Measurement type: plasma_wave_waveform
- Instrument line: cassini_rpws_wbr
- Archive collection: space.physics.uiowa.edu/pds
- Novelty evidence: novelty.py --url .../RPWS_WIDEBAND_FULL/ --terms rpws wideband plasma: no URL match and no registry, ledger or downstream match. No plasma-wave or space-physics waveform family exists at any width (the vocabulary has interplanetary_magnetic_field f32 and orbital_magnetometer f64, both derived low-rate vectors). The novelty.py --type plasma_wave_waveform query returned 0. The 8-bit audio families (fsdd_pcm_u8 speech, asterisk mu-law speech) are terrestrial voice; these are AGC-ranged broadband plasma noise with whistler, chorus and electron-plasma-frequency tones.
- Homogeneity: One instrument (Cassini RPWS WBR), one mode (10-kHz baseband, 36 us sampling), one antenna (Ex dipole, header ANTENNA==0), one unit (uncalibrated DN, offset 127.5). Exclude the 75-kHz baseband files (75KHZ), the frequency-translated HF files (2025KHZ, 10025KHZ…) and any record whose antenna is Bx, Ew, LP or HF. Gain steps from the AGC are part of the instrument's native regime; keep GAIN and AGC as auxiliary per record if wanted. Spread the hourly files over several Saturn-tour volumes.
- Risks: (1) Filename digits after KHZ are not the antenna code, so filter on the per-record ANTENNA byte and verify. (2) Possible byte-level similarity to fsdd_pcm_u8 (also unsigned 8-bit waveforms centred near 128), though plasma noise has very different spectra and amplitude statistics. (3) Some hourly 10-kHz files are tiny (6 KB) and some are large (68 MB). Pick a deterministic bounded list, e.g. files of at least 1 MB from evenly spaced days, and cap the total. (4) The license basis is the NASA SMD policy, the same as the accepted Magellan, GRAIL and Mastcam-Z recipes; the U. Iowa server is the RPWS PDS data node.
- Probe evidence: Directory listings for CORPWS_0121/DATA/RPWS_WIDEBAND_FULL/T20083XX/T2008350 and T2008352 are live and show hourly 10KHZ files of 1.3-68 MB. Labels give RECORD_BYTES=4128, 4096 one-byte UNSIGNED_INTEGER samples, OFFSET -127.5 and VALID 0-255. A range GET (206, 8,256 bytes) of two records from T2008350_09_10025KHZ4_WBRFR.DAT decoded with '>HH' at 12 to record_bytes=4128 and samples=4096. Values were 90-169 with 72-78 distinct levels and a clear oscillation (e.g. 147,146,112,105,152,158,103,104…). The row-prefix FMT documents the antenna codes (0=Ex … 8=HF).

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_8bit/scout.20261008_230754.jsonl`).
