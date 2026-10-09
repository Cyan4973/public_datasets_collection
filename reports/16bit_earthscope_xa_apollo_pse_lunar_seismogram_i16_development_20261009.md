# Apollo PSE long-period vertical lunar seismogram int16 development

## Outcome

Accepted `earthscope_xa_apollo_pse_lunar_seismogram_i16`. It holds complete UTC station-days of the long-period vertical (MHZ) channel of the Apollo 12, 14, 15 and 16 ALSEP Passive Seismic Experiment seismometers on the Moon, 1971-1977. The data come from the Nunn et al. (2022) restored archive, which EarthScope serves as FDSN network XA (1969-1977).

This is the corpus's first material from this source at any width. Seismometer waveforms already exist as the terrestrial 32-bit IRIS counts baseline (`seismic_waveform_i32`), so the novelty is `new_source`, not a new modality. The coarse 10-bit lunar telemetry is a distinct low-entropy regime: a DC level with ±1 DU dither, tidal and thermal drift, moonquake bursts and telemetry glitches.

## Source and rights

- Source: EarthScope fdsnws-dataselect 1, one anonymous GET per pinned plan row (`net=XA&sta=<S12|S14|S15|S16>&loc=00&cha=MHZ`, one UTC day, `nodata=404`). Each response is 4096-byte miniSEED 2 records, Steim2 (encoding 11).
- Inventory: fdsnws-station text for XA 1969-1977. It lists every plan station as `00|MHZ`, 6.625 sps, "Apollo PSE Alsep Seismometer".
- Network page: https://www.fdsn.org/networks/detail/XA_1969/ (operated by NASA Goddard Space Flight Center, DOI 10.7914/SN/XA_1969; cite Latham et al. 1970 and Nunn et al. 2022).
- License: NASA SMD Scientific Information Policy (`LicenseRef-NASA-SMD-Open-Data`). Information produced from SMD-funded research is "made publicly available". download.sh re-fetches the page and string-checks it.
- Supporting evidence:
  - Station XML lists the network with `restrictedStatus="open"`.
  - The archive authors state "The archive is public at IRIS and the Planetary Data System".
  - The DataCite rightsList is empty, which is disclosed.
  - The same basis was accepted for `nasa_pds_lola_rdr_spot_radius_range_i32`.
- Download: 43,105,473 bytes (119 station-day files plus inventory and evidence pages).

## Shape and conversion

- Natural record: one station-channel UTC day of about 572,400 samples.
- Decoder: a pure-stdlib miniSEED 2 reader adapted from the accepted `earthscope_pb_borehole_strain_counts_i32` recipe. It handles BTIME, time correction and blockettes 1000/1001, and decodes Steim2 with the X0/Xn integration constants checked on every record. An independent synthetic Steim2 encoder self-test runs before every validate, build and verify.
- Assembly: records are sorted by time and exact duplicates dropped. The chain must be contiguous within 1 sample period (realized maximum deviation 0.51 samples). Values are written unchanged as little-endian int16. The range -1..1023 is enforced, and the archive's inline `-1` missing-sample marker is kept verbatim.
- Day policy: a day must hold at least 99% of the nominal samples, have at most 20% `-1`, and take at least 16 distinct valid levels. Failing days are skipped whole and logged; days are never split or spliced.
- Excluded: location 01 (flat response mode), S11, SHZ (53 sps), the horizontals and ATT.
- The plan (`plan.tsv`, 119 station-days) was resolved once by `discover.sh`. It draws crc32 candidate days per station-year, probes 3×10-minute windows per candidate, and selects round-robin over years.

## Accepted output

- Primary samples: 106 (S12 30, S14 16, S15 31, S16 29; every year 1971-1977)
- Primary values: 60,666,177
- Primary bytes: 121,332,354
- Sample size: minimum 567,591, median 572,400, maximum 572,401 values
- Skipped plan days: 13 (5 degenerate, 4 short, 2 inter-record gaps, 2 with more than 20% `-1`)
- `-1` markers: 1,012,517 (1.67% of values; per-day maximum 19.1%)
- Day modes: 415-527 DU. Order-0 entropy has a median of 1.78 bits/value (range 0.48-4.89).
- Aggregate decoded SHA-256: `8a261e35151dfe2b29df52ebcba5c906461b999dbb3d784b1e57fbec7f2407b8`
- zlsim: OK. Nearest family is `ceda_ukdale_iam_appliance_power_u16` at 0.0824 (loss 0.1199).

## Judge checks

- **Gate:** `gate.py` PASS with no warnings.
- **Verify:** I re-ran `verify.sh`. The self-test passed and it reported `verify_ok samples=106 total_bytes=121332354` across 4 stations and 7 years.
- **Independent decode:** I wrote a separate Steim2/miniSEED decoder from the SEED layout (walking the blockette chain, which starts with 1001 then 1000). It reproduced the stored int16 bytes exactly on 5 days, including the shortest day (S12 1973-04-06) and the saturated day (S14 1977-04-03). All records are quality `M` with the correct stream identity.
- **Bytes:**
  - Quiet days are a DC level with ±1 DU dither: delta 0 for 93-95% of steps, median constant run 4-5 samples.
  - Active days show coherent waveforms, e.g. a smooth oscillation with lag-1 autocorrelation 0.90.
  - Global shares: 0 at 0.014%, 1023 at 0.077%, isolated spikes at 6.8e-5.
  - S14 1977-04-03 opens with about 1.7 h of saturated 1023 words (7%). This is archive content.
  - There are no duplicate samples.
- **Fill warning (mode share 0.8146):** justified. The dominant value is each day's quiet seismometer DC level, which varies by station and day, with ±1 DU dither. It is not a no-data code. The archive authors note the very coarse digitization at low SNR, and days with fewer than 16 levels are already dropped.
- **Rights:**
  - I confirmed `restrictedStatus="open"` with a station-XML probe and the empty DataCite rightsList with a DataCite API probe.
  - I read the NASA SMD policy text and the FDSN page (NASA GSFC operator).
  - The authors' notebook confirms the archive is public at IRIS and PDS, along with the `-1` convention, the constant sampling interval, nominal gains and possible short peaked/flat mislabels. The README documents all of these.
  - No credentials appear in any script, and build and verify make no network calls.
- **Novelty:** `novelty.py` URL and term checks match only the shared EarthScope host path (PB strain, 4P MT) and the lunar LOLA, GRAIL and gravity recipes, all different modalities. There are no downstream matches, and no family shares the instrument line or archive collection.
- **Cosmetic note:** the README still quotes the probe-time maximum chain deviation of 0.41 samples. The realized maximum in the index is 0.51 samples, within the 1-sample tolerance.
