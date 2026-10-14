# OOI Endurance Oregon Offshore Shallow Profiler (CE04OSPS SF01B) WET Labs AC-S Hyperspectral Absorption/Attenuation Meter Raw Spectral Counts UInt16 (OPTAAD105, 2019)

- Candidate id: `ooi_ce04osps_optaa_acs_spectral_counts_u16`
- Width: uint16
- Quantity: Raw per-wavelength detector counts from the AC-S in-situ spectrophotometer: for each of 84 wavelengths (about 400-750 nm), c-reference, a-reference, c-signal and a-signal, as big-endian uint16 (observed 314..29,373). About 4 Hz packets during each profiler ascent.
- Source: https://rawdata.oceanobservatories.org/files/CE04OSPS/SF01B/OPTAAD105/
- Resources: https://rawdata.oceanobservatories.org/files/CE04OSPS/SF01B/OPTAAD105/2019/06/, https://rawdata.oceanobservatories.org/files/CE04OSPS/SF01B/OPTAAD105/2019/06/OPTAAD105_10.33.10.202_2101_20190601T0720_UTC.dat, https://oceanobservatories.org/wp-content/uploads/2024/01/1102-00010_Data_Use_Policy_OOI.pdf
- License: OOI Data Use Policy (LicenseRef-OOI-Data-Use-Policy; same as accepted ooi_ce02shbp_vel3d_adv_amplitude_correlation_u8)
- License evidence: https://oceanobservatories.org/wp-content/uploads/2024/01/1102-00010_Data_Use_Policy_OOI.pdf
- License quote: Data Use Policy section 4.1: 'all OOI data will be made publicly available, free of charge ... The User is granted the right to use OOI data and web sites for any legal and non-prohibited purpose whatsoever ... -- to access, link to and use, create derivative works, publish, distribute, disseminate, transfer, or copy.'
- Natural record: One daily raw PortAgent file (about 23 MB): the spectral counts of all valid AC-S packets in that file, about 32,000 packets × 336 values, in native packet order (per wavelength: cref, aref, csig, asig).
- Estimated samples: 16
- Estimated primary values: 175,000,000
- Estimated download bytes: 370,000,000
- Estimated primary bytes: 350,000,000
- Decode path: Pure stdlib. (1) Strip OOI PortAgent framing: sync a3 9d 7a, type u8, total length u16 BE, checksum u16, 8-byte timestamp, 16-byte header in all. Keep type-1 (instrument data) payloads and concatenate them into the serial stream (same approach as the accepted OOI VEL3D recipe). (2) Scan for AC-S registration ff 00 ff 00. Record length u16 BE at +4 (704). Number of wavelengths N at +31 (84). Then N×4 BE uint16 at +32. Checksum u16 = sum(bytes[0:len]) & 0xffff at +len. Keep only checksum-valid packets with the expected N.
- Novelty kind: new_modality
- Measurement type: insitu_optical_spectrometer_counts
- Instrument line: WET Labs (Sea-Bird) AC-S hyperspectral absorption/attenuation meter on OOI shallow profiler
- Archive collection: ooi_rawdata
- Novelty evidence: novelty.py --url: same host only (ooi_ce02shbp VEL3D u8, a different instrument and quantity). Terms 'AC-S', OPTAA and spectrophotometer have no recipe, registry, ledger or downstream hits ('attenuation' only matched unrelated CT/RSTN recipes). --type insitu_optical_spectrometer_counts and --archive ooi_rawdata return 0. No in-situ ocean optics family exists at any width; the nearest 16-bit spectral material is lab NIR hyperspectral cubes (venere), which have a different structure.
- Homogeneity: One instrument designator (OPTAAD105) at one site/node, one packet format, N=84 wavelengths in every probed file (Jan and Apr 2019). Restrict to one deployment window (Jan-Jun 2019 is well populated with 23-24 MB daily files) and assert constant N and serial across chosen days. Days are profiles of the same water column, so it is one regime.
- Risks: (1) Some packets fail the checksum (52/67 valid in the 64 KB probe; some are probably boundary-truncated), so drop invalid ones. (2) The 4-channel interleave per wavelength is native but mixes reference and signal levels; it could instead be split into 4 series if a judge prefers. (3) Late-2019 months are sparse (instrument gaps), so pin dates. (4) The serial-number byte offset was not confirmed (the field read as 000080); rely on N and the date window. (5) The OOI policy is not SPDX but was accepted before.
- Probe evidence: Directory listing live (2014-2020 years; 2019/06 daily files of 23-24 MB). 64 KB range GET of 20190601: 634 PortAgent type-1 packets parsed without desync, giving a 55,295-byte stream with 67 AC-S packets, length 704 and N=84; 52 of them were checksum-valid. Values: cref 588,685,792..., aref 679,785..., csig 314,372..., asig 378,464...; overall min 314 max 29,373. A 200 KB probe of 2019-01-10 and 2019-04-10 also showed N=84 (241-244 packets).

Proposed by the autocollect scout on 2026-10-14 (transcript `.data/pipeline/logs/scout_16bit/scout.20261014_131332.jsonl`).
