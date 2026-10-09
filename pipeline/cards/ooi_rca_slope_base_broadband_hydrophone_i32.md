# OOI Regional Cabled Array Slope Base (RS01SLBS) Broadband Hydrophone HYDBBA102 64 kHz Raw Acoustic Pressure Counts, Native Int32 (Steim2 miniSEED)

- Candidate id: `ooi_rca_slope_base_broadband_hydrophone_i32`
- Width: int32
- Quantity: Raw digitizer counts of underwater acoustic pressure from an icListen HF broadband hydrophone at 64,000 samples/s on the Cascadia Margin seafloor (OO.HYVM1..YDH), decoded from Steim2-compressed miniSEED to int32
- Source: https://rawdata.oceanobservatories.org/files/RS01SLBS/LJ01A/HYDBBA102/
- Resources: https://rawdata.oceanobservatories.org/files/RS01SLBS/LJ01A/HYDBBA102/2019/06/01/, https://rawdata.oceanobservatories.org/files/RS01SLBS/LJ01A/HYDBBA102/2019/06/01/OO-HYVM1--YDH-2019-06-01T00:00:00.000000.mseed
- License: OOI open data (attribution: acknowledge OOI and NSF)
- License evidence: https://oceanobservatories.org/how-to-use-acknowledge-and-cite-data/
- License quote: All OOI data are freely available to everyone who has an Internet connection. The only requirement for use of OOI data is to acknowledge OOI as its source, provide citations where appropriate, and include acknowledgment of the US National Science Foundation's support.
- Natural record: One 5-minute miniSEED file, a contiguous 64 kHz trace of about 19.2M samples
- Estimated samples: 12
- Estimated primary values: 230,000,000
- Estimated download bytes: 340,000,000
- Estimated primary bytes: 920,000,000
- Decode path: curl about 12 five-minute .mseed files (about 28 MB each) spread across 2016-2022 from the Apache directory listings; pin by size. Parse 4096-byte big-endian miniSEED 2 records (blockette 1000 encoding 11 = Steim2, blockette 100 rate 64000) and decode Steim2 frames in pure Python into int32. Check the reverse-integration constant per record. This is the same codec family as the IRIS/EarthScope int32 recipes.
- Novelty kind: new_modality
- Measurement type: underwater_acoustic_pressure
- Instrument line: ocean_sonics_iclisten_hf_hydrophone
- Archive collection: rawdata.oceanobservatories.org
- Novelty evidence: novelty.py --url https://rawdata.oceanobservatories.org --terms hydrophone ooi: no URL match. The only hydrophone recipe is mbari_mars_hydrophone_hmd_psd_f32, a derived spectral-density product, not a waveform. pcm_audio families are airborne audio; seismic_waveform_i32 is broadband seismometer counts at much lower rates. --type underwater_acoustic_pressure: 0 families.
- Homogeneity: One hydrophone (HYDBBA102 at Slope Base, OO.HYVM1..YDH), one sample rate (64 kHz), one encoding, raw counts, 5-minute files. Do not mix the other RCA hydrophones (Axial, Oregon Offshore) or the 2023+ daily tar.bz2 packaging.
- Risks: Each sample is large (about 77 MB int32), so about 12 samples fill the 1 GB cap; the count is lower than the guidance but bounded by the cap. Pure-Python Steim2 over about 230M samples may take tens of minutes. Possible byte-gate proximity to seismic_waveform_i32 or the queued EarthScope int32 miniSEED families, though 64 kHz broadband ocean noise has very different spectral and delta statistics. Files after 2022 are daily tar.bz2 bundles (763 MB) and should be avoided.
- Probe evidence: The directory listing for 2019/06/01 has 299 .mseed files, each 28-29 MB. A one-byte range GET returned 206. An 8 KB range parse showed station HYVM1, channel YDH, network OO, blockettes 1000/100/1001, encoding byte 11 (Steim2), record length 2^12, 2682 samples per record, and blockette 100 rate 64000 (float 'Gz\x00\x00'). The year listing spans 2015-2026.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_32bit/scout.20261008_225934.jsonl`).
