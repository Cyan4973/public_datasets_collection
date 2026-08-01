# V16 Beacon NB-IoT SigMF Complex Int16

Collects two coherent software-defined-radio recordings of a V16 automotive
emergency beacon's NB-IoT uplink and downlink. Both Zenodo records declare CC
BY 4.0 and provide raw SigMF `ci16_le` data.

Each complete `.sigmf-data` file is one natural sample with shape
`[complex_sample, component_iq]`. The raw stream alternates signed-int16 I and
Q ADC components; no demodulation, filtering, conversion, or concatenation is
performed.

- uplink: 832.3 MHz center frequency
- downlink: 791.3 MHz center frequency
- sample rate: 320 kHz
- total raw primary bytes: 877,648,544

Run:

```bash
bash datasets/zenodo_v16_nb_iot_sigmf_ci16/download.sh
bash datasets/zenodo_v16_nb_iot_sigmf_ci16/build.sh
bash datasets/zenodo_v16_nb_iot_sigmf_ci16/verify.sh
```

The downloader validates record licenses, exact file sizes, Zenodo MD5 values,
and the stronger SigMF-declared SHA-512 digests.
