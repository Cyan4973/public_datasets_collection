# USGS Seismic Event Feed

Pinned USGS GeoJSON event feed with row-level seismic magnitude and geometry fields.

Selected series:
- `usgs_event_mag_f64`
- `usgs_event_time_u64`
- `usgs_event_felt_u16`
- `usgs_event_tsunami_u8`
- `usgs_event_sig_u16`
- `usgs_event_nst_u16`
- `usgs_event_dmin_f64`
- `usgs_event_rms_f64`
- `usgs_event_gap_u16`

Missing-value policy: filters rows missing required event fields and preserves zero values where present upstream.
