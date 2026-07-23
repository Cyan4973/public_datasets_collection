#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="polyhaven_hdri_exr_f32"
SERIES_ID="hdri_float_planes_f32"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1

python3 - <<'PY'
from pathlib import Path
import os, struct, zlib, json, shutil, statistics, re
from collections import Counter

repo_root = Path(os.environ.get("REPO_ROOT", os.getcwd()))
data_dir = os.environ.get("DATA_DIR", ".data")
dataset_id = "polyhaven_hdri_exr_f32"
series_id = "hdri_float_planes_f32"
data_root = repo_root / data_dir
download_dir = data_root / "downloads" / dataset_id
# Also check f16 download dir as fallback source for reclassification
download_dir_f16 = data_root / "downloads" / "polyhaven_hdri_exr_f16"
extracted_dir = data_root / "extracted" / dataset_id
filtered_dir = data_root / "filtered" / dataset_id
index_dir = data_root / "index" / dataset_id
samples_dir = data_root / "samples" / dataset_id
out_dir = samples_dir / series_id

def clean_name(v, fallback="sample"):
    v = re.sub(r"[^A-Za-z0-9._-]+", "_", v).strip("._")
    return v or fallback

# Clean output
if out_dir.exists():
    shutil.rmtree(out_dir)
out_dir.mkdir(parents=True, exist_ok=True)
filtered_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

def parse_exr_header(data):
    if len(data) < 16 or struct.unpack_from("<I", data, 0)[0] != 20000630:
        return None
    offset=8
    compression=-1
    channels=[]
    data_window=None
    while offset < len(data):
        end=data.find(b"\0", offset)
        if end<0: return None
        name=data[offset:end].decode('ascii','replace')
        offset=end+1
        if not name:
            break
        end=data.find(b"\0", offset)
        if end<0: return None
        atype=data[offset:end].decode('ascii','replace')
        offset=end+1
        if offset+4>len(data): return None
        size=struct.unpack_from("<I", data, offset)[0]
        offset+=4
        value=data[offset:offset+size]
        offset+=size
        if name=="compression":
            compression=value[0] if value else -1
        elif name=="channels":
            pos=0
            while pos < len(value):
                en=value.find(b"\0", pos)
                if en<0: break
                ch=value[pos:en].decode('ascii','replace')
                pos=en+1
                if not ch: break
                if pos+16>len(value): break
                pt=struct.unpack_from("<I", value, pos)[0]
                # pixel type: 0=UINT,1=HALF,2=FLOAT
                pos+=16
                channels.append((ch,pt))
        elif name=="dataWindow":
            if len(value)==16:
                data_window=struct.unpack("<iiii", value)
    return offset, compression, channels, data_window

def build_one_exr(path: Path, rows, data_root, out_dir):
    data=path.read_bytes()
    parsed=parse_exr_header(data)
    if not parsed:
        return 0
    header_end, compression, channels, data_window = parsed
    if not channels or not data_window:
        return 0
    # Accept only FLOAT (type 2)
    if any(pt != 2 for _, pt in channels):
        return 0
    # Accept only ZIP (3) and ZIPS (2) for now (zlib-compressed)
    if compression not in (2,3):
        # PIZ (4) needs wavelet decoder, skip for now
        return 0
    x_min,y_min,x_max,y_max=data_window
    width=x_max-x_min+1
    height=y_max-y_min+1
    if width<=0 or height<=0:
        return 0
    lines_per_chunk = 1 if compression==2 else 16
    chunk_count = (height + lines_per_chunk -1)//lines_per_chunk
    if header_end + chunk_count*8 > len(data):
        return 0
    chunk_offsets=[struct.unpack_from("<Q", data, header_end+i*8)[0] for i in range(chunk_count)]
    # Prepare planes
    planes={name: bytearray() for name,_ in channels}
    channel_count=len(channels)
    # Process each chunk
    for idx, co in enumerate(chunk_offsets):
        if co+8 > len(data):
            return 0
        y, packed_size = struct.unpack_from("<iI", data, co)
        payload=data[co+8:co+8+packed_size]
        # Decompress
        try:
            dec=zlib.decompress(payload)
        except Exception:
            return 0
        # Determine lines in this chunk (last may be smaller)
        lines_in_this = lines_per_chunk
        if y + lines_in_this > height:
            lines_in_this = height - y
        expected = width * lines_in_this * channel_count * 4
        if len(dec) != expected:
            # Some EXRs have 32-bit offset? Check
            return 0
        # Layout: channel-separated per scanline? For ZIP, data is stored as
        # for each channel, contiguous. So split.
        # dec layout: for line 0 channel0, line0 channel1, etc? Actually spec: each scanline block contains
        # all channels for those lines, with each channel's data contiguous.
        # So total per channel = width * lines_in_this *4
        pos=0
        for name,_ in channels:
            chunk_plane = dec[pos:pos+width*lines_in_this*4]
            planes[name].extend(chunk_plane)
            pos+=width*lines_in_this*4
    # Validate
    for name, buf in planes.items():
        if len(buf) != width*height*4:
            return 0
    # Write samples
    for name, buf in planes.items():
        # Reject constant (degenerate) - check first 4 bytes repeated?
        # Simple check: all bytes same?
        if len(set(buf))<=1:
            continue
        # Write
        sample_name=f"{path.stem}_{name}"
        out_path = out_dir / f"{len(rows)+1:06d}_{clean_name(sample_name)}.bin"
        out_path.write_bytes(bytes(buf))
        row={
            "dataset_id": dataset_id,
            "series_id": series_id,
            "role": "primary",
            "sample_path": out_path.relative_to(data_root).as_posix(),
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": len(buf),
            "value_count": len(buf)//4,
            "sample_format": "raw OpenEXR FLOAT32 channel plane",
            "sample_geometry": "2d_raster",
            "sample_rank": 2,
            "sample_shape": [height, width],
            "sample_axes": ["y","x"],
            "source_path": path.relative_to(data_root).as_posix(),
            "container_format": "openexr",
            "channel": name,
            "compression": "zip" if compression==3 else "zips",
            "width": width,
            "height": height,
        }
        rows.append(row)
    return len(planes)

# Collect exr files from both f32 and f16 download dirs (reclassification)
roots=[download_dir, download_dir_f16]
files=[]
seen=set()
for root in roots:
    if not root.exists():
        continue
    for p in sorted(root.rglob("*.exr")):
        rp=p.resolve()
        if rp in seen:
            continue
        seen.add(rp)
        files.append(p)

print(f"found {len(files)} exr files")
rows=[]
for p in files:
    try:
        n=build_one_exr(p, rows, data_root, out_dir)
        if n:
            print(f"accepted {p.name} -> {n} planes")
    except Exception as e:
        print(f"error {p.name}: {e}")

if not rows:
    raise SystemExit("no native 32-bit samples accepted")

sizes=[r["sample_size_bytes"] for r in rows]
values=[r["value_count"] for r in rows]
total=sum(sizes)
if total < 102400:
    raise SystemExit(f"below floor bytes {total}")
if sum(values) < 10000:
    raise SystemExit(f"below floor values {sum(values)}")
if statistics.median(values) < 1000:
    raise SystemExit(f"median below floor {statistics.median(values)}")

stats={
    "dataset_id": dataset_id,
    "series_id": series_id,
    "format": "exr",
    "sample_count": len(rows),
    "primary_bytes": total,
    "primary_values": sum(values),
    "min_sample_bytes": min(sizes),
    "median_sample_bytes": statistics.median(sizes),
    "max_sample_bytes": max(sizes),
}
(filtered_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True)+"\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for r in rows:
        fh.write(json.dumps(r, sort_keys=True)+"\n")
print(f"built samples={len(rows)} primary_bytes={total} median={statistics.median(sizes)}")
PY
