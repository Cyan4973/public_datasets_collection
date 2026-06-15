# 16-bit Next Hunt Error Triage

User-run downloads were inspected locally. No dataset network fetches were run by the agent.

| dataset_id | observed local state | conclusion | next action |
|---|---|---|---|
| `nsynth_test_notes_i16` | `nsynth-test.jsonwav.tar.gz` exists and passed archive semantic validation with `4096` WAV files. Build and verify succeeded locally. | Accepted pending final review of fixed-size-sample weakness. | No download rerun needed. |
| `dwd_radolan_rw_precip_i16` | The first run failed because the script looked for `.gz`; after patching to `.bz2`, the user reran download and local build/verify succeeded for `192` RADOLAN composites. | Accepted pending final review of fixed-size-sample weakness. | No download rerun needed. |
| `sdss_corrected_frame_fits_i16` | `download_plan.tsv` is empty. All selected SDSS directory URLs returned HTTP 503. No FITS payload exists locally. | Deferred from active benchmark because the current access strategy is not locally reproducible. | Reattempt only with exact stable direct frame URLs and local validation that selected files are `BITPIX = 16`. |

Current material state is written in:

- `reports/16bit_next_hunt_20260614_dataset_state.md`
- `reports/16bit_next_hunt_20260614_dataset_state.tsv`
- `reports/16bit_next_hunt_20260614_dataset_state.json`
