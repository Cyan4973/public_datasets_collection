#!/usr/bin/env python3
"""Author-time resolver for sources.tsv (run via ../discover.sh; metadata only).

Network I/O goes through the curl CLI (never urllib). For each of the ten QR3 week groups it
lists the detector-1 directory of the primary `l2b-v27-*` pipeline run (the `l2b_retry-*`
side runs are excluded), picks three exposures at evenly spaced observation positions, and
range-probes only the FITS headers (<= 115,200 bytes per file, with If-Match on the listed
ETag) to check the header regime and locate the IMAGE data unit.

  discover.py <scratch_dir> <sources.tsv>
"""
from __future__ import annotations

import html
import json
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spherex_fits as sf  # noqa: E402

BUCKET = "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com"
UA = "openzl-public-datasets-spherex-qr3/1.0"
GROUPS = ["2026W30_1B", "2026W30_2A", "2026W31_1B", "2026W31_2A", "2026W32_1A",
          "2026W32_2A", "2026W33_1A", "2026W33_2A", "2026W34_1A", "2026W34_2A"]
PER_GROUP = 3
COLUMNS = ["name", "key", "url", "etag", "object_size", "last_modified", "data_offset", "prefix_bytes",
           "header_sha256", "week_group", "pipeline_run", "obsid", "expidn", "date_obs", "crval1", "crval2",
           "sps_elon", "sps_elat", "xposure"]


def curl(args: list[str], out: Path | None = None) -> bytes:
    cmd = ["curl", "--fail", "--silent", "--show-error", "--max-time", "120", "--retry", "5",
           "--retry-delay", "3", "--user-agent", UA] + args
    if out is not None:
        cmd += ["--output", str(out)]
        subprocess.run(cmd, check=True)
        return out.read_bytes()
    return subprocess.run(cmd, check=True, capture_output=True).stdout


def list_prefix(prefix: str, delimiter: bool) -> tuple[list[str], list[dict]]:
    prefixes, objects, token = [], [], ""
    while True:
        url = f"{BUCKET}/?list-type=2&max-keys=1000&prefix={urllib.parse.quote(prefix, safe='/')}"
        if delimiter:
            url += "&delimiter=/"
        if token:
            url += "&continuation-token=" + urllib.parse.quote(token, safe="")
        text = curl([url]).decode("utf-8")
        prefixes += [html.unescape(p) for p in re.findall(r"<CommonPrefixes><Prefix>(.*?)</Prefix>", text)]
        for block in re.findall(r"<Contents>(.*?)</Contents>", text, flags=re.S):
            get = lambda tag: html.unescape(re.search(f"<{tag}>(.*?)</{tag}>", block).group(1))  # noqa: E731
            objects.append({"key": get("Key"), "size": int(get("Size")), "etag": get("ETag").strip('"'),
                            "last_modified": get("LastModified")})
        m = re.search(r"<NextContinuationToken>(.*?)</NextContinuationToken>", text)
        if not m:
            return prefixes, objects
        token = html.unescape(m.group(1))


def probe(obj: dict, scratch: Path) -> tuple[dict | None, list[str], bytes]:
    name = obj["key"].rsplit("/", 1)[1]
    for size in (57600, 115200):
        buf = curl(["--range", f"0-{size - 1}", "--header", f'If-Match: "{obj["etag"]}"',
                    f"{BUCKET}/{obj['key']}"], scratch / f"{name}.hdr")
        try:
            info = sf.walk_prefix(buf)
        except sf.FitsError as exc:
            if "truncated" in str(exc) and size == 57600:
                continue
            return None, [str(exc)], buf
        return info, sf.check_regime(info, name), buf
    return None, ["header longer than 115,200 bytes"], b""


def main() -> None:
    scratch, sources = Path(sys.argv[1]), Path(sys.argv[2])
    scratch.mkdir(parents=True, exist_ok=True)
    top, _ = list_prefix("qr3/level2/", True)
    found = sorted(p.split("/")[2] for p in top if p.count("/") == 3)
    if found != GROUPS:
        raise SystemExit(f"FATAL week groups changed: {found}")
    rows, summary = [], {}
    for group in GROUPS:
        runs, _ = list_prefix(f"qr3/level2/{group}/", True)
        primary = [r for r in runs if re.fullmatch(rf"qr3/level2/{group}/l2b-v27-\d{{4}}-\d{{3}}/", r)]
        if len(primary) != 1:
            raise SystemExit(f"FATAL {group}: expected one l2b-v27 run, got {runs}")
        run = primary[0].split("/")[3]
        _, objs = list_prefix(f"{primary[0]}1/", False)
        by_obs: dict[str, list[dict]] = {}
        for o in objs:
            name = o["key"].rsplit("/", 1)[1]
            m = sf.NAME_RE.match(name)
            if not m or m["group"] != group or m["ver"] != run or m["det"] != "1":
                raise SystemExit(f"FATAL unexpected object in detector-1 listing: {o['key']}")
            by_obs.setdefault(m["obs"], []).append(o)
        obs_sorted = sorted(by_obs)
        summary[group] = {"run": run, "d1_objects": len(objs), "observations": len(obs_sorted),
                          "object_size_min": min(o["size"] for o in objs),
                          "object_size_max": max(o["size"] for o in objs)}
        chosen: set[str] = set()
        for k in range(PER_GROUP):
            idx = int((k + 0.5) * len(obs_sorted) / PER_GROUP)
            for step in range(len(obs_sorted)):
                obs = obs_sorted[(idx + step) % len(obs_sorted)]
                if obs in chosen:
                    continue
                exps = sorted(by_obs[obs], key=lambda o: o["key"])
                pref = [o for o in exps if f"_{obs}_{k + 1}D1_" in o["key"]]
                obj = (pref or exps)[0]
                info, bad, buf = probe(obj, scratch)
                if bad:
                    print(f"skip {obj['key']}: {bad}", file=sys.stderr)
                    continue
                chosen.add(obs)
                h = info["image"]
                name = obj["key"].rsplit("/", 1)[1]
                rows.append({
                    "name": name, "key": obj["key"], "url": f"{BUCKET}/{obj['key']}", "etag": obj["etag"],
                    "object_size": obj["size"], "last_modified": obj["last_modified"],
                    "data_offset": info["data_offset"], "prefix_bytes": info["prefix_bytes"],
                    "header_sha256": sf.sha256_bytes(buf[:info["data_offset"]]), "week_group": group,
                    "pipeline_run": run, "obsid": h["OBSID"], "expidn": h["EXPIDN"], "date_obs": h["DATE-OBS"],
                    "crval1": h["CRVAL1"], "crval2": h["CRVAL2"], "sps_elon": h["SPS_ELON"],
                    "sps_elat": h["SPS_ELAT"], "xposure": h["XPOSURE"],
                })
                print(f"pick {name} data_offset={info['data_offset']} ra={h['CRVAL1']:.3f} dec={h['CRVAL2']:.3f}",
                      file=sys.stderr)
                break
            else:
                raise SystemExit(f"FATAL {group}: not enough exposures in regime")
    with sources.open("w", encoding="utf-8") as fh:
        fh.write("\t".join(COLUMNS) + "\n")
        for r in rows:
            fh.write("\t".join(str(r[c]) for c in COLUMNS) + "\n")
    (scratch / "population.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary, indent=1))
    print(f"rows={len(rows)} prefix_bytes_total={sum(r['prefix_bytes'] for r in rows)}")


if __name__ == "__main__":
    main()
