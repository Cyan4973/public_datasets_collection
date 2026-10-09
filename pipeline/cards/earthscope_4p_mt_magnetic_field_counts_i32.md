# NSF EarthScope USArray Magnetotelluric Transportable Array (4P) NIMS Fluxgate Magnetic-Field Time Series (LFN/LFE/LFZ, 1 sps), Native Int32 miniSEED

- Candidate id: `earthscope_4p_mt_magnetic_field_counts_i32`
- Width: int32
- Quantity: Long-period MT fluxgate magnetometer field components in counts (~100.9 counts/nT; horizontal ~2.27e6 counts = ~22,500 nT), 1 sample/s over ~3-week station deployments
- Source: https://doi.org/10.7914/SN/4P_2006
- Resources: https://service.iris.edu/fdsnws/dataselect/1/query?net=4P&sta=ALW48&cha=LFN&start=2015-06-20T00:00:00&end=2015-06-20T00:10:00, https://service.iris.edu/fdsnws/station/1/query?net=4P&cha=LFN&level=channel&format=text
- License: CC-BY-4.0
- License evidence: https://doi.org/10.7914/SN/4P_2006
- License quote: DataCite rightsList for 10.7914/SN/4P_2006 (NSF EarthScope MT-TA): 'Creative Commons Attribution 4.0 International' (rightsIdentifier cc-by-4.0); EarthScope data-license page: 'all data originating from EarthScope operated facilities will be licensed under the Creative Commons Attribution 4.0 International License (CC BY 4.0).'
- Natural record: One station-channel deployment epoch (fdsnws station epoch, typically ~3 weeks, ~1.8M samples at 1 sps)
- Estimated samples: 60
- Estimated primary values: 108,000,000
- Estimated download bytes: 200,000,000
- Estimated primary bytes: 432,000,000
- Decode path: curl fdsnws dataselect per channel epoch (start/end from the station service text). miniSEED 4096-byte records, blockette 1000 encoding 11 (Steim2). Pure-Python Steim2 decoder validated in the probe (601 decoded samples; last value 2271368 equals the reverse-integration constant). Emit int32 in time order per epoch, gap-split.
- Novelty kind: new_modality
- Measurement type: ground_magnetometer
- Instrument line: nims_mt_fluxgate
- Archive collection: service.iris.edu/fdsnws/dataselect:4P
- Novelty evidence: novelty.py: no recipe, registry, ledger or downstream match for magnetotelluric/NIMS/MT-TA. ground_magnetometer has only usgs_geomag_observatory_minute_f32 (float32 minute values, a different byte representation and cadence). Same host as baseline seismic_waveform_i32, but a different instrument and quantity (fluxgate B-field counts with a large DC offset and slow geomagnetic variation, not zero-mean seismic velocity).
- Homogeneity: Magnetic channels only (LFN, LFE, LFZ), same NIMS instrument and gain (~100.9 counts/nT), 1 sps. Exclude electric-field LQN/LQE (different unit, mV/km). Pick ~20 stations x 3 components from the 4P network (1163 stations) only, not other MT networks with different loggers.
- Risks: Same host as the PB strainmeter candidate (2 this round). The Z component has a larger offset than the horizontals but the same unit and gain. NIMS data can contain spikes or resets. Total primary is ~430 MB at 60 samples; the builder could take 40-60 epochs to stay comfortably under 1 GB.
- Probe evidence: fdsnws station net=4P cha=LFN: 1682 channel epochs (NIMS, scale 100.9048 counts/nT, 1 sps), e.g. ALW48 2015-06-18..2015-07-09. dataselect 10 min ALW48 LFN: HTTP 200, 4096 bytes, enc=11 Steim2, 601 samples decoded: 2271241..2271368. DataCite JSON for the DOI returned rightsList cc-by-4.0.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_32bit/scout.20261008_183620.jsonl`).
