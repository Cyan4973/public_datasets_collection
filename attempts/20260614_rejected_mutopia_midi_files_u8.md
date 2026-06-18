# Rejected: mutopia_midi_files_u8

Date: 2026-06-14

The Mutopia Project repository-archive candidate was rejected before build.

Reason:

- The downloaded `MutopiaProject-master.zip` archive contains zero `.mid` or `.midi` payload files.
- The current recipe shape therefore cannot produce Standard MIDI File samples.
- A different official Mutopia endpoint or a different symbolic-music source would be required.

Cleanup status:

- Rejection evidence is preserved in `reports/8bit_variety_hunt_20260614_errors.md`.
- The empty `staging/mutopia_midi_files_u8/` directory was removed.
- Generated failed-download artifacts under `.data/*/mutopia_midi_files_u8/`
  were removed after rejection so future audits do not treat the candidate as
  unfinished local work.
