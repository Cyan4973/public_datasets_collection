# musopen_chopin_solo_piano_pcm_i16

Musopen "Set Chopin Free" solo-piano recordings (CC0): the Prelude and Etude
tracks whose FLAC STREAMINFO is 44.1 kHz / stereo / 16-bit (minus one band-limited track, see below), decoded bit-exact
to raw little-endian int16 interleaved stereo PCM. One sample per complete
piece: 39 pieces, 4,658.7 s (about 77.6 min), 410,896,576 values,
821,793,152 bytes.

| group | pieces | performer (FLAC tag) |
|---|---|---|
| Preludes Op. 28 nos. 1-24 | 24 | Jeannette Fang |
| Preludes B. 86, Op. 45, "no. 27" | 3 | Jeannette Fang |
| Etudes Op. 25 nos. 1-12 | 12 | Edward Neeman |

Pieces run from 32 s to 366 s (2.8 M to 32.4 M values, median about 9.3 M).

## Source and selection

- Bulk source: Internet Archive item
  [musopen-chopin-complete-works-flac](https://archive.org/details/musopen-chopin-complete-works-flac)
  (214 FLAC tracks: 152 16-bit, 62 24-bit, lossless XLD transcodes of
  Musopen's ALAC release, plus the Musopen booklet). Per-file md5 values come
  from the item metadata JSON.
- Selection (`scripts/discover.sh`): all 52 FLACs named Prelude/Etude; read
  STREAMINFO from an 8 KiB range request; keep 44100 Hz / 2 ch / 16 bps: 40
  files. The 12 Op. 10 Etudes are 48 kHz and are excluded. No Prelude or Etude
  is 24-bit or 96 kHz. The Cello Sonata and every other genre are out of scope.
- Spectral audit (ffmpeg `highpass` x3 + `astats`, after the first build):
  39 pieces show a smooth high-band noise floor, -79 to -100 dB above
  15 kHz and -89 to -109 dB above 18 kHz. Etude B. 130, the only Donald
  Betts track, measures -116 dB above 15 kHz and digital zero above 18 kHz.
  That brick-wall cutoff is the signature of a lossy or low-passed master, so
  it is excluded (`EXCLUDED` in `scripts/musopen_chopin.py`). 39 files are
  kept: two complete opus sets and three standalone Preludes.
  The result is pinned in `scripts/pinned_files.tsv` (IA name, size, md5,
  total_samples, STREAMINFO MD5, artist tag).
- Why only Preludes and Etudes: the full 16-bit/44.1 kHz population is 110
  pieces, about 3.95 GB of PCM, so it is over the 1 GB cap. Preludes and
  Etudes form a complete, genre-defined subset under the cap.

## Rights

The license is CC0 1.0. `download.sh` fetches and checks each piece of evidence:

1. The 2013 Set Chopin Free Kickstarter page, as a pinned Wayback snapshot.
   Its FAQ says: "What license will the music recordings be released under?
   Like all the previous music we released, we will be using Creative Common's
   CC0 dedication, a public domain dedication".
2. Musopen's first-party IA item
   [musopen-chopin](https://archive.org/details/musopen-chopin) (uploader
   aaron@musopen.org, licenseurl CC0 1.0). MusicBrainz release
   ab46c4ff-af73-4ed4-bbfb-665d6358b7ec links to it as "download for free".
   That release's release group (45aa5c1a-...) is the one embedded in the
   FLAC tags (LABEL=Musopen).
3. The bulk item declares licenseurl CC0 1.0. Its booklet title page reads
   "SET FREE BY MUSOPEN.ORG".
4. Wikimedia Commons, Category:Set Chopin Free, lists the same Edward Neeman
   Op. 25 recordings as public domain (PD-author Musopen).

Caveat: the bulk item is a 2026 third-party upload. The first-party item
holds an earlier, smaller edition (no Etudes; some Preludes combined or
edited differently). So the Jeannette Fang Prelude files are covered by the
project-wide CC0 commitment and the item's CC0 declaration, not by a
per-file first-party page. musopen.org returns 403 to scripted clients.

## Conversion

`ffmpeg -i x.flac -map 0:a:0 -vn -f s16le -acodec pcm_s16le x.bin`, with no
resampling, remixing or dither. The build asserts two things for each piece:

- decoded bytes == total_samples x 2 channels x 2 bytes
- MD5(decoded PCM) == the FLAC STREAMINFO MD5 signature, which proves a
  bit-exact lossless decode

Leading and trailing digital silence, zero fraction, clipping and distinct
value count are recorded per piece in the index. A piece is fatal if it is
constant, has more than 50% zero values, has more than 50% edge silence, is
dual-mono, has no odd values (padded below 16-bit), or has fewer than 1024
distinct values.

`verify.sh` re-parses STREAMINFO with its own parser, re-checks length and
the MD5 signature for every sample, and recomputes min/max, zero fraction and
edge silence against the index.

## Usage

```bash
bash staging/musopen_chopin_solo_piano_pcm_i16/download.sh   # ~277.9 MB
bash staging/musopen_chopin_solo_piano_pcm_i16/build.sh      # needs ffmpeg
bash staging/musopen_chopin_solo_piano_pcm_i16/verify.sh
```
