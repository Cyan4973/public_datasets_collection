#!/usr/bin/env python3
"""Discovery helper for discover.sh (metadata only).

  discover.py obsid-batches <observations.json>   -> comma-joined PUBLIC SUB2048 obsids, 20 per line
  discover.py candidates <discover_dir>           -> TSV of every seg001 NRS1 x1dints product
  discover.py finalize <discover_dir> <sources.tsv>
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import x1dints  # noqa: E402

SUFFIX = "-seg001_nrs1_x1dints.fits"
FLUX_BYTE_BUDGET = 500_000_000
COLUMNS = [
    "filename", "url", "size_bytes", "caom_size_bytes", "etag", "last_modified", "obsid", "obs_id", "program",
    "observation", "visit", "exposure", "target", "target_key", "date_obs", "time_obs", "nints",
    "intstart", "intend", "exsegtot", "ngroups", "readpatt", "cal_ver", "sdp_ver", "crds_ctx",
    "extract1d_data_offset", "naxis1", "naxis2", "flux_col_offset", "nbins", "flux_bytes",
]


def load_obs(path):
    with open(path) as fh:
        d = json.load(fh)
    if d.get("status") != "COMPLETE":
        raise SystemExit(f"observation query status {d.get('status')}")
    return d["data"]


def public_sub2048(rows):
    return [r for r in rows if r["dataRights"] == "PUBLIC" and r["obs_id"].endswith("-sub2048")]


def target_key(name):
    key = re.sub(r"[^a-z0-9+]", "", name.lower())
    key = re.sub(r"(updated|revised|copy)$", "", key)
    key = re.sub(r"^v(v\d)", r"\1", key)  # 'V-V1298-TAU' -> 'v1298tau'
    return key


def cmd_obsid_batches(path):
    ids = sorted(str(r["obsid"]) for r in public_sub2048(load_obs(path)))
    for i in range(0, len(ids), 20):
        print(",".join(ids[i:i + 20]))


def candidates(ddir):
    obs = {str(r["obsid"]): r for r in public_sub2048(load_obs(os.path.join(ddir, "observations.json")))}
    seen = {}
    for path in sorted(glob.glob(os.path.join(ddir, "products", "batch_*.json"))):
        with open(path) as fh:
            d = json.load(fh)
        if d.get("status") != "COMPLETE":
            raise SystemExit(f"{path}: status {d.get('status')}")
        for p in d["data"]:
            fn = p["productFilename"]
            if not fn.endswith(SUFFIX) or p["dataRights"] != "PUBLIC":
                continue
            parent = str(p["parent_obsid"])
            if parent not in obs:
                continue
            seen.setdefault(fn, (int(p["size"]), parent, obs[parent]))
    return seen


def cmd_candidates(ddir):
    print("filename\tsize_bytes\tobsid\tobs_id\ttarget")
    for fn, (size, parent, o) in sorted(candidates(ddir).items()):
        print(f"{fn}\t{size}\t{parent}\t{o['obs_id']}\t{o['target_name']}")


def http_meta(hdir):
    for path in sorted(glob.glob(os.path.join(hdir, "*.http"))):
        with open(path, encoding="latin-1") as fh:
            status, headers = x1dints.parse_http_headers(fh.read())
        if status == 206:
            total = int(headers["content-range"].rsplit("/", 1)[1])
            return headers.get("etag", "").strip('"'), headers.get("last-modified", ""), total
    raise SystemExit(f"{hdir}: no 206 header dump")


def cmd_finalize(ddir, out_path):
    rows = []
    rejected = []
    for fn, (size, parent, o) in sorted(candidates(ddir).items()):
        hdir = os.path.join(ddir, "hdr", fn)
        with open(os.path.join(hdir, "layout.json")) as fh:
            lay = json.load(fh)
        p = lay["primary"]
        etag, lastmod, total = http_meta(hdir)
        listed = size
        size = total  # the served object is authoritative; Caom size lags reprocessing
        problems = x1dints.regime_problems(lay, fn, size)
        e = lay["extract1d"]
        if problems:
            rejected.append((fn, problems))
            continue
        foff, nbins, _, _ = x1dints.flux_layout(lay)
        rows.append({
            "filename": fn, "url": f"https://mast.stsci.edu/api/v0.1/Download/file?uri=mast:JWST/product/{fn}",
            "size_bytes": size, "caom_size_bytes": listed, "etag": etag, "last_modified": lastmod, "obsid": parent,
            "obs_id": o["obs_id"], "program": p["PROGRAM"], "observation": p["OBSERVTN"],
            "visit": p["VISIT"], "exposure": p["EXPOSURE"], "target": o["target_name"],
            "target_key": target_key(o["target_name"]), "date_obs": p["DATE-OBS"],
            "time_obs": p["TIME-OBS"], "nints": p["NINTS"], "intstart": p["INTSTART"],
            "intend": p["INTEND"], "exsegtot": p["EXSEGTOT"], "ngroups": p["NGROUPS"],
            "readpatt": p["READPATT"], "cal_ver": p["CAL_VER"], "sdp_ver": p["SDP_VER"],
            "crds_ctx": p["CRDS_CTX"], "extract1d_data_offset": e["data_offset"],
            "naxis1": e["naxis1"], "naxis2": e["naxis2"], "flux_col_offset": foff, "nbins": nbins,
            "flux_bytes": 8 * nbins * e["naxis2"],
        })
    for fn, problems in rejected:
        print(f"rejected {fn}: {'; '.join(problems)}", file=sys.stderr)
    # One product per target so that no star contributes more than one segment: prefer the
    # newest calibration (already-reprocessed products are least likely to change before the
    # download), then the earliest observation (lowest program/observation/visit group). Then
    # drop the largest products until the FLUX byte budget holds (keeps the target spread
    # instead of a few long visits).
    def cal_key(r):
        return tuple(-int(x) for x in r["cal_ver"].split("."))

    by_target = {}
    for r in sorted(rows, key=lambda r: (cal_key(r), r["filename"])):
        by_target.setdefault(r["target_key"], r)
    chosen = sorted(by_target.values(), key=lambda r: r["flux_bytes"])
    total = 0
    selected = []
    for r in chosen:
        if total + r["flux_bytes"] > FLUX_BYTE_BUDGET:
            print(f"budget-skip {r['filename']} flux_bytes={r['flux_bytes']}", file=sys.stderr)
            continue
        total += r["flux_bytes"]
        selected.append(r)
    selected.sort(key=lambda r: r["filename"])
    with open(out_path, "w") as fh:
        fh.write("\t".join(COLUMNS) + "\n")
        for r in selected:
            fh.write("\t".join(str(r[c]) for c in COLUMNS) + "\n")
    print(
        f"eligible={len(rows)} rejected={len(rejected)} targets={len(by_target)} selected={len(selected)} "
        f"programs={len({r['program'] for r in selected})} flux_bytes={total} "
        f"nbins={sorted({r['nbins'] for r in selected})} cal_ver={sorted({r['cal_ver'] for r in selected})}",
        file=sys.stderr,
    )


def main(argv):
    if argv[1] == "obsid-batches":
        cmd_obsid_batches(argv[2])
    elif argv[1] == "candidates":
        cmd_candidates(argv[2])
    elif argv[1] == "finalize":
        cmd_finalize(argv[2], argv[3])
    else:
        raise SystemExit(f"unknown command {argv[1]}")


if __name__ == "__main__":
    main(sys.argv)
