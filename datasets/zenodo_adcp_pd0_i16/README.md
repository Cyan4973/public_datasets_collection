# Lower South San Francisco Bay ADCP PD0 Int16

This candidate targets raw Acoustic Doppler Current Profiler observations:
signed 16-bit water velocities arranged by measurement ensemble, depth cell,
and acoustic beam. It would add a new ocean-current sensor domain and a new
multichannel profile shape to the corpus.

The accepted recipe uses three files from Zenodo record `5015459`, *Salinity
and Velocity in Lower South San Francisco Bay*, DOI `10.6078/D14H5K`, released
under CC BY 4.0. Each recording contains 51 depth cells and four
earth-coordinate velocity components.

Every complete PD0 ensemble must provide:

- a complete first PD0 ensemble beginning with `0x7f7f`;
- a valid PD0 offset table and ensemble checksum;
- a fixed leader declaring a plausible beam/cell layout; and
- a velocity block (`0x0100`) containing the expected little-endian int16
  values.

Run the accepted recipe:

```bash
bash datasets/zenodo_adcp_pd0_i16/download.sh
bash datasets/zenodo_adcp_pd0_i16/inspect.sh
bash datasets/zenodo_adcp_pd0_i16/build.sh
bash datasets/zenodo_adcp_pd0_i16/verify.sh
```

The output is three complete little-endian int16 samples with shapes
`[21136, 51, 4]`, `[40000, 51, 4]`, and `[9338, 51, 4]`. Source order is
ensemble, depth cell, then velocity component. All `-32768` invalid-velocity
sentinels are retained. Framing, fixed/variable leaders, correlation,
intensity, and percent-good blocks are validated where needed but not emitted.
