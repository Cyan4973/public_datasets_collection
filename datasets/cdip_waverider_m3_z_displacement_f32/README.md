# CDIP Datawell DWR-M3 Waverider Raw Heave Displacement (float32)

Raw vertical sea-surface displacement ("heave", `xyzZDisplacement`) recorded
by Datawell DWR-M3 directional Waverider buoys and archived by the Coastal
Data Information Program (CDIP, Scripps Institution of Oceanography). The
values are 1.28 Hz samples in metres with 0.01 m telemetry resolution, stored
as Float32 in the CDIP archive NetCDF files.

## Scope

- Source: CDIP THREDDS archive, `cdip/archive/<NNNp1>/<NNNp1>_dMM.nc`, read
  through OPeNDAP DAP2 binary hyperslab projection, so only the selected
  values are transferred.
- Instrument: only deployments whose NetCDF global `title` says
  "collected in situ by Datawell DWR-M3 directional buoy" (974 of the 1,423
  archive deployment files, at 136 of 192 stations), each with
  `xyzSampleRate == 1.28`. DWR-M1/M2/M4, DWR-GPS and Mark I/II buoys are
  excluded because they differ in sample rate or resolution.
- Samples: one contiguous window of exactly 3 days (331,776 values) from one
  DWR-M3 deployment per station. That gives 128 stations (US West, East and
  Gulf coasts, Great Lakes, Alaska, Hawaii, Pacific islands, Caribbean,
  Canada, Ocean Station Papa) spanning 2007–2025, and
  169,869,312 primary bytes. No deployment is split into several windows,
  and no station contributes more than one.
- The natural record is a buoy deployment, typically weeks to years at
  1.28 Hz (up to about 140 M values, roughly 0.5 GB of Z per deployment).
  The full DWR-M3 Z archive is on the order of 100 GB, far above the 1 GB
  cap, so the recipe takes one bounded window per deployment.

## Window selection (`scripts/discover.py`, output pinned in `windows.tsv`)

For each station, the DWR-M3 deployments are tried longest first (at most
4). The window start is the first half-hour wave-record start time at least
2 days after the deployment's first wave record where:

1. the 145 covering wave records are consecutive (1800 s apart) and all have
   `waveFlagPrimary == 1`;
2. the full xyz flag hyperslab has `xyzFlagPrimary` in {1 good, 2
   not_evaluated} and `xyzFlagSecondary == 0`. Flag 2 is the archive default
   for xyz data. Gaps carry flag 9 and `_FillValue -999.99`; flags 3 and 4
   mark questionable or bad data, and HF transmission errors are flagged in
   the secondary flag;
3. a stride-16 probe of Z has no fill value, |z| < 30 m, and more than 50
   distinct values.

The xyz start index is `ceil((t0 - xyzStartTime + xyzFilterDelay) * 1.28)`,
the inverse of CDIP's documented time formula. 8 stations had no window
that qualified within the search limits. Their windows were rejected for
flag 9 gaps (57 cases), flag 3/1 (19), and flag 4/2 (2).

## Pipeline

- `download.sh`: for each of the 128 rows, fetch `<deployment>.nc.das` and
  check the DWR-M3 title, exact license string, station id, units and fill
  value. Then fetch
  `.dods?xyzStartTime,xyzSampleRate,xyzFilterDelay,xyzFlagPrimary[a:1:b],xyzFlagSecondary[a:1:b],xyzZDisplacement[a:1:b]`
  with `curl -g`. Each response must be exactly 1,990,962 bytes and pass the
  missing-value policy; a semantically invalid window is fatal. The total is
  about 258.5 MB.
- `build.sh`: parse the DDS and XDR (two big-endian int32 counts, then
  big-endian float32 values), byte-swap Z to little-endian, and write
  `samples/<id>/cdip_dwr_m3_heave_z_displacement_f32/<deployment>.bin`.
  Also write `index/<id>/samples.jsonl` (with station, site, deployment,
  start index, first-sample UTC time, min/max, SHA-256) and
  `filtered/<id>/ingest_stats.json`.
- `verify.sh`: an independent fixed-layout decoder re-derives every sample
  from the downloads and compares bytes. It re-applies the missing-value
  policy and rejects degenerate series (fewer than 50 distinct values,
  standard deviation below 0.02 m, |mean| above 0.5 m, or a run of more than
  256 identical values). It also checks index fields, min/max from the
  stored float32, one window per station and deployment, and the manifest
  totals.

## Missing values

Windows are gap-free by construction, and nothing is dropped, interpolated
or rescaled. Any flag outside the policy, fill value, NaN, or |z| > 20.47 m
(the DAS valid range) fails the recipe.
Degeneracy is judged over the whole window, identically in download and
verify. Sheltered sites such as Bahia Honda Key (242p1) have long calm
stretches of only a few centimetres, which are kept as legitimate data.

## License

Every CDIP archive file carries the global attribute
`license = "These data may be redistributed and used without restriction."`
`download.sh` checks this string in the `.das` of each selected deployment.
Credit CDIP / Scripps Institution of Oceanography and its funders
(primarily USACE).

## Caveats

- The values sit on a 0.01 m lattice (build reports the lattice fraction),
  which makes the stream quite compressible. The values are stored verbatim
  as float32 and not remapped to integers.
- CDIP occasionally reprocesses archive files (`date_modified`). Window
  indices are positional within a file, so a re-download after
  reprocessing could change values. Per-sample SHA-256 hashes are recorded
  in the index.
