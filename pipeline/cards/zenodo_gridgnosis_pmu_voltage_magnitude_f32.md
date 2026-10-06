# GridGnosis Cyprus Transmission-System PMU Three-Phase Voltage Phasor Magnitudes (50 frames/s) Float32

- Candidate id: `zenodo_gridgnosis_pmu_voltage_magnitude_f32`
- Width: float32
- Quantity: Per-phase voltage phasor magnitudes (volts, phase-to-ground, about 77 kV on 132 kV lines) for every line monitored by 6 phasor measurement units in the Cyprus transmission system, reported at 50 frames per second.
- Source: https://zenodo.org/records/20308780
- Resources: https://zenodo.org/api/records/20308780/files/Steady%20state%20data.zip/content, https://zenodo.org/records/17648863
- License: CC-BY-4.0
- License evidence: https://zenodo.org/records/20308780
- License quote: Zenodo record metadata license: {'id': 'cc-by-4.0'} for 'PMU data from the GridGnosis project' ('This dataset includes PMU data recorded from the Cyprus transmission system through the GridGnosis platform...').
- Natural record: One PMU one-hour steady-state CSV (e.g. PMU_3_20260514_170200_20260514_180200.csv, about 180,000 frames). Emit its Mag_V{A,B,C}_<pmu>_<line> columns as a frames x channels float32 matrix. Current magnitudes, angles, Frequency and Dfrequency are excluded or auxiliary.
- Estimated samples: 18
- Estimated primary values: 49,000,000
- Estimated download bytes: 894,457,235
- Estimated primary bytes: 196,000,000
- Decode path: Download the zip (or range-fetch its 18 deflated CSV members via the central directory, skipping __MACOSX entries). zlib raw inflate, csv module, struct.pack('<f'). Values print with 8 significant digits (77372.172, -63.15921, 49.979588), consistent with float32 IEEE phasor frames. The builder should verify that each token re-prints identically from its nearest float32.
- Novelty kind: new_modality
- Novelty evidence: novelty.py --url https://zenodo.org/records/20308780 --terms pmu synchrophasor gridgnosis phasor: no URL match beyond the Zenodo host, and no recipe, registry, ledger or downstream term matches. No synchrophasor or PMU material exists at any width locally or downstream.
- Homogeneity: Voltage magnitudes only (one unit, one nominal level, one PMU network and frame rate). Do not mix current magnitudes (about 13-120 A), phase angles (-180..180 deg) or frequency. If any PMU sits at a different nominal voltage level, drop it or document it. Steady-state hours only; the event zips (frequency events 21.7 MB, voltage events 4.9 MB) are a different regime.
- Risks: Only 18 natural records (6 PMUs x 3 one-hour windows), below the soft 20-sample target. The sibling GridEye record 17648863 (CC BY 4.0, 202 MB steady-state zip, same TSO) could add records but must be checked for compatibility. Channel count varies by PMU: PMU_3 has 15 voltage-magnitude columns of 62; others are unverified because Zenodo returned 503 during later probes. 8-digit prints may not round-trip for every float32. Published 2026-05-20, recent; pin the record and sizes.
- Probe evidence: Steady state data.zip (894,457,235 B) central directory via range GET: 50 entries, 18 CSVs of 55-162 MB each (2,162,574,636 B uncompressed), names PMU_{1..6}_2026050{5,6}/20260514_hhmmss_... Range-fetched and inflated the first 300 KB of the PMU_3 file. Header 'Date_Time,Mag_VA_3_21,Angle_VA_3_21,...,Frequency,Dfrequency' (62 columns), 20 ms frame spacing, first row '2026-05-14 14:02:00.000000,77372.172,-63.15921,77175.977,...,49.979588,-0.022154542'.

Proposed by the autocollect scout on 2026-10-06 (transcript `.data/pipeline/logs/scout_32bit/scout.20261005_234311.jsonl`).
