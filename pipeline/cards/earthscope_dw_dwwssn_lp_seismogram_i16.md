# Digital World-Wide Standardized Seismograph Network (FDSN DW, USGS ASL 1981-1987) Sprengnether Long-Period Vertical (LHZ, 1 sps) Seismograms, Native DWWSSN 16-bit Integers

- Candidate id: `earthscope_dw_dwwssn_lp_seismogram_i16`
- Width: int16
- Quantity: Ground motion from the Sprengnether S-5007-V long-period seismometer: raw digitizer counts in miniSEED data encoding 32 (DWWSSN 16-bit big-endian integers), 1 sample/s. Observed day ranges are about ±15,000-17,000, up to ±32,767 at full scale, sd 330-1,300.
- Source: https://www.fdsn.org/networks/detail/DW/
- Resources: https://service.earthscope.org/fdsnws/station/1/query?net=DW&level=channel&format=text, https://service.earthscope.org/fdsnws/dataselect/1/query?net=DW&sta=AFI&cha=LHZ&start=1985-01-01T00:00:00&end=1985-01-02T00:00:00, https://www.usgs.gov/data-management/data-licensing
- License: U.S. public domain (operated by Albuquerque Seismological Laboratory/USGS; USGS federal data = CC0)
- License evidence: https://www.usgs.gov/data-management/data-licensing
- License quote: USGS: federal works are 'in the U.S. public domain, which means that anyone may use, copy, distribute' them; for data 'wholly produced by USGS employees ... use CC Zero'. FDSN DW page: 'Operated by Albuquerque Seismological Laboratory/USGS (ASL)', DOI 10.7914/SN/DW.
- Natural record: One station-day of continuous LHZ: 86,400 int16 values from 00:00 to 24:00 UTC, as in the accepted Apollo XA station-day recipe. Gap-split segments are allowed if the builder prefers.
- Estimated samples: 400
- Estimated primary values: 34,560,000
- Estimated download bytes: 72,000,000
- Estimated primary bytes: 69,000,000
- Decode path: Pure stdlib. miniSEED v2, 4096-byte records: fixed header (nsamp u16 BE at +30, data offset u16 at +44, first blockette at +46). Blockette 1000 gives encoding 32 and the record length. Payload = nsamp × '>h'. Assert encoding==32 for every record. Order records by start time and split at gaps. Same dataselect URL template as the accepted earthscope_xa recipe.
- Novelty kind: new_source
- Measurement type: inertial_vibration
- Instrument line: DWWSSN Sprengnether S-5007 long-period seismometer (USGS ASL digitizer)
- Archive collection: earthscope_fdsnws_dw
- Novelty evidence: novelty.py --url: only same-path matches to the other EarthScope dataselect recipes (XA Apollo lunar i16, PB strain i32, 4P MT i32), all different networks and quantities. Terms DWWSSN, 'net=DW' and Sprengnether have zero hits anywhere (recipes, registry, ledger, downstream). The registry's zenodo_miniseed_int16 was blocked because no native encoding-1/16-bit MiniSEED was found; this is native 16-bit (encoding 32) terrestrial seismology. The only 16-bit seismogram is lunar Apollo data (10-bit, 6.6 sps); the baseline seismic_waveform_i32 is 32-bit.
- Homogeneity: One network, one channel code (LHZ), one sensor regime: restrict to station epochs whose station-service SensorDescription is 'Sprengnether Series 201 S-5007-V' (mostly 1981-1987). Exclude later STS-1 epochs, which have different gain and much smaller counts (a 1989 AFI day spanned only -64..53). About 15 stations (AFI, BDF, BER, COL, GDH, HON, KEV, LEM, LON, SCP, SLR, TAU, TOL...); spread days evenly.
- Risks: (1) Access: EarthScope announced that user authentication will be required for all data downloads from 2026-12-15. Anonymous dataselect works today, but standalone reproducibility after that date needs a free login. This also affects the accepted XA Apollo recipe. (2) Some station-days are missing (LON 1982-11-20 and BDF 1986-02-14 returned no data), so use availability or nodata=404 and over-select. (3) Days contain calibration pulses and clipping at about ±15,600 or ±32,767; these are genuine records but should be noted. (4) The dataset is small (about 69 MB), but well above floors.
- Probe evidence: Station service: 178 channel lines for DW, 18 stations 1980-1994, LHZ Sprengnether S-5007-V epochs listed. Dataselect day pulls (about 180 KB each): AFI 1985-01-01 has 44 records, all encoding 32, 86,400 samples, -15545..15371, sd 455.6, 3,083 distinct. TOL 1984-06-10: -15627..15947, sd 336. KEV 1983-03-05: -17351..17363. SLR 1985-09-01: -15788..15808. GDH 1984-12-01: -16055..15727. TAU 1983-07-07: -32767..32767, sd 1325. AFI 1989-01-01 (STS-1 era): -64..53, which is why the family is limited to the Sprengnether regime.

Proposed by the autocollect scout on 2026-10-14 (transcript `.data/pipeline/logs/scout_16bit/scout.20261014_131332.jsonl`).
