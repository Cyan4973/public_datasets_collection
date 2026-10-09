# Apollo Passive Seismic Experiment (ALSEP, FDSN XA 1969-1977) Long-Period Vertical (MHZ) Lunar Seismograms, Native 10-bit Digital Units as Int16 (Nunn et al. 2022 archive)

- Candidate id: `earthscope_xa_apollo_pse_lunar_seismogram_i16`
- Width: int16
- Quantity: Raw digital output of the Apollo PSE long-period vertical seismometer at 6.625 samples/s, 10-bit digital units (0..1023). -1 marks gaps or invalid frames in the restored archive.
- Source: https://www.fdsn.org/networks/detail/XA_1969/
- Resources: https://service.earthscope.org/fdsnws/station/1/query?net=XA&starttime=1969-07-01&endtime=1977-12-31&level=channel&format=text, https://service.earthscope.org/fdsnws/dataselect/1/query?net=XA&sta=S15&cha=MHZ&loc=*&starttime=1973-06-10T00:00:00&endtime=1973-06-11T00:00:00
- License: NASA SMD open scientific data (US Government / NASA Apollo mission data, publicly available without restriction)
- License evidence: https://science.nasa.gov/researchers/science-data/science-information-policy/
- License quote: It is Science Mission Directorate (SMD) policy, consistent with NASA and Federal policies, that information produced from SMD-funded scientific research activities be made publicly available.
- Natural record: One station-channel-day of the MHZ long-period vertical stream (SEED day boundary). A complete day is about 572,400 samples, about 1.14 MB as int16.
- Estimated samples: 120
- Estimated primary values: 68,000,000
- Estimated download bytes: 43,000,000
- Estimated primary bytes: 137,000,000
- Decode path: curl the FDSN dataselect miniSEED for one station-day (anonymous, nodata=404). Decode the 4096-byte miniSEED 2 records (blockette 1000 encoding 11 = Steim2) in pure Python; datasets/earthscope_pb_borehole_strain_counts_i32/scripts/mseed.py already decodes Steim and can serve as a model. Check the X0/Xn integrity words. Concatenate the records of the day in time order, keeping -1 gap markers as native values (or splitting at gaps, documented), and write little-endian int16 (range -1..1023 fits).
- Novelty kind: new_source
- Measurement type: inertial_vibration
- Instrument line: Apollo ALSEP Passive Seismic Experiment long-period seismometer (10-bit telemetry)
- Archive collection: EarthScope FDSN web services, network XA (1969) Apollo restored archive
- Novelty evidence: novelty.py --url .../dataselect/1/query?net=XA --terms apollo lunar seismometer matches only the shared EarthScope host path (PB strainmeters i32, 4P magnetotellurics i32 in staging), not network XA. The 'lunar' hits are LOLA, GRAIL and Clementine (different modalities). There is no seismogram family at 16 bits; inertial_vibration at 16 bits holds only Bosch CNC vibration, a honeybee accelerometer and GENEActiv wrist accelerometry. The 10-bit long-period lunar telemetry (very low entropy around a DC level, with tidal drift, moonquake bursts and telemetry glitches) differs statistically from all of them.
- Homogeneity: A single channel type: MHZ (long-period vertical, 6.625 sps, location 00) of one instrument design, the ALSEP PSE. Proposed stations are S12, S14, S15 and S16, about 30 days each spread over 1971-1977. One unit (10-bit DU) and one tick lattice throughout. Exclude SHZ (short-period, 53 sps), the horizontals MH1/MH2 and the ATT timing channel. If the screener prefers stricter homogeneity, restrict to S12 and S15 with 60 days each.
- Risks: The license rests on a NASA policy statement rather than a CC tag; DataCite for DOI 10.7914/SN/XA_1969 has an empty rightsList (the same policy basis accepted for IRIS and PDS recipes). The -1 gap fill can dominate on bad days, so the builder should skip days with large -1 fractions. Values are low-entropy, which is not a defect but should be noted. Days before 1971 hold only S12/S11, so sample across 1971-77. Steim2 decoder correctness must be self-tested.
- Probe evidence: The station service (200) lists XA S11/S12/S14/S15/S16 channels MHZ/MH1/MH2 at 6.625 sps, SHZ at 53 sps and ATT, described as 'Apollo PSE Alsep Seismometer'. A dataselect for S15 MHZ on 1973-06-10 returned 200 with 356,352 bytes (87 Steim2 records). A local pure-Python Steim2 decode gave 572,292 samples, range -1..1023, 275 distinct values, mode around 460. A 10-minute S12 probe returned 200 and 8,192 bytes, encoding 11, 4096-byte records.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_16bit/scout.20261008_225519.jsonl`).
