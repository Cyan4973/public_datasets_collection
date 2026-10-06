# MBARI Pacific Ocean Sound (MARS Cabled Observatory, 891 m) Daily Hybrid-Millidecade Band Sound Pressure Spectral Density at 1-Minute Resolution, Native Float32

- Candidate id: `mbari_mars_hydrophone_hmd_psd_f32`
- Width: float32
- Quantity: Calibrated underwater sound power spectral density (dB re 1 µPa²/Hz) in 2,787 hybrid millidecade bands, one spectrum per minute (1440 per day). PyPAM v0.2.0 computes it from the icListen digital hydrophone at the MARS deep-sea cabled observatory in Monterey Bay, following the Martin et al. 2021 / SoundCoop standard.
- Source: https://registry.opendata.aws/pacific-sound/
- Resources: https://pacific-sound-spectra.s3.amazonaws.com/?list-type=2&max-keys=1000, https://pacific-sound-spectra.s3.amazonaws.com/2021/MARS_20210101.nc, https://docs.mbari.org/pacific-sound/
- License: CC-BY-4.0
- License evidence: https://github.com/awslabs/open-data-registry/blob/main/datasets/pacific-sound.yaml
- License quote: Registry: 'License: CC-BY 4.0'. Each NetCDF's global attributes also say: 'As for the original recordings available online (https://registry.opendata.aws/pacific-sound/), this derived data product carries the CC-BY 4.0 license.'
- Natural record: One daily NetCDF4 file's psd variable: a 1440-minute x 2787-band float32 matrix, 4,013,280 values (16,053,120 bytes), stored contiguous and uncompressed inside the HDF5 file.
- Estimated samples: 36
- Estimated primary values: 144,500,000
- Estimated download bytes: 580,000,000
- Estimated primary bytes: 578,000,000
- Decode path: List pacific-sound-spectra and keep the 2,189 'YYYY/MARS_YYYYMMDD.nc' files (16,124,324 B, 2017–2023). Pick ~36 evenly spaced days. Curl the first 32 KB, parse the HDF5 superblock v0 and v2 OHDR messages in pure Python: datatype message (class 1 float, size 4, little-endian), dataspace (1440 x 2787), layout message v3 class 1 contiguous giving address and size. Assert size == 1440*2787*4, then range-fetch exactly that span (address 37,004 in the probed 2021 and 2018 files; never hardcode it) and emit it as little-endian float32. Keep native NaN/fill as is and document them. Frequency and time coordinates may be emitted as auxiliary.
- Novelty kind: new_modality
- Novelty evidence: novelty.py --url https://pacific-sound-spectra.s3.amazonaws.com/ --terms millidecade hydrophone 'pacific sound' MBARI returned no matches in URLs, recipes, registry, ledger, downstream or downstream_registry. Local acoustics are room impulse responses (f32), bat vocalizations (i16), CirCor PCG and MIMII machine audio. No ocean passive-acoustic or soundscape spectral product exists at any width.
- Homogeneity: Only the MARS cabled-observatory daily files at the 16,124,324 B layout (1440 x 2787 HMD bands, one PyPAM processing chain, one unit dB re 1 µPa²/Hz). Exclude the 'mb05/' files (710 at 12,528,662 B; different site and recorder, band count differs) and the 'MANTA_961/' and 'MBARI/' comparison folders. Hydrophone serial changes are absorbed by the per-file calibration, so the unit is unchanged.
- Risks: This is a derived (computed) spectral product rather than raw pressure samples. It is the publisher's standard community data product, carries an explicit CC BY grant, and matches the accepted VPTS precedent. The raw 16 kHz WAVs are 24-bit PCM, so they are not 32-bit material. Values are log-domain dB (probe range 35.6–88.6) with smooth spectral shape, but they carry full float precision (100% unique in the probe). Some minutes may be NaN or filled when the hydrophone was down. The builder must parse HDF5 headers per file rather than assume a fixed offset.
- Probe evidence: Paged the bucket listing: 2,913 .nc files, of which 2,189 are MARS daily files at 16,124,324 B (2017:201, 2018:357, 2019:355, 2020:357, 2021:355, 2022:355, 2023:209). A 32 KB range GET of 2021/MARS_20210101.nc showed an HDF5 v0 superblock and the NetCDF4 global attribute text (title 'Hybrid Millidecade Band Sound Pressure Levels Computed at 1 Minute Resolution ... MARS', the CC-BY 4.0 statement, and the PyPAM v0.2.0 method). A decoded OHDR gave a dataset with float class size 4 and contiguous layout at address 0x908C=37,004, size 0xF4F380=16,053,120 = 1440*2787*4. An 11 KB range at 37,004 gave 2,787 floats in 35.6–88.6, all unique. The 2018-06-15 file carries the identical layout bytes. The 16 kHz WAV header showed PCM 24-bit mono 16 kHz. Total transfer about 0.1 MB.

Proposed by the autocollect scout on 2026-10-06 (transcript `.data/pipeline/logs/scout_32bit/scout.20261006_035508.jsonl`).
