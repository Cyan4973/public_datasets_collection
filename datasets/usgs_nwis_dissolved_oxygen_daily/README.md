# USGS NWIS Daily Dissolved Oxygen

This recipe collects USGS NWIS daily dissolved-oxygen observations from 32
geographically diverse stream gauging stations across the US and converts
selected numeric fields into raw numeric samples.

Selected scope:
- parameter code `00300` (dissolved oxygen)
- years `2021` through `2023`
- sites (one output sample per site with available data):

  | Site ID    | Description                              | Region              |
  |------------|------------------------------------------|---------------------|
  | `01100000` | Merrimack R at Lawrence MA               | Northeast           |
  | `01372500` | Hudson R at Poughkeepsie NY              | Northeast           |
  | `01463500` | Delaware R at Trenton NJ                 | Northeast           |
  | `01481500` | Brandywine Ck at Wilmington DE           | Mid-Atlantic        |
  | `01578310` | Susquehanna R at Conowingo MD            | Mid-Atlantic        |
  | `01594440` | Patuxent R at Bowie MD                   | Mid-Atlantic        |
  | `01646500` | Potomac R at Little Falls MD             | Mid-Atlantic        |
  | `02087500` | Neuse R near Kinston NC                  | Southeast           |
  | `02169500` | Congaree R near Columbia SC              | Southeast           |
  | `02215500` | Oconee R at Milledgeville GA             | Southeast           |
  | `02335000` | Chattahoochee R at Atlanta GA            | Southeast           |
  | `02342500` | Apalachicola R at Chattahoochee FL       | Southeast           |
  | `04085427` | Fox R at Green Bay WI                    | Midwest             |
  | `04193500` | Maumee R at Waterville OH                | Midwest             |
  | `05288500` | Mississippi R at Minneapolis MN          | Midwest             |
  | `05420500` | Mississippi R at Clinton IA              | Midwest             |
  | `05587450` | Illinois R at Valley City IL             | Midwest             |
  | `06805500` | Platte R at Ashland NE                   | Great Plains        |
  | `06892350` | Kansas R at DeSoto KS                    | Great Plains        |
  | `06934500` | Missouri R at Hermann MO                 | Midwest             |
  | `07022000` | Mississippi R at Thebes IL               | South               |
  | `07144200` | Arkansas R at Wichita KS                 | Great Plains        |
  | `07374000` | Mississippi R at Baton Rouge LA          | South               |
  | `07381490` | Atchafalaya R at Melville LA             | South               |
  | `08158000` | Colorado R at Austin TX                  | South / Texas       |
  | `09085000` | Colorado R near Dotsero CO               | Mountain West       |
  | `09163500` | Colorado R near Colorado-Utah line       | Mountain West       |
  | `11447650` | Sacramento R at Sacramento CA            | West Coast          |
  | `12114500` | Green R at Auburn WA                     | Pacific Northwest   |
  | `13011900` | Snake R near Moran WY                    | Mountain West       |
  | `14048000` | Deschutes R at Moody OR                  | Pacific Northwest   |
  | `14211720` | Willamette R at Portland OR              | Pacific Northwest   |

Sites with no parameter-00300 data for a given year are skipped at build time.

Series emitted by `build.sh`:
- `usgs_dissolved_oxygen_f64` (`float64`, little-endian)
- `obs_year_u16` (`uint16`, little-endian)
- `obs_month_u8` (`uint8`)
- `obs_day_u8` (`uint8`)
