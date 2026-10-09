# EarthScope MT-TA (4P) NIMS fluxgate magnetic-field counts int32 development

## Outcome

Accepted `earthscope_4p_mt_magnetic_field_counts_i32`. It holds native int32 counts from the three magnetic-field components (`LFN`, `LFE`, `LFZ`) of the long-period NIMS fluxgate magnetometers in the NSF EarthScope USArray Magnetotelluric Transportable Array (FDSN network `4P`). Sampling is 1 sps at 100.9048 counts/nT.

This is not a new modality. The corpus already holds ground-magnetometer component series at 32 bits: `usgs_geomag_observatory_minute_f32` locally and `usgs_geomag_xyz_minute_f32` downstream. Both are calibrated float32 nT at 1-minute cadence. This recipe adds a new source and instrument line, raw int32 digitizer counts at 1 sps from temporary MT field stations. The counts carry a large static main-field offset with diurnal and storm-time variation on top. Novelty kind: `new_source`.

zlsim breadth verdict: OK. The nearest family for every component is the accepted `earthscope_pb_borehole_strain_counts_i32`, at distance 0.0656 (LFN), 0.1121 (LFE) and 0.0569 (LFZ), with loss 0.45%, 0.67% and -0.03%. The series are compression-equivalent to PB strain counts but separated on features.

## Source and rights

- Source: EarthScope FDSN web services (`service.earthscope.org/fdsnws`, formerly IRIS DMC).
  - `station/1` text listings for `net=4P cha=LFN|LFE|LFZ` provide epochs, sensor, gain and rate. These are live listings, not hash-pinned.
  - `dataselect/1` returns one Steim2 miniSEED 2.4 payload (4096-byte records) per pinned channel epoch.
- Selection: `scripts/mt_mseed.py select` keeps 4P epochs where LFN/LFE/LFZ share identical start and end, an empty location code, sensor `NIMS`, scale 100.9048 counts/nT and 1.0 sps; 1,073 triplets qualify. From these it takes, per calendar year 2006–2018, the epoch closest to 21 days, plus the runner-up in 2012, 2015 and 2016. Result: 16 deployments × 3 components = 48 epochs, pinned with nominal and decoded value counts and payload sha256 in `selection.tsv`.
- Download: 48 files, 60,215,296 bytes, about 1.07–1.40 MB each. Every payload is fully decoded and its sha256 and value count checked before it is accepted. `check-station` re-confirms each pinned epoch's end time, sensor and gain against the live listing.
- License: CC BY 4.0. The DataCite record for DOI 10.7914/SN/4P_2006 ('NSF EarthScope MT-TA', publisher IRIS) carries rightsList 'Creative Commons Attribution 4.0 International', rightsIdentifier `cc-by-4.0` (SPDX). This DOI identifies exactly the network whose data are fetched. Cite the network DOI.

## Shape and conversion

- Natural record: one station-channel deployment epoch, split at data gaps into contiguous 1-sps segments. A gap means the next record starts more than 0.5 s from the predicted time. A -1 s step across a UTC leap second is treated as continuous; this happens 3 times (ALW48, 2015-06-30). There is no concatenation across gaps or epochs.
- Decoder: `scripts/mt_mseed.py`, pure stdlib. It validates the stream code, encoding 11, word order 1 and rate factor/multiplier 1/1. It decodes all seven Steim2 packings and checks every record's reverse-integration constant.
- Values are written unchanged as little-endian int32, with no scaling, detrending or despiking.
- One primary series per component, because the static offset differs:
  - LFN: about 1.6–2.3e6 counts
  - LFE: near 0, with the sensor aligned to magnetic north
  - LFZ: about 4.35–5.36e6 counts
- Excluded: electric channels LQN/LQE, calibration-variant epochs (`NIMS 2611-*`/`LEMI` at 1e11 counts/T), and other MT networks.

## Accepted output

- Channel epochs: 48 (16 stations × 3 components). Gaps: 93 (31 per component, identical across a station's components). Overlaps: 0. Leap-second continuations: 3.
- Dropped: 6 one-value fragments (ORI09), under the 1,000-value minimum.
- Primary samples: 135, i.e. 45 per series.
- Primary values: 86,447,694. Primary bytes: 345,790,776 (115,263,592 per series).
- Sample size: min 1,509, median 777,026, max 1,806,904 values. 12 startup fragments per series of 1,509–5,508 values precede the first logger restart.
- Value character:
  - |Δ| ≤ 15 counts for 98.5% (LFN), 99.4% (LFE) and 99.8% (LFZ) of steps.
  - Max dominant-value fraction 5.6%; min distinct values 101.
  - 0.57% of LFE values exceed the int16 range.
  - 23 one-sample logger spikes (11 LFN, 1 LFE, 11 LFZ), almost all at segment sample 0–2 after a restart, kept as source behaviour.
- Aggregate decoded SHA-256, all samples in sorted path order: `3b18f1b57632a264a65a5dea8b0ea545281b6eb4d105b6b53664ac0414ad68df`.
- zlsim mode share: 0.9–1.4% per series.

## Judge checks

- `gate.py` passes with no warnings. I ran `verify.sh` myself (exit 0): 48 epochs, 135 samples, 86,447,694 values and 345,790,776 bytes re-decoded and compared byte for byte, and manifest totals ok. `build.sh`, `verify.sh` and the decoder contain no network calls.
- Selection: re-running `mt_mseed.py select` on the downloaded station listings reproduces `selection.tsv` columns 1–7 exactly (16 picks from 1,073 triplets).
- Independent decode checks:
  - My own header reader, separate from the recipe decoder, compared each record's X0/Xn words with the stored output. All 1,213 records in four epochs (NEN29 LFZ, IDL10 LFE, WIG41 LFN, NVN07 LFN) match, and the value totals equal the stored segment concatenations.
  - ALW48 LFN at 2015-06-20T00:00:00 reads 2271241, and 600 s later 2271368. These match the scout's separate decode from service.iris.edu.
- Byte scan: no duplicate sample hashes. LFN and LFZ use 21–23 bits with the top byte always 0. LFE is sign-extended near zero but does not fit int16 losslessly, which is native logger width rather than a widened code.
- Rights: I fetched the DataCite JSON for the DOI myself (cc-by-4.0, SPDX). The fdsn.org network page links the DOI. A credential grep over all scripts found nothing.
- Novelty: `novelty.py --url` on the dataselect hosts, the DOI and `net=4P` has no URL match. `--terms` magnetotelluric/NIMS/MT-TA/LFN/LFZ match only this candidate. `--instrument nims_mt_fluxgate` and `--archive ...:4P` return 0 families. `--type ground_magnetometer` returns only the USGS f32 minute family. `seismic_waveform_i32` uses net IU only.
- Caveats:
  - The series are compression-equivalent to PB strain counts; LFZ's feature distance (0.0569) is near the 0.05 threshold.
  - LFE mostly occupies about 17 bits.
  - The README describes the startup fragments as '1.5k–3k' values; they actually reach 5,508.
