# USGS NWIS Daily Water Temperature

This recipe collects a curated subset of USGS NWIS daily water-temperature
observations and converts selected numeric fields into raw numeric samples.

Selected scope:
- parameter code `00010` (water temperature)
- years `2021` through `2023`
- 32 geographically diverse stream sites across the US
- one output sample per site per series

| Site ID | Description |
|---------|-------------|
| `01100000` | Merrimack R at Lawrence MA |
| `01372500` | Hudson R at Poughkeepsie NY |
| `01463500` | Delaware R at Trenton NJ |
| `01481500` | Brandywine Ck at Wilmington DE |
| `01578310` | Susquehanna R at Conowingo MD |
| `01594440` | Patuxent R at Bowie MD |
| `01646500` | Potomac R at Little Falls MD |
| `02087500` | Neuse R near Kinston NC |
| `02169500` | Congaree R near Columbia SC |
| `02215500` | Oconee R at Milledgeville GA |
| `02335000` | Chattahoochee R at Atlanta GA |
| `02342500` | Apalachicola R at Chattahoochee FL |
| `04085427` | Fox R at Green Bay WI |
| `04193500` | Maumee R at Waterville OH |
| `05288500` | Mississippi R at Minneapolis MN |
| `05420500` | Mississippi R at Clinton IA |
| `05587450` | Illinois R at Valley City IL |
| `06805500` | Platte R at Ashland NE |
| `06892350` | Kansas R at DeSoto KS |
| `06934500` | Missouri R at Hermann MO |
| `07022000` | Mississippi R at Thebes IL |
| `07144200` | Arkansas R at Wichita KS |
| `07374000` | Mississippi R at Baton Rouge LA |
| `07381490` | Atchafalaya R at Melville LA |
| `08158000` | Colorado R at Austin TX |
| `09085000` | Colorado R near Dotsero CO |
| `09163500` | Colorado R near Colorado-Utah line |
| `11447650` | Sacramento R at Sacramento CA |
| `12114500` | Green R at Auburn WA |
| `13011900` | Snake R near Moran WY |
| `14048000` | Deschutes R at Moody OR |
| `14211720` | Willamette R at Portland OR |

Series emitted by `build.sh`:
- `usgs_water_temperature_c_f64` (`float64`, little-endian)
- `obs_year_u16` (`uint16`, little-endian)
