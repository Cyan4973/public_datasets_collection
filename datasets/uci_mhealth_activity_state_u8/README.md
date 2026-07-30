# UCI MHEALTH activity-state timelines (u8)

Accepted recipe for the numeric activity-ID field in the MHEALTH Dataset. The
source contains ten continuous subject recordings sampled at 50 Hz. Its final
column is the documented activity label: `0` for the null state and `1..12`
for protocol activities.

The recipe emits one `uint8` state timeline per complete subject recording.
It does not emit physiological sensor channels, concatenate subjects, remap
activity IDs, or treat ZIP bytes as numeric material.

The official UCI dataset record identifies the license as CC BY 4.0, which
permits training and commercial reuse with attribution. Preserve the UCI and
creator citation, including DOI `10.24432/C5TW22`.

## Run

From the repository root:

```bash
bash datasets/uci_mhealth_activity_state_u8/download.sh
```

After the user-run download succeeds, the local-only steps are:

```bash
bash datasets/uci_mhealth_activity_state_u8/build.sh
bash datasets/uci_mhealth_activity_state_u8/verify.sh
```
