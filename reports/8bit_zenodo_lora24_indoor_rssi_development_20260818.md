# Indoor LoRa 2.4 GHz RSSI Int8 — 2026-08-18

## Outcome

`zenodo_lora24_indoor_rssi_i8` adds 21 measured signed-int8 radio-link RSSI
timelines containing 215,232 packet observations. Samples range from 5,192 to
21,446 values, with a median of 8,732.

This adds a new 8-bit domain and shape: irregular received-packet link-quality
series from fixed wireless devices under controlled radio configurations. It
is distinct from RF baseband I/Q recordings, acoustic angle codes, dense
industrial telemetry, images, and categorical label streams already accepted.

## Source and license

The source is Zenodo record 7106074, *Dataset: Indoor Performance Evaluation
of LoRa 2.4GHz*, DOI `10.5281/zenodo.7106074`, published under CC BY 4.0 by
Carlos Fernández Hernández, Gwendoline Hochet Derévianckine, Oana Iova,
Alexandre Guitton, and Fabrice Valois.

The record documents communication between three fixed end nodes and one
gateway in an INRIA office building. It contains:

- a complete configuration sweep in which every node sent 50 packets under
  every tested LoRa 2.4 GHz setting; and
- a week-long experiment in which the three nodes repeatedly sent packets
  under six radio configurations.

Both CSVs, the Zenodo metadata, readme, and two published analysis scripts are
pinned by exact size and SHA-256. The analysis scripts are retained as decoder
evidence and are never executed.

## Safety and excluded context

This is fixed-device radio-test telemetry, not human tracking or personal
mobility data. The source says the exhaustive experiment ran while the building
was mostly empty.

Only RSSI values are emitted. Packet payloads, wall-clock timestamps, SNR,
frame counters, building/floor context, and other gateway metadata are excluded
from sample bytes. The sample index retains only technical node and radio
configuration labels required to describe natural boundaries.

## Decoding and natural boundaries

The published plotting scripts document how a valid received node packet is
identified and how its node ID and frame number are encoded in the 20-byte
payload. The recipe independently implements only the attribution logic:

- require a 20-byte packet and the documented payload marker;
- decode and validate node ID 1, 2, or 3;
- validate the frame-number field;
- retain the row's numeric `rssi` field unchanged.

Payload bytes are never themselves emitted.

The exhaustive experiment emits one complete source-order sweep timeline for
each fixed node, producing three samples. Individual 50-packet configurations
would be below the natural-sample floor and are not emitted separately. The
week-long experiment emits one source-order timeline per node and fixed channel,
frequency, spreading-factor, bandwidth, coding-rate, and transmit-power
configuration, producing 18 samples.

All 21 groups are at least 5,192 values long, nonconstant, and unique. Observed
RSSI ranges extend from -109 to -69 dBm. Values are exact source integers within
`-128..127` and are written unchanged as two's-complement signed-int8 bytes.
No averaging, quantization, resampling, filling, smoothing, or cross-group
concatenation occurs.

## Verification

Build and verification passed on 2026-08-18. The verifier reparses both complete
CSVs, freshly reapplies packet/node attribution, reconstructs all natural
groups, and byte-compares every output. It additionally enforces signed-int8
metadata, sample sizes, ranges, histograms, nonconstancy, unique hashes, exact
group coverage, aggregate totals, and accepted-recipe size floors.
