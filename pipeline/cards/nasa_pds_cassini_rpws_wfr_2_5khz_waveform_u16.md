# Cassini RPWS Waveform Receiver (WFR) Full-Resolution 2.5-kHz-Band Single-Channel Plasma-Wave Waveforms, Native 12-bit DN as UInt16

- Candidate id: `nasa_pds_cassini_rpws_wfr_2_5khz_waveform_u16`
- Width: uint16
- Quantity: Uncalibrated 12-bit waveform-receiver samples (0-4095, zero amplitude at 2047.5) of the electric/magnetic wave field measured by Cassini RPWS WFR in the 2.5 kHz band (140 us sampling), 512-sample captures
- Source: https://space.physics.uiowa.edu/pds/
- Resources: https://space.physics.uiowa.edu/pds/CORPWS_0130/DATA/RPWS_WAVEFORM_FULL/T20091XX/T2009164/T2009164_2_5KHZ1_WFRFR.DAT, https://space.physics.uiowa.edu/pds/CORPWS_0130/DATA/RPWS_WAVEFORM_FULL/T20091XX/T2009164/T2009164_2_5KHZ1_WFRFR.LBL, https://space.physics.uiowa.edu/pds/CORPWS_0130/LABEL/RPWS_WBR_WFR_ROW_PREFIX.FMT
- License: NASA SMD open scientific data policy (NASA PDS archive, no use restriction)
- License evidence: https://science.nasa.gov/researchers/science-data/science-information-policy/
- License quote: It is Science Mission Directorate (SMD) policy, consistent with NASA and Federal policies, that information produced from SMD-funded scientific research activities be made publicly available.
- Natural record: One daily PDS product T<yyyyddd>_2_5KHZ1_WFRFR.DAT (data set CO-V/E/J/S/SS-RPWS-2-REFDR-WFRFULL-V1.0): fixed 1056-byte records = 32-byte row prefix + 512 MSB uint16 samples. The sample is the valid (VALIDITY/SUSPECT flags clear), single antenna (ANTENNA byte 23 = 0, Ex, or the documented dominant antenna), FREQUENCY_BAND = 2.5 kHz records of that day, concatenated in file order.
- Estimated samples: 100
- Estimated primary values: 110,000,000
- Estimated download bytes: 250,000,000
- Estimated primary bytes: 220,000,000
- Decode path: Pure stdlib: parse the PDS3 .LBL (RECORD_BYTES, FILE_RECORDS), read the .DAT in 1056-byte records with struct; decode the 32-byte prefix per RPWS_WBR_WFR_ROW_PREFIX.FMT (byte 21 FREQUENCY_BAND, 22 GAIN, 23 ANTENNA, 19-20 validity/status bits, 15-16 SAMPLES); take the samples as '>512H' and write little-endian uint16. Reject values >4095.
- Novelty kind: new_quantity
- Measurement type: plasma_wave_waveform
- Instrument line: Cassini RPWS Waveform Receiver (WFR)
- Archive collection: space.physics.uiowa.edu/pds (RPWS PDS node)
- Novelty evidence: novelty.py --url .../RPWS_WAVEFORM_FULL/ only matches the accepted nasa_pds_cassini_rpws_wbr_10khz_waveform_u8 at the volume level. That recipe ingests the different WBRFULL products (Wideband Receiver, 8-bit). WFRFULL files are a separate receiver and data set with 12-bit samples, never ingested. The measurement type plasma_wave_waveform has no 16-bit member, and no downstream 16-bit family covers space-plasma waveforms. 'WFRFULL' and 'waveform receiver' have no term hits in recipes, registry or ledger.
- Homogeneity: One instrument (RPWS WFR), one band (2.5 kHz, 140 us), one channel mode (the '1' single-channel daily files, not the 4/5-channel '_2_5KHZ4' files), one antenna (filter on the ANTENNA byte), one 12-bit offset-binary lattice. Gain varies (WALSH_DGF/ANALOG_GAIN) as in any AGC receiver, the same situation as the accepted WBR recipe. The 25 Hz band and multi-channel files are excluded.
- Risks: Some '1' files may mix antennas or contain few records for the chosen antenna. The builder must pick the antenna from prefix statistics and drop days with under ~1000 captures. Same instrument and archive as the accepted WBR u8 family: the judge may view it as 'same instrument, other width', though it is a different receiver product and file set. Waveforms near zero amplitude with low gain may be low-entropy. Prefix bit-field layout must be validated on synthetic records.
- Probe evidence: Directory listings of CORPWS_0130/DATA/RPWS_WAVEFORM_FULL/T20091XX/ show daily _2_5KHZ1_WFRFR.DAT files of 1.2-6.5 MB on 11 of 12 surveyed days. The label (fetched) gives RECORD_BYTES=1056, FILE_RECORDS=2425, WFR_SAMPLE MSB_UNSIGNED_INTEGER ITEMS=512 ITEM_BYTES=2, VALID 0-4095, OFFSET -2047.5, SAMPLING_PARAMETER_INTERVAL 0.000140. The ROW_PREFIX FMT (fetched) documents the ANTENNA codes. A one-byte range GET on the .DAT returned 206.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_16bit/scout.20261009_010213.jsonl`).
