# Transient failure: OpenAIR room impulse responses PCM16

- Date: 2026-08-15
- Candidate: `openair_room_impulse_pcm16`
- Intended domain: measured room and architectural acoustic impulse responses
- Intended representation: one native signed PCM16 microphone or ambisonic
  channel per natural response sample

## Why it was considered

Room impulse responses measure an acoustic system rather than carrying
ordinary audio content. Their excitation peak, early reflections, and
reverberant decay would add a variable-length numerical shape distinct from
speech, instrument notes, environmental clips, and continuous accelerometer
signals.

OpenAIR was expected to provide diverse measurements from halls, churches,
rooms, stairwells, tunnels, and other spaces, reportedly under Creative
Commons Attribution-ShareAlike terms. The discovery was designed to verify
those terms rather than relying on that recollection.

## Metadata-only attempt

A user-run bounded discovery queried both official University of York host
variants:

- `https://www.openair.hosted.york.ac.uk/`
- `https://openair.hosted.york.ac.uk/`

It was prepared to preserve official license text, inventory direct WAV/ZIP
resources through HTTP headers, and range-read no more than 4 KiB from direct
WAV files to require integer PCM with exactly 16 stored and valid bits.

Both host variants returned the same 7,644-byte hosting-provider page titled
`Account Suspended`. The page contains no OpenAIR content, license terms,
dataset links, WAV files, archives, or official mirror location. No resource
header could be inspected and no payload was downloaded.

## Decision

Record a transient failure rather than rejecting the impulse-response domain.
Do not substitute an unaffiliated mirror: the original rights evidence and
payload identity cannot currently be established from the official source.

Retry only if:

1. the official University of York OpenAIR host is restored; or
2. an official University of York-maintained replacement exposes both clear
   training-compatible reuse terms and direct impulse-response resources.

Any retry must still preflight source WAV headers and admit only actual PCM16;
24-bit, 32-bit, or floating-point files must not be narrowed to manufacture a
16-bit family.

Evidence:

- `.data/logs/openair_room_impulse_pcm16/discover.latest.log`;
- `.data/discovery/openair_room_impulse_pcm16/pages.json`; and
- `.data/discovery/openair_room_impulse_pcm16/pages/`.
