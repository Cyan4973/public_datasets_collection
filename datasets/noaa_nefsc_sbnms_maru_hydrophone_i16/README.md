# NOAA NEFSC/ONMS Stellwagen Bank MARU array hydrophone recordings (int16)

Raw underwater sound-pressure waveforms from the 10-unit Cornell MARU
(Marine Autonomous Recording Unit) arrays that NOAA's Northeast Fisheries
Science Center and Office of National Marine Sanctuaries deployed in the
Stellwagen Bank National Marine Sanctuary in 2007-2010
(DOI [10.25921/g3vk-v972](https://doi.org/10.25921/g3vk-v972)). The data are
archived by NCEI and served from the NODD Google Cloud bucket
`gs://noaa-passive-bioacoustic/nefsc/audio/sbnms/`.

Each MARU is a single-channel bottom-mounted recorder. After recovery, NEFSC
time-aligned the units of one deployment and stitched them into 10-channel
AIFF files: 15 minutes, 2000 Hz, 12-bit ADC values MSB-aligned in big-endian
int16, so every code is a multiple of 16. Lost or failed units appear as
blank (all-zero) channels.

## What is collected

- **Deployments**: the 7 deployments that use the 10-channel 2 kHz AIFF
  layout (all files 36,000,054 bytes) and have at least one channel the
  publisher flags "Good": sbnms_200712 (NOPP1), 200809 (NOPP4), 200812
  (NOPP5), 200903_2 (NOPP6), 200910_1 (NOPP8), 200912 (NOPP9) and 201004
  (NOPP10).
- **Files**: two per deployment, taken on the middle day of the deployment.
  Their file-name times are 00:00:00 and 12:00:00, so each deployment gives
  one night and one day file. 14 files, 504 MB download. All are pinned by
  name, size and GCS md5 in `files.tsv`.
- **Samples**: one little-endian int16 `.bin` per kept channel, holding
  1,800,000 values (3.6 MB). Expected: 120 samples, 432 MB.
- **Channels excluded** (identical rules in build and verify, listed in
  `filtered/<id>/ingest_stats.json`):
  1. any channel not flagged quality "Good" in the deployment JSON's
     `QUALITY_DETAILS`, i.e. "Unusable" (blank or lost) or "Compromised"
     (trawl damage, noise);
  2. all-zero channels;
  3. railed channels, where count(min) + count(max) is more than 1% of
     frames;
  4. channels where one value covers more than 50% of frames;
  5. channels with std below 16 counts;
  6. channels byte-identical to an earlier kept channel of the same file.
- **Not mixed in**:
  - the FLAC deployments (single-channel files from other recorder setups);
  - the 10 kHz AIFF deployments 200806_1 and 200907_1;
  - the 7-channel realigned 200907_2;
  - 200803 (NOPP2), where the publisher flags every channel "Unusable". In
    40 KB probes its channels look live, but one of them is railed at
    -32768/25520 for about half its values, so the flag is respected.

Values are the stored codes. The only changes are the byte order and the
de-interleave. The 12-bit lattice and the DC offset of each recorder are
kept.

## Quality-flag caveats (honest notes)

The publisher's channel flags are imperfect. 200903_2 flags all 10 channels
"Good", yet its channel 4 is all zero, and rule 2 drops it. 200912 flags
channel 6 "blank" although probes show signal there; it is dropped anyway,
because the flag is applied as published. Channel numbering (1-based) lines
up with AIFF channel order: the blank channels named in the JSON for 200712
(ch2) and 201004 (ch2, ch3) are exactly the all-zero AIFF channels.

## Compressibility note

The ambient-noise standard deviation is low, roughly 30 to 800 counts in the
probes, around DC offsets of -500 to -1000. Combined with the 12-bit lattice,
this makes the material quite compressible. That is expected for this
instrument. The index records `std`, `min`, `max`, `distinct_values`,
`mode_fraction` and `rail_fraction` for every sample, so dead channels can be
ruled out at a glance.

## Files

- `discover.sh`: re-derives `files.tsv` and `meta.tsv` from the GCS
  listing and deployment JSONs. It documents the selection and is not part
  of the pipeline.
- `download.sh`: runs a liveness check, then fetches the NCEI ISO record
  (license and citation check), the 7 metadata JSONs (md5, 2 kHz/12-bit,
  Good channels) and the 14 AIFF files (resumable; size, md5 and header
  checked).
- `build.sh` runs `scripts/maru.py build`: generic AIFF chunk walk, then
  `array('h')` + byteswap + strided slices.
- `verify.sh` runs `scripts/maru.py verify`: a fixed 54-byte header
  comparison and a byte-lane de-interleave, then a re-derived exclusion
  list, byte equality, index fields and manifest totals.

## License

U.S. Government work. The NCEI ISO record lists only two liability
disclaimers and a citation request. Cite as:

> NOAA Northeast Fisheries Science Center and NOAA Office of National Marine
> Sanctuaries. 2020. An Ocean Observing System for Large-Scale Monitoring and
> Mapping of Noise Throughout the Stellwagen Bank National Marine Sanctuary.
> NOAA National Centers for Environmental Information.
> https://doi.org/10.25921/g3vk-v972
