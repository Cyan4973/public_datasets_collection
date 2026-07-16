# Blocked Attempt: `noaa_swpc_dscovr_solar_wind_f32` Seven-Day URLs

Date: 2026-07-15

## Outcome

The initial DSCOVR solar-wind download script failed immediately because both
planned NOAA SWPC seven-day JSON product URLs returned `404`.

## Failed URLs

```text
https://services.swpc.noaa.gov/products/solar-wind/plasma-7-day.json
https://services.swpc.noaa.gov/products/solar-wind/mag-7-day.json
```

## Fix Applied

The staging recipe was changed to use the SWPC one-day product names:

```text
https://services.swpc.noaa.gov/products/solar-wind/plasma-1-day.json
https://services.swpc.noaa.gov/products/solar-wind/mag-1-day.json
```

The natural sample description and manifest were updated from seven-day streams
to one-day streams.

## Follow-up

The one-day product names also returned `404`:

```text
https://services.swpc.noaa.gov/products/solar-wind/plasma-1-day.json
https://services.swpc.noaa.gov/products/solar-wind/mag-1-day.json
```

The staging recipe has been updated again to use the SWPC DSCOVR JSON namespace:

```text
https://services.swpc.noaa.gov/json/dscovr/dscovr_plasma_1s.json
https://services.swpc.noaa.gov/json/dscovr/dscovr_mag_1s.json
```

## Final Status

The DSCOVR JSON namespace URLs also returned `404`. The candidate is blocked
until a verified current SWPC DSCOVR product URL is available. The next staged
new-domain candidate is `cicids2017_network_flow_features_f64`.
