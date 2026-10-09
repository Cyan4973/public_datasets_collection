# ISIS Rapid Cycling Synchrotron Storage-Ring Coasting-Beam Experiment: Vertical BPM R8VM1 Electrode Voltages (E1/E2), 100 MHz TDMS Acquisitions, Float64

- Candidate id: `isis_rcs_coasting_beam_bpm_electrode_voltage_f64`
- Width: float64
- Quantity: Raw pickup-electrode voltage (V) of the sector-8 vertical beam position monitor (R8VM1, electrodes E1 and E2), sampled at 100 MS/s during transverse-instability tune scans of a coasting proton beam. The NI TDMS files store these natively as DBL (tdsTypeDoubleFloat, 0x0A).
- Source: https://zenodo.org/records/16940890
- Resources: https://zenodo.org/records/16940890/files/data.zip?download=1, https://zenodo.org/api/records/16940890/files/Readme.md/content, https://zenodo.org/api/records/16940890
- License: CC-BY-4.0
- License evidence: https://zenodo.org/api/records/16940890
- License quote: Zenodo record metadata: "license": {"id": "cc-by-4.0"} for 'Coasting Beam Experimental Data from ISIS Storage Ring' (2025-08-25).
- Natural record: One TDMS acquisition file (one tune setting, one 10 ms capture of 1,000,000 samples per channel). One sample = one electrode channel (R8VM1_E1 or R8VM1_E2) of one acquisition, 1,000,000 float64 values (8 MB).
- Estimated samples: 84
- Estimated primary values: 84,000,000
- Estimated download bytes: 210,000,000
- Estimated primary bytes: 672,000,000
- Decode path: data.zip (908 MB, 745 entries; zip64 extra fields present) holds about 181 .tdms acquisitions (coarse_sweep_1/2: 24/23, fine_sweep_1..6: 21 each, beam_off: 8), each 48,000,5xx bytes uncompressed and about 4.7 MB deflated. Get the member offsets from the central directory (one range GET of the last ~3 MB), then range-GET each selected member with curl and inflate with zlib (raw deflate, wbits=-15). TDMS layout: 28-byte lead-in 'TDSm', ToC 0x0E (metadata, new object list, raw data; not interleaved), one segment, raw-data offset 515. The object list holds 6 channels /'Data'/{BLMSum, R5IM_Divided, R5IM_Undivided, R9HM1_Diff, R8VM1_E1, R8VM1_E2}, each type 0x0A DBL, 1,000,000 values, contiguous. The channel at index k starts at raw offset 28+515+k*8,000,000 as little-endian float64. Suggested subset: E1 and E2 from fine_sweep_1 and fine_sweep_4 (the first repetition at each beam intensity), 42 files x 2 = 84 samples, about 672 MB, with the members pinned by name, offset, CRC and size.
- Novelty kind: new_modality
- Measurement type: accelerator_beam_diagnostics
- Instrument line: isis_rcs_r8vm1_bpm_ni_tdms_100mhz
- Archive collection: zenodo
- Novelty evidence: novelty.py --url https://zenodo.org/records/16940890 --terms 'coasting beam' ISIS tdms: same host only (Zenodo), no recipe, registry, ledger or downstream match. The only term hit is 'isis' inside the unrelated NAIF MRO recipe (USGS ISIS kernels mirror). novelty.py --type accelerator_beam_diagnostics: 0 recipes. The vocabulary has no accelerator beam-instrumentation family at any width. The nearest types are oscilloscope_trace (zenodo_lecroy_oscilloscope_i16, 16-bit) and grid_point_on_wave.
- Homogeneity: One machine (ISIS RCS in storage-ring mode), one experiment campaign, one BPM (R8VM1), one digitizer and sample rate (100 MHz), one unit (V). Only the two electrodes of the same monitor are primary. BLM sum, intensity-monitor and horizontal-BPM channels are different quantities and must not be mixed in (they could be auxiliary at most). Tune setting and the two beam intensities vary within the family, but the generation process and scale are the same.
- Risks: Width honesty: the values sit on a uniform digitizer lattice. The BLM channel probe shows 136 distinct values with step 0.002786630765 V over 550k samples, so the effective resolution is about 8-12 bits even though TDMS stores DBL natively. A screener may call this a hollow 64-bit family, and the byte gate may find it highly compressible. The counter-argument is that DBL is the instrument software's native typed storage, not a local widening. Lattice step and range for the R8VM1 channels were not probed directly (only channel 0 was inflated). Single campaign and single source, but there are 84 or more large natural samples. Zip members come from a macOS archive (ignore __MACOSX entries). Total population (~181 files x 2 electrodes x 8 MB, about 2.9 GB) exceeds the 1 GB cap, so a documented subset is required.
- Probe evidence: HEAD data.zip returned 200 with content-length 908,395,416. A range GET of the last 3 MB parsed the central directory (745 entries, 8.69 GB uncompressed). A range GET of 400 KB at member offset 268,246,989 (fine_sweep_1/set3_Qh_4331-Qv_3_790.tdms) inflated 4.4 MB of raw TDMS: lead-in TDSm, ToC 0xE, version 4713, next-segment 48,000,515, raw offset 515, 6 DBL channels x 1,000,000 values, first values -0.0384, -0.0356, ... V. The Readme confirms the 100 MHz sampling and the R8VM1 E1/E2 vertical BPM electrodes in V.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_64bit/scout.20261008_225019.jsonl`).
