# NOAA NEFSC SBNMS MARU hydrophone int16 development

## Outcome

Accepted `noaa_nefsc_sbnms_maru_hydrophone_i16`. It holds raw low-frequency underwater sound-pressure waveforms from the 10-unit Cornell MARU (Marine Autonomous Recording Unit) arrays that NOAA NEFSC and the Office of National Marine Sanctuaries deployed in the Stellwagen Bank National Marine Sanctuary in 2007-2010.

This is the corpus's first raw underwater-hydrophone waveform at any width, locally or downstream:
- `mbari_mars_hydrophone_hmd_psd_f32` holds derived spectral densities (dB), not waveforms.
- The earlier `noaa_passive_acoustic_pcm16` attempt was blocked because no audio objects were reachable.
- The OOI broadband hydrophone i32 candidate was screened out as hollow.

The material is int16 PCM audio, a modality the 16-bit corpus already has (esc50, mimii, openslr_rirs, librispeech). Novelty is therefore labelled `new_content_same_modality`. What distinguishes it is a different medium and regime: 2 kHz band limit, a 12-bit-in-16 lattice, large per-recorder DC offsets and seafloor ambient content. Measured breadth (zlsim) is OK; the nearest family is downstream `sao_IS` at distance 0.1145.

## Source and rights

- Source: NOAA NODD Google Cloud bucket `gs://noaa-passive-bioacoustic/nefsc/audio/sbnms/`, fetched anonymously over HTTPS; NCEI DOI 10.25921/g3vk-v972.
- Objects: 14 AIFF files of 36,000,054 bytes each, 2 per deployment for sbnms_200712, 200809, 200812, 200903_2, 200910_1, 200912 and 201004. Each is pinned by name, size, GCS md5, crc32c and generation in `files.tsv`.
- Metadata: 7 deployment JSONs pinned in `meta.tsv`.
- Download: 504,155,984 bytes in total.
- Rights evidence:
  - The NCEI ISO 19115 record `gov.noaa.ncei.pad:NEFSC_SBNMS_Raw_Data` lists only "Distribution liability" and "Use liability" disclaimers and a "Cite as" request. Its publisher is NOAA NCEI.
  - The bucket's `nefsc/README.pdf` names the provider as NOAA Northeast Fisheries Science Center.
  - NOAA's Big Data Project FAQ states that NODD datasets are "free for all users to access with no use restrictions".
- This is the same U.S. Government basis as `noaa_goes16_xrs_1s_flux_f32` and the other 45+ accepted US-Government recipes. `download.sh` re-validates the ISO constraints on every run.
- Caveat: one of the three PIs (C. Clark) is from Cornell University. Authorship, citation and distribution are NOAA's, and no other terms exist.
- Citation: NOAA NEFSC and NOAA ONMS (2020), DOI 10.25921/g3vk-v972.

## Shape and conversion

Each AIFF holds 10 time-aligned channels: 1,800,000 frames at 2000 Hz, 16-bit big-endian. NEFSC stitched the single-channel MARU recorders of one deployment into these files after recovery.

The natural record is one channel, meaning one physical recorder at one array site, for one 15-minute file.

The build:
1. Walks the IFF chunks and asserts the COMM/SSND layout.
2. Byteswaps the SSND frames and de-interleaves them.
3. Writes each kept channel as little-endian int16.

No filtering, DC removal or rescaling is applied; the low 4 bits stay zero as stored.

Selection:
- Deployments: only those using the 10-channel 2 kHz AIFF layout. The FLAC, 10 kHz AIFF and 7-channel deployments are excluded, and so is 200803, where every channel is flagged Unusable.
- Files: those named 00:00:00 and 12:00:00 on each deployment's middle day.
- Channel exclusions:
  - 18 channels not flagged "Good" in the publisher's QUALITY_DETAILS: 6 blank, 12 live but Compromised/Unusable.
  - 2 blank channels: 200903_2 ch4, flagged Good but all zero in both files.
  - No channel tripped the railed, dominant-value, near-constant or duplicate rules.

## Accepted output

| Item | Value |
|---|---|
| Files decoded | 14 (140 channels seen) |
| Channels excluded | 20 (18 publisher quality, 2 all-zero) |
| Primary samples | 120 (deployments: 18, 14, 18, 18, 20, 16, 16) |
| Values per sample | 1,800,000 (3,600,000 bytes) |
| Primary values | 216,000,000 |
| Primary bytes | 432,000,000 |
| Per-sample std | 50.6 min / 291.5 median / 2,269.3 max |
| full_scale_count | 0 in every sample |
| Aggregate SHA-256 | `3727f06decb06d50970c52db26bd8098d2f2d82daaa30e226e2099a361529968` |

## Judge checks

- **Gate:** `gate.py` PASS with no warnings.
- **verify.sh** (I ran it): verify_ok in 16.8 s. It decodes independently: fixed-header comparison, byte-lane de-interleave, re-derived exclusions, then byte equality of every sample and the manifest totals.
- **Bytes, within each sample** (all 120 samples read with stdlib `array`):
  - zero off-lattice values;
  - longest zero run 6;
  - longest constant run 10;
  - lag-1 autocorrelation 0.40-0.997;
  - delta entropy 3.6-8.7 bits per sample.
- **Bytes, across samples:**
  - no 2000-value block repeats within or across samples;
  - max |r| between channels of one file is 0.29;
  - the quietest sample (200809 ch06, std 50.6) correlates at r = 0.004 with its 12-hours-later counterpart, so it is a stationary noise floor, not a copy;
  - DC offsets are stable per recorder across both files.
- **Local-only build:** `maru.py` does no network I/O; `build.sh` reads only `.data/downloads`. No credentials in any script.
- **Rights:** I read the downloaded ISO record's constraints and the bucket's top-level and `nefsc/` README PDFs myself, and fetched the NOAA Big Data Project FAQ ("no use restrictions").
- **Novelty:** `novelty.py --url/--terms` found no waveform hydrophone family locally or downstream. `--type/--instrument/--archive` each return 0 matches. The vocabulary shows the existing 16-bit `pcm_audio` group, hence the `new_content_same_modality` label.
- **Known limitation:** samples are correlated, not independent. The two files of a deployment come from the same recorders 12 hours apart, giving about 60 recorder-deployments. The bytes show this is acceptable: the files differ in content (std often doubles between night and day), and channels are weakly correlated.
