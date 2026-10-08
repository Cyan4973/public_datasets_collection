#!/usr/bin/env python3
"""CLI for the zenodo_m3d_iwr6843_radar_adc_i16 recipe (download + build steps).

Subcommands
  check-record   validate the Zenodo record JSON (id, license, file, size, md5)
  parse-cd       parse the archive tail, check the pinned central directory, write cd.tsv
  small-list     list (name, start, end, local_file) for every conf/log/legend member
  extract-small  validate + inflate one small member range into the meta dir
  derive         derive the capture selection from the meta dir, write a TSV
  compare        require the derived selection to equal the pinned selection.tsv
  bin-list       list (key, start, end) byte ranges of the selected captures
  check-bin      fully validate one downloaded capture range
  build          emit samples + index from local files only
"""

from __future__ import annotations

import argparse
import array
import hashlib
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import m3d_zip as mz  # noqa: E402

DATASET_ID = "zenodo_m3d_iwr6843_radar_adc_i16"
SERIES_ID = "m3d_iwr6843_hsi_adc_iq_i16"
RECORD_ID = 22811456
FILE_KEY = "dataset_260917.zip"
FILE_MD5 = "ce7e75179bcabac8fd3f934f75a863f4"
SMALL_SLOP = 512
SEL_COLS = ["session", "capture", "frame_loops", "chirps", "label", "bin_name",
            "bin_lho", "bin_csize", "bin_usize", "bin_crc32", "cfg_name", "log_name"]


def local_name(member: str) -> str:
    return member[len(mz.ROOT):].replace("/", "__")


def read_cd(path: Path) -> dict[str, dict]:
    out = {}
    lines = path.read_text().splitlines()
    head = lines[0].split("\t")
    for ln in lines[1:]:
        r = dict(zip(head, ln.split("\t")))
        for k in ("flags", "method", "crc32", "csize", "usize", "lho"):
            r[k] = int(r[k])
        out[r["name"]] = r
    return out


def read_sel(path: Path) -> list[dict]:
    lines = path.read_text().splitlines()
    head = lines[0].split("\t")
    mz.require(head == SEL_COLS, f"{path}: unexpected columns {head}")
    rows = [dict(zip(head, ln.split("\t"))) for ln in lines[1:]]
    for r in rows:
        for k in ("frame_loops", "chirps", "bin_lho", "bin_csize", "bin_usize", "bin_crc32"):
            r[k] = int(r[k])
    return rows


def bin_range(r: dict) -> tuple[int, int]:
    start = r["bin_lho"]
    end = min(start + 30 + len(r["bin_name"].encode()) + r["bin_csize"] + SMALL_SLOP, mz.CD_OFFSET) - 1
    return start, end


# ---------------------------------------------------------------- commands
def cmd_check_record(a) -> None:
    rec = json.loads(Path(a.record).read_text())
    mz.require(int(rec["id"]) == RECORD_ID, f"record id {rec['id']}")
    lic = rec["metadata"]["license"]["id"]
    mz.require(lic == "cc-by-4.0", f"license {lic}")
    mz.require(rec["metadata"].get("access_right", "open") == "open", "record not open access")
    files = {f["key"]: f for f in rec["files"]}
    mz.require(list(files) == [FILE_KEY], f"files {list(files)}")
    f = files[FILE_KEY]
    mz.require(int(f["size"]) == mz.ZIP_SIZE, f"size {f['size']}")
    mz.require(f["checksum"] == "md5:" + FILE_MD5, f"checksum {f['checksum']}")
    print(f"record ok id={RECORD_ID} license={lic} file={FILE_KEY} size={mz.ZIP_SIZE} {f['checksum']}")


def cmd_parse_cd(a) -> None:
    tail = Path(a.tail).read_bytes()
    _cd, entries = mz.parse_central_directory(tail, a.tail_start)
    keys = ["name", "flags", "method", "crc32", "csize", "usize", "lho"]
    with open(a.out, "w") as fh:
        fh.write("\t".join(keys) + "\n")
        for e in entries:
            fh.write("\t".join(str(e[k]) for k in keys) + "\n")
    print(f"central directory ok entries={len(entries)} sha256={mz.CD_SHA256}")


def _is_small(name: str) -> bool:
    return name.endswith(("/conf_file.cfg", "/datacard_record_hdr_LogFile.csv", "_legend.txt"))


def cmd_small_list(a) -> None:
    cd = read_cd(Path(a.cd))
    for name, e in cd.items():
        if _is_small(name):
            end = min(e["lho"] + 30 + len(name.encode()) + e["csize"] + SMALL_SLOP, mz.CD_OFFSET) - 1
            print(f"{name}\t{e['lho']}\t{end}\t{local_name(name)}")


def cmd_extract_small(a) -> None:
    cd = read_cd(Path(a.cd))
    e = cd[a.name]
    blob_path = Path(a.range_file)
    blob = blob_path.read_bytes()
    off = mz.parse_local_header(blob, a.name, e["method"], e["csize"])
    mz.require(off + e["csize"] <= len(blob), f"{a.name}: range too short")
    if e["method"] == 8:
        raw = mz.inflate_member(blob_path, e, off)
    else:
        mz.require(e["method"] == 0, f"{a.name}: method {e['method']}")
        raw = blob[off : off + e["csize"]]
        mz.require(len(raw) == e["usize"] and mz.zlib.crc32(raw) == e["crc32"], f"{a.name}: stored CRC")
    out = Path(a.out)
    out.write_bytes(raw)


def derive_rows(cd: dict[str, dict], meta: Path) -> list[dict]:
    rows = []
    sessions = sorted({n.split("/")[1] for n in cd if n.count("/") >= 2 and n.split("/")[1]})
    for s in sessions:
        legend_name = f"{mz.ROOT}{s}/{s}_legend.txt"
        labels = mz.legend_labels((meta / local_name(legend_name)).read_text(errors="replace")) \
            if legend_name in cd else {}
        caps = sorted({n.split("/")[2] for n in cd
                       if n.startswith(f"{mz.ROOT}{s}/") and n.endswith("/datacard_record_hdr_0ADC_0.bin")})
        for c in caps:
            base = f"{mz.ROOT}{s}/{c}/"
            cfg_name = base + "conf_file.cfg"
            if cfg_name not in cd:
                print(f"skip {s}/{c}: no conf_file.cfg (profile cannot be confirmed)")
                continue
            loops = mz.cfg_frame_loops((meta / local_name(cfg_name)).read_text())
            if loops is None:
                continue
            mz.require(loops in mz.ALLOWED_LOOPS, f"{s}/{c}: unexpected loops {loops}")
            b = cd[base + "datacard_record_hdr_0ADC_0.bin"]
            mz.require(b["method"] == 8, f"{s}/{c}: bin not deflated")
            mz.require(b["usize"] % mz.RECORD_BYTES == 0, f"{s}/{c}: size % 1088 != 0")
            chirps = b["usize"] // mz.RECORD_BYTES
            log_name = base + "datacard_record_hdr_LogFile.csv"
            mz.check_log((meta / local_name(log_name)).read_text(errors="replace"), chirps)
            label = labels.get(c, "")
            mz.require(label != "", f"{s}/{c}: no legend label")
            rows.append({"session": s, "capture": c, "frame_loops": loops, "chirps": chirps,
                         "label": label, "bin_name": b["name"], "bin_lho": b["lho"],
                         "bin_csize": b["csize"], "bin_usize": b["usize"], "bin_crc32": b["crc32"],
                         "cfg_name": cfg_name, "log_name": log_name})
    return rows


def cmd_derive(a) -> None:
    rows = derive_rows(read_cd(Path(a.cd)), Path(a.meta_dir))
    with open(a.out, "w") as fh:
        fh.write("\t".join(SEL_COLS) + "\n")
        for r in rows:
            fh.write("\t".join(str(r[k]) for k in SEL_COLS) + "\n")
    print(f"derived {len(rows)} captures; loops={sorted({r['frame_loops'] for r in rows})}; "
          f"usize={sum(r['bin_usize'] for r in rows)} csize={sum(r['bin_csize'] for r in rows)}")


def cmd_compare(a) -> None:
    d, p = Path(a.derived).read_bytes(), Path(a.pinned).read_bytes()
    if d != p:
        sys.exit(f"FATAL: derived selection differs from pinned {a.pinned}")
    print("selection matches pinned table")


def cmd_bin_list(a) -> None:
    for r in read_sel(Path(a.selection)):
        s, e = bin_range(r)
        print(f"{r['session']}_{r['capture']}\t{s}\t{e}")


def stream_capture(range_file: Path, r: dict, on_payload) -> int:
    blob_head = range_file.open("rb").read(30 + len(r["bin_name"].encode()) + 1024)
    off = mz.parse_local_header(blob_head, r["bin_name"], 8, r["bin_csize"])
    s, e = bin_range(r)
    mz.require(range_file.stat().st_size == e - s + 1, f"{range_file.name}: range size")
    mz.require(off + r["bin_csize"] <= e - s + 1, f"{range_file.name}: range too short")
    n, crc = mz.split_hsi(mz.inflate_iter(range_file, off, r["bin_csize"]), on_payload)
    mz.require(n == r["chirps"], f"{range_file.name}: {n} chirps != {r['chirps']}")
    mz.require(crc == r["bin_crc32"], f"{range_file.name}: CRC-32 mismatch")
    return n


class Stats:
    def __init__(self, out=None):
        self.out = out
        self.h = hashlib.sha256()
        self.lo, self.hi = 32767, -32768
        self.zero_chirps = 0
        self.hist = bytearray(65536)

    def __call__(self, payload):
        b = bytes(payload)
        if self.out is not None:
            self.out.write(b)
        self.h.update(b)
        a = array.array("h")
        a.frombytes(b)
        if sys.byteorder != "little":
            a.byteswap()
        lo, hi = min(a), max(a)
        if lo == 0 and hi == 0:
            self.zero_chirps += 1
        self.lo, self.hi = min(self.lo, lo), max(self.hi, hi)
        hist = self.hist
        for v in a[::8]:
            hist[v & 0xFFFF] = 1

    def distinct_probe(self) -> int:
        return sum(self.hist)


def check_degenerate(st: Stats, chirps: int, key: str) -> None:
    mz.require(st.lo < st.hi, f"{key}: constant sample")
    mz.require(st.zero_chirps * 100 < chirps, f"{key}: {st.zero_chirps} all-zero chirps")
    mz.require(st.distinct_probe() >= 64, f"{key}: too few distinct values ({st.distinct_probe()})")
    mz.require(st.lo > -32768 or st.hi < 32767, f"{key}: full-scale both ways, suspicious")


def cmd_check_bin(a) -> None:
    rows = {f"{r['session']}_{r['capture']}": r for r in read_sel(Path(a.selection))}
    r = rows[a.key]
    st = Stats()
    n = stream_capture(Path(a.range_file), r, st)
    check_degenerate(st, n, a.key)
    print(f"capture ok {a.key} chirps={n} min={st.lo} max={st.hi} zero_chirps={st.zero_chirps}")


def cmd_build(a) -> None:
    data_root = Path(a.data_root)
    meta = Path(a.meta_dir)
    ranges = Path(a.ranges_dir)
    out_dir = Path(a.samples_dir) / SERIES_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = read_sel(Path(a.selection))
    keep = set()
    index_rows = []
    for r in rows:
        key = f"{r['session']}_{r['capture']}"
        cfg = (meta / local_name(r["cfg_name"])).read_text()
        loops = mz.cfg_frame_loops(cfg)
        mz.require(loops == r["frame_loops"], f"{key}: cfg profile/loops mismatch ({loops})")
        mz.check_log((meta / local_name(r["log_name"])).read_text(errors="replace"), r["chirps"])
        dest = out_dir / f"{key}.bin"
        tmp = dest.with_suffix(".bin.tmp")
        with open(tmp, "wb") as fh:
            st = Stats(fh)
            n = stream_capture(ranges / f"{key}.zipmember", r, st)
        check_degenerate(st, n, key)
        size = tmp.stat().st_size
        mz.require(size == n * mz.PAYLOAD_BYTES, f"{key}: output size")
        tmp.replace(dest)
        keep.add(dest.name)
        index_rows.append({
            "dataset_id": DATASET_ID, "series_id": SERIES_ID,
            "sample_path": str(dest.relative_to(data_root)),
            "numeric_kind": "int", "bit_width": 16, "endianness": "little",
            "element_size_bytes": 2, "sample_size_bytes": size, "value_count": size // 2,
            "session": r["session"], "capture": r["capture"], "label": r["label"],
            "frame_loops": r["frame_loops"], "chirps": n,
            "values_per_chirp": mz.VALUES_PER_CHIRP, "min": st.lo, "max": st.hi,
            "sha256": st.h.hexdigest(), "source_member": r["bin_name"],
            "source_crc32": f"{r['bin_crc32']:08x}",
        })
        print(f"sample {key} loops={r['frame_loops']} chirps={n} values={size // 2} "
              f"min={st.lo} max={st.hi} label='{r['label']}'")
    for p in out_dir.iterdir():
        if p.name not in keep:
            print(f"removing stale {p.name}")
            p.unlink()
    idx = Path(a.index)
    idx.parent.mkdir(parents=True, exist_ok=True)
    with open(idx, "w") as fh:
        for row in index_rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    total = sum(r["sample_size_bytes"] for r in index_rows)
    stats = {"samples": len(index_rows), "total_size_bytes": total,
             "total_values": total // 2, "chirps": sum(r["chirps"] for r in index_rows),
             "headers_dropped_bytes": sum(r["chirps"] for r in index_rows) * mz.HEADER_BYTES}
    sp = Path(a.stats)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check-record"); p.add_argument("--record", required=True)
    p = sub.add_parser("parse-cd"); p.add_argument("--tail", required=True)
    p.add_argument("--tail-start", type=int, required=True); p.add_argument("--out", required=True)
    p = sub.add_parser("small-list"); p.add_argument("--cd", required=True)
    p = sub.add_parser("extract-small"); p.add_argument("--cd", required=True)
    p.add_argument("--name", required=True); p.add_argument("--range-file", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("derive"); p.add_argument("--cd", required=True)
    p.add_argument("--meta-dir", required=True); p.add_argument("--out", required=True)
    p = sub.add_parser("compare"); p.add_argument("--derived", required=True)
    p.add_argument("--pinned", required=True)
    p = sub.add_parser("bin-list"); p.add_argument("--selection", required=True)
    p = sub.add_parser("check-bin"); p.add_argument("--selection", required=True)
    p.add_argument("--key", required=True); p.add_argument("--range-file", required=True)
    p = sub.add_parser("build")
    for k in ("selection", "meta-dir", "ranges-dir", "samples-dir", "index", "stats", "data-root"):
        p.add_argument("--" + k, required=True)
    a = ap.parse_args()
    try:
        {"check-record": cmd_check_record, "parse-cd": cmd_parse_cd, "small-list": cmd_small_list,
         "extract-small": cmd_extract_small, "derive": cmd_derive, "compare": cmd_compare,
         "bin-list": cmd_bin_list, "check-bin": cmd_check_bin, "build": cmd_build}[a.cmd](a)
    except mz.FormatError as exc:
        sys.exit(f"FATAL: {exc}")


if __name__ == "__main__":
    main()
