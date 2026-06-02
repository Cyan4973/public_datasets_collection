# seismic_waveform_i32

- Date: 2026-06-01
- Status: needs_tooling
- Candidate dataset: IRIS seismic waveform windows
- Source: https://service.iris.edu/irisws/timeseries/
- Why it looked promising: Integer seismic counts are on-scope numeric content.
- Failure class: missing_selection_tooling
- What happened: The external exact ID is a curated set of event windows. Porting it cleanly needs a reusable source-window selection workflow in addition to ASCII parse logic.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest where present.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Record as tooling-limited for now.
- Retry conditions: Retry after adding a reviewed event-window selection helper or replacing this with a more direct raw waveform recipe.
