# UCI Parking Birmingham Occupancy Int16

This staged recipe collects the official CC BY 4.0 UCI Parking Birmingham
table and emits one complete occupancy-count timeline per car-park system code.

The primary values are exact source integer counts of occupied spaces. They
are range-checked against each facility's documented capacity and encoded as
little-endian signed int16, including the source's small negative and
above-capacity measurement anomalies. Facility identifiers, timestamps, and
the constant capacity field remain validation metadata and are not sample
bytes.

This material is adjacent to existing bike-rental counts but has a different
operational shape: bounded inventory state sampled repeatedly across multiple
parking facilities, with stepwise daily utilization patterns rather than a
stream of rental events.

Run:

```bash
bash datasets/uci_parking_birmingham_occupancy_i16/download.sh
bash datasets/uci_parking_birmingham_occupancy_i16/build.sh
bash datasets/uci_parking_birmingham_occupancy_i16/verify.sh
```

Validated output: 30 complete source facility-code timelines containing 35,717
signed-int16 values and 71,434 bytes. Median sample length is 1,294 values.
The exact source includes 12 negative readings and 373 readings above nominal
facility capacity; all are retained as published.
