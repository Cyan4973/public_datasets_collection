# Rejected: UZH/RPG DAVIS event polarity uint8

- Date: 2026-07-30
- Status: rejected
- Candidate dataset ID: `uzh_rpg_davis_event_polarity_u8`
- Source: <https://rpg.ifi.uzh.ch/davis_data.html>
- Intended material: native binary polarity values from asynchronous DAVIS
  event-camera recordings, one complete recording per natural sample.

## Why it looked promising

Event polarity streams would add a genuinely new asynchronous sensing domain
to the 8-bit corpus. The official catalog exposes text-format ZIP releases for
many complete recordings, including small bounded sequences such as
`slider_depth`, `slider_hdr_far`, `slider_hdr_close`, `slider_far`, and
`slider_close`. Their reported archive sizes range from roughly 8 MB to 24 MB,
so a multi-recording subset would be operationally bounded and require no ROS
decoder.

## License result

A metadata-only user-run probe fetched the official catalog page and inspected
object headers without downloading any recording payloads. The official page
states:

> This datasets are released under the Creative Commons license
> (CC BY-NC-SA 3.0), which is free for non-commercial use (including research).

The NonCommercial restriction does not satisfy this corpus's requirement for
training material that can be reused without a commercial-use prohibition.
The ShareAlike condition would also require additional downstream analysis,
but the NonCommercial term is independently disqualifying.

## Decision

Reject this source before acquisition. No sequence ZIP or event payload was
downloaded. Do not retry the UZH/RPG DAVIS collection unless the rightsholder
publishes the relevant recordings under a license that permits commercial
reuse, such as CC BY or CC0.

The event-camera polarity material type remains worthwhile if a different
source with an explicit permissive license and bounded direct downloads can be
identified.
