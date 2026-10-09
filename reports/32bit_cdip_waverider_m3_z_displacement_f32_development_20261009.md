# CDIP Datawell DWR-M3 Waverider heave displacement float32 development

## Outcome

Accepted `cdip_waverider_m3_z_displacement_f32`: raw 1.28 Hz vertical sea-surface displacement (heave, `xyzZDisplacement`) measured by Datawell DWR-M3 directional Waverider buoys and archived by the Coastal Data Information Program (CDIP, Scripps Institution of Oceanography).

This is the corpus's first raw wave-buoy displacement waveform:

- The only local wave family, `noaa_ndbc_wave_spectral_density_f64`, holds derived spectral densities.
- Downstream holds only NDBC hourly summary statistics (`ndbc_wvht` and others, at 64 bits).
- Comparable oscillatory sensor waveforms do exist (accelerometers and seismometers in `inertial_vibration`, and water-level series), so the novelty is labelled `new_source`, not `new_modality`.

The measured breadth verdict is OK.

## Source and rights

- **Source:** the CDIP THREDDS archive, `https://thredds.cdip.ucsd.edu/thredds/dodsC/cdip/archive/<NNNp1>/<NNNp1>_dMM.nc`, read through OPeNDAP DAP2 binary hyperslab projection.
- **Instrument screen:** `scripts/discover.py` screened all 1,423 archive deployment files by their `.das` title. 974 are DWR-M3, at 136 stations. Windows are pinned in `windows.tsv`, resolved on 2026-10-08.
- **License:** every selected file's NC_GLOBAL carries `license = "These data may be redistributed and used without restriction."`. `download.sh` and `verify.sh` require that exact string in each deployment's `.das`.
- **CDIP web policy:** the data-access page states the data are freely available "provided that they are not altered in any way" and asks for attribution. Values are kept bit-exact, and the manifest citation credits CDIP/SIO and USACE.
- **Access:** anonymous HTTPS only. No credentials, no personal data.

## Shape and conversion

- **Natural record and window:** the natural record is one buoy deployment, typically weeks to years at 1.28 Hz. The full DWR-M3 Z archive is about 100 GB, so the recipe takes one bounded contiguous window of exactly 3 days (331,776 values) per station. Deployments are never split and never concatenated.
- **Window selection:**
  - Deployments are tried longest first, at most 4 per station.
  - The window starts at least 2 days after the first wave record.
  - The 145 covering half-hour wave records must be consecutive with `waveFlagPrimary == 1`.
  - Every xyz sample must have `xyzFlagPrimary` in {1, 2}. Flag 2, "not evaluated", is the archive default; all 128 windows are in fact all-2.
  - Every xyz sample must have `xyzFlagSecondary == 0`, with no `_FillValue -999.99`, no NaN, and |z| ≤ 20.47 m.
- **Download validation:** each `.dods` response must be exactly 1,990,962 bytes, carry XDR counts of 331,776, and report `xyzSampleRate` equal to float32(1.28).
- **Conversion:** the big-endian Float32 Z elements are reversed to little-endian. Nothing is rescaled, rounded or interpolated. No `additional_processing` attribute applies to `xyzZDisplacement`.
- **Homogeneity:** one instrument model (all 128 DAS files give `make_model "Datawell DWR-M3 directional buoy"`), one sample rate, one 0.01 m telemetry lattice, one unit (meter), one variable, one archive decode.

## Accepted output

- Primary samples: 128, one per station and deployment, 2007–2025: US West, East and Gulf coasts, Great Lakes, Alaska, Hawaii, Pacific islands, Caribbean, Canada and Ocean Station Papa.
- Values per sample: 331,776 (1,327,104 bytes)
- Primary values: 42,467,328
- Primary bytes: 169,869,312
- Download bytes: 258,543,393 (254,843,136 DODS + 3,700,257 DAS)
- Global value range: -6.76 .. +7.75 m. Distinct values: 1,154 overall, 79–1,119 per sample.
- Per-sample SD: 0.053–0.941 m (median 0.281). Zero-crossing period: 2.3–9.0 s (median 5.6 s).
- Centimetre-lattice fraction: 1.0
- Aggregate SHA-256 of sample SHA-256s: `47966b95ccf3ae0063fba3ea0d3213fa1eb49e634df9d715e6e4c3a3e5b41364`
- zlsim: own ratio 4.53. Nearest family `downstream:sao_xdpm` at distance 0.0774 (loss 0.0131), outside the 0.05 distance threshold. `open_meteo_hourly_dew_point` is at 0.115. Verdict OK.

Caveats:

- The window length (3 days) and the selection bias toward early, gap-free stretches are deterministic choices documented in the recipe.
- 8 of the 136 DWR-M3 stations had no qualifying window.
- There is no upstream checksum. CDIP reprocessing could change values on re-download, but `download.sh` semantic checks and the recorded per-sample SHA-256 would expose this.

## Judge checks

- **Gate:** ran `python3 tools/autocollect/gate.py staging/cdip_waverider_m3_z_displacement_f32`. PASS, no warnings.
- **verify.sh:** ran it myself. `verify_ok samples=128 bytes=169869312`. Its decoder is independent of the build parser: it matches the exact DDS header, checks the counts, and byte-swaps by slicing.
- **Provenance:** confirmed `build.sh` reads only `.data/downloads`, and that `download.latest.log` (23:55) postdates every script edit, with 128/128 windows valid and 0 refetches.
- **Byte scan (own stdlib script over all 128 samples):**
  - Every value equals float32(k/100).
  - Means are within ±2.5e-5 m. There are no duplicate files or prefixes and no fill.
  - Largest crests are smooth 5–7-sample waves.
  - The largest relative oscillations (up to 13 SD at Betton Island AK, SD 0.053 m) are near-Nyquist chop at sheltered sites, which the CDIP metadata describes.
  - Max mode share is 0.144 (the value 0.00 at Isle Royale East, where hourly SD falls to 0.007 m): real calm water, not fill.
- **Rights:** confirmed the exact license string in all 128 downloaded DAS files, and read CDIP's data-access policy (no restriction beyond attribution and not altering values).
- **Novelty:** ran `novelty.py` with `--url` (thredds.cdip.ucsd.edu, cdip.ucsd.edu), with `--terms` (cdip waverider datawell heave xyzZDisplacement buoy swell), with `--vocabulary`, and with `--type/--instrument/--archive`. No source, registry, ledger or downstream match. The downstream wave material is limited to hourly NDBC statistics.
