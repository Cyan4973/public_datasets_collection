# Blocked: DeepMind GenCast Ensemble Forecasts Float32

- Date: 2026-08-27
- Candidate: `deepmind_gencast_ensemble_forecasts_f32`
- Intended domain: AI-generated probabilistic global weather forecasts
- Intended representation: separate little-endian float32 samples for each
  physical variable and pressure level, preserving initialization, ensemble,
  forecast-lead, longitude, and latitude axes
- Decision: blocked for training because the forecast archive lacks the
  dataset-specific license required by its own data guide

## Expected value

This would be a genuinely new num32 structure: stochastic AI forecast cubes
rather than measured station timelines, static maps, or deterministic model
tensors.  The authoritative WeatherBench2 bucket contains seven precomputed
GenCast 2020 Zarr archives at three spatial resolutions, including ensemble,
ensemble-mean, and raw variants.

The bounded investigation selected:

```text
gs://weatherbench2/datasets/gencast/2020-64x32_equiangular_conservative.zarr
```

Only consolidated Zarr metadata and documentation were downloaded.

## Technical result

The selected archive contains 15 physical arrays stored as native
little-endian float32 with Blosc/LZ4 plus byte shuffle.  Its axes are:

```text
time=732
sample=56
prediction_timedelta=30
longitude=64
latitude=32
level=3 for pressure-level fields
```

There are eight surface fields and seven three-level atmospheric fields,
including temperature, geopotential, humidity, wind components, pressure, and
precipitation.  The complete archive expands to 292,151,623,680 physical
float32 bytes, so a recipe would select a bounded set of complete
initialization/variable/level ensemble forecast cubes rather than ingesting the
whole archive.

A practical selection could remain below 1 GB while retaining the distinctive
geometry.  For example, one four-initialization source chunk across three
surface variables and four three-level variables would produce 60 homogeneous
samples and 825,753,600 primary bytes.  Each sample would contain one physical
quantity only; variables and pressure levels would not be interleaved.

## License investigation

The pinned DeepMind repository revision
`9c034db1ff412d5db6cbe6bb0c5c9afc5a267719` says that code/notebooks are
Apache-2.0 and other repository materials are CC BY 4.0.  The separate
`dm_graphcast` bucket also publishes the full CC BY 4.0 license, but its
`gencast/dataset/` objects are ERA5/HRES model inputs rather than the
precomputed prediction archive targeted here.

The predictions are hosted in the separate `weatherbench2` bucket.  The pinned
WeatherBench2 data guide explicitly says:

> Please also check the LICENSE files for each dataset in the respective GCS
> buckets. Some datasets allow commercial use. Others only permit research
> use.

The targeted probe searched likely `LICENSE`, `COPYING`, `TERMS`, and `README`
names, in multiple cases, under both:

```text
datasets/gencast/
datasets/gencast/2020-64x32_equiangular_conservative.zarr/
```

All 24 exact-prefix searches succeeded and returned zero matching objects.
The Zarr root attributes are also empty, and the current WeatherBench2 data
guide does not contain a GenCast section or license declaration.  The
WeatherBench2 repository's Apache-2.0 notice covers its software and cannot be
applied automatically to the hosted forecast data.

The final HTTP 401 seen during the first license-probe run came only from an
optional bucket-metadata request after all object searches had completed.  It
was not evidence of hidden license objects or inaccessible forecast data; the
probe was corrected to make that irrelevant request non-fatal and completed
from the cached listings.

## Decision and retry condition

Do not download numerical chunks or promote these forecasts for training under
the current evidence.  Retry only if WeatherBench2 or Google DeepMind publishes
an explicit license that identifies the `weatherbench2/datasets/gencast/`
prediction archive, or adds the per-dataset license file that the data guide
instructs users to consult.

Do not infer coverage from the `dm_graphcast` bucket license, the DeepMind code
repository license, public readability, or the license of the upstream ERA5
and HRES inputs.

Evidence remains under
`.data/discovery/deepmind_gencast_ensemble_forecasts_f32/`,
`.data/probes/deepmind_gencast_ensemble_forecasts_f32/`, and
`.data/logs/deepmind_gencast_ensemble_forecasts_f32/`.
