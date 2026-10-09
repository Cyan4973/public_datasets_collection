#!/usr/bin/env bash
# Discovery helper for the privacy screen (not part of the acceptance path).
# For each burst in <sources.candidate.tsv>, range-GET the first 32 KiB of the
# dataset's own gallery JPEG (gs://hdrplusdata/20171106/gallery_20171023/
# <burst>.jpg) and extract the embedded EXIF thumbnail JPEG to <outdir>/<burst>.jpg
# for human review. About 1.3 MB of traffic for 40 bursts.
set -euo pipefail
cand="$1"; outdir="$2"
mkdir -p "$outdir"
tail -n +2 "$cand" | cut -f1 | while read -r burst; do
  [ -s "$outdir/$burst.jpg" ] && continue
  curl -fsS --retry 5 --max-time 60 -r 0-32767 -o "$outdir/$burst.head" \
    "https://storage.googleapis.com/hdrplusdata/20171106/gallery_20171023/$burst.jpg"
  python3 -I - "$outdir/$burst.head" "$outdir/$burst.jpg" <<'PY'
import struct, sys
d = open(sys.argv[1], "rb").read()
# APP1 Exif: FFD8 FFE0(JFIF) ... FFE1 len "Exif\0\0" TIFF; thumbnail = IFD1 tags 513/514
pos = 2
tiff = None
while pos + 4 <= len(d) and d[pos] == 0xFF:
    m, L = d[pos + 1], struct.unpack_from(">H", d, pos + 2)[0]
    if m == 0xE1 and d[pos + 4:pos + 10] == b"Exif\0\0":
        tiff = pos + 10
        break
    pos += 2 + L
if tiff is None:
    raise SystemExit(f"no Exif APP1 in {sys.argv[1]}")
bo = "<" if d[tiff:tiff + 2] == b"II" else ">"
ifd0 = struct.unpack_from(bo + "I", d, tiff + 4)[0]
n0 = struct.unpack_from(bo + "H", d, tiff + ifd0)[0]
ifd1 = struct.unpack_from(bo + "I", d, tiff + ifd0 + 2 + 12 * n0)[0]
if not ifd1:
    raise SystemExit("no IFD1 thumbnail")
n1 = struct.unpack_from(bo + "H", d, tiff + ifd1)[0]
tags = {}
for k in range(n1):
    tag, typ, cnt, val = struct.unpack_from(bo + "HHII", d, tiff + ifd1 + 2 + 12 * k)
    tags[tag] = val
off, ln = tags[513], tags[514]
thumb = d[tiff + off:tiff + off + ln]
if len(thumb) != ln or thumb[:2] != b"\xff\xd8":
    raise SystemExit("thumbnail outside probe or not JPEG")
open(sys.argv[2], "wb").write(thumb)
PY
  rm -f "$outdir/$burst.head"
done
ls "$outdir" | wc -l
