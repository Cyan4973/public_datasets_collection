# NOMIS Employment

NOMIS Jobseeker's Allowance claimant observations from dataset `NM_1_1`.
The recipe keeps one homogeneous material: item `1` total claimants and
measure `20100` persons claiming JSA. It widens the current single-geography
slice by querying a NOMIS geography selector.

Source URL template:
- `https://www.nomisweb.co.uk/api/v01/dataset/NM_1_1.data.json?geography={geography}&item=1&measures=20100`

Selected series:
- `nomis_obs_value`
- `nomis_geography`
- `nomis_sex`
- `nomis_year`
- `nomis_month`

Download knobs:
- `NOMIS_GEOGRAPHY` defaults to `TYPE480`.
- `NOMIS_ITEM` defaults to `1`.
- `NOMIS_MEASURE` defaults to `20100`.
- `NOMIS_MIN_RECORDS` defaults to `10000`.

Build knobs:
- `NOMIS_MIN_RETAINED_RECORDS` defaults to `10000`.
