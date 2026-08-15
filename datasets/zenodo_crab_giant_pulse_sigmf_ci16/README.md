# Crab Giant-Pulse SigMF Complex Int16

Collects one coherent radio-astronomy baseband recording containing a giant
pulse from the Crab pulsar, captured by the Dwingeloo radio telescope on
2024-07-30.

The complete `.sigmf-data` file is retained as one natural sample with shape
`[4,000,000, 2]`. The source alternates signed-int16 I and Q ADC components and
explicitly declares `ci16_le`, so output bytes are preserved unchanged.

- center frequency: 410 MHz
- sample rate: 20 MHz
- duration: 0.2 seconds
- primary values: 8,000,000 signed int16 scalars
- primary bytes: 16,000,000

The Zenodo record declares CC BY 4.0, while its embedded SigMF metadata
declares the stricter CC BY-SA 4.0. This recipe conservatively records and
enforces CC BY-SA 4.0.

Run:

```bash
bash datasets/zenodo_crab_giant_pulse_sigmf_ci16/download.sh
bash datasets/zenodo_crab_giant_pulse_sigmf_ci16/build.sh
bash datasets/zenodo_crab_giant_pulse_sigmf_ci16/verify.sh
```
