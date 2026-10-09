# EarthScope/PBO Gladwin Tensor Borehole Strainmeter Raw Gauge Counts (PB network LS1-LS4, 1 sps), Native Int32 miniSEED

- Candidate id: `earthscope_pb_borehole_strain_counts_i32`
- Width: int32
- Quantity: Raw gauge displacement counts of the 4 horizontal extensometer gauges (LS1..LS4) of Gladwin tensor strainmeters, 1 sample/s, values ~4.7e7 counts (~26 bits)
- Source: https://www.fdsn.org/networks/detail/PB/
- Resources: https://service.iris.edu/fdsnws/dataselect/1/query?net=PB&sta=B004&cha=LS1&start=2015-06-20T00:00:00&end=2015-06-20T01:00:00, https://service.iris.edu/fdsnws/station/1/query?net=PB&cha=LS?&level=channel&format=text
- License: CC-BY-4.0 (all data originating from EarthScope-operated facilities)
- License evidence: https://www.unavco.org/data/policies_forms/data-policy/data-license.html
- License quote: Effective immediately, all data originating from EarthScope operated facilities will be licensed under the Creative Commons Attribution 4.0 International License (CC BY 4.0).
- Natural record: One gauge-channel x UTC day (standard SDS day-volume archive unit): 86,400 int32 counts per sample
- Estimated samples: 480
- Estimated primary values: 41,000,000
- Estimated download bytes: 80,000,000
- Estimated primary bytes: 166,000,000
- Decode path: curl fdsnws dataselect miniSEED (512-byte records, blockette 1000 encoding 11 = Steim2, big-endian). Pure-Python Steim2 frame decoder (validated in this probe on MT data: reconstructed last sample equals the frame's reverse-integration constant). Concatenate records for one channel-day in time order; split at gaps or emit gap-free days only.
- Novelty kind: new_modality
- Measurement type: borehole_strain
- Instrument line: gladwin_tensor_strainmeter
- Archive collection: service.iris.edu/fdsnws/dataselect:PB
- Novelty evidence: novelty.py: no recipe, registry, ledger or downstream match for strainmeter/Gladwin/borehole strain. --type borehole_strain shows 0 families. Same host as seismic_waveform_i32 (baseline; it used the now-retired irisws/timeseries service), but this is a different physical quantity and instrument (tidal-strain gauge counts with a huge DC offset and smooth tidal and barometric signal, unlike zero-mean seismometer counts).
- Homogeneity: One instrument class (Gladwin GTSM), one channel family (LS1-LS4, 1 sps, counts), one unit. Station offsets differ but scale and lattice (integer counts) are the same. Do not mix in 20 sps BS? channels, pore-pressure or other auxiliary channels.
- Risks: 2nd candidate this round on service.iris.edu (with MT), so the host's 3rd acceptance needs sign-off. Gauge resets and offsets cause occasional steps. Some stations have gaps, so prefer gap-free days. Byte-level similarity to seismic_waveform_i32 is judged unlikely but unmeasured.
- Probe evidence: fdsnws station: 84 LS1 channel epochs in PB (Gladwin Tensor Strainmeter, 1.0 sps). dataselect 1 h B004 LS1 2015-06-20: HTTP 200, 3584 bytes, 512-byte records, encoding 11 (Steim2), first record 721 samples, first values 46965675, 46965654. UNAVCO data-license page re-read 2026-10-08.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_32bit/scout.20261008_183620.jsonl`).
