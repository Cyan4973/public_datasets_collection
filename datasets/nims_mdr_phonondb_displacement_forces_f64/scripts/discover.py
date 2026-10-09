#!/usr/bin/env python3
"""Discovery helper that documents how sources.tsv was resolved (not run by download.sh).

Step 1 (oai): harvest MDR OAI-PMH ListRecords (metadataPrefix=jpcoar_2.0) over a
  datestamp window and keep records whose title starts with
  "Ab-initio phonon calculation for" and that carry a phonopy_params.yaml.xz file.
  The MDR phonon calculation database records were bulk re-stamped on
  2025-08-25T09:22:51Z; the window below covers that stamp.  The HTML listing and
  the JSON API both cap enumeration at 10,000 hits, while the collection holds
  10,034 records, so OAI keyset tokens (UUID order) are used instead.
Step 2 (api): for every candidate id, GET https://mdr.nims.go.jp/api/v1/datasets/<id>
  and keep it only if it belongs to collection d7aab932-8512-4b9a-b93d-b61f6e5e7019,
  is published / open_to_public, is CC BY 4.0, and has exactly one fileset named
  phonopy_params.yaml.xz.  The fileset id, exact size and md5 come from the API.
Selection rule (applied before step 2): keep a dataset id iff
  int(sha256(dataset_id_ascii).hexdigest(), 16) % 2 == 0.  This deterministic
  half-population subset keeps the float64 output well under the 1 GB cap (the
  full population would be ~0.9 GB); it does not look at chemistry, size or content.
Step 3 (tsv): write the sorted pin list (sorted by dataset id, independent of
  listing order).

All HTTP goes through the curl CLI (proxy-aware); Python only parses.
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import time
import hashlib
import xml.etree.ElementTree as ET

COLLECTION = "d7aab932-8512-4b9a-b93d-b61f6e5e7019"
OAI = "https://mdr.nims.go.jp/oai"
API = "https://mdr.nims.go.jp/api/v1/datasets/"
UA = "openzl-public-datasets-nims-mdr-phonondb-discover/1.0"
NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "jpcoar": "https://github.com/JPCOAR/schema/blob/master/2.0/",
}
TITLE_PREFIX = "Ab-initio phonon calculation for"
def selected(ds_id):
    return int(hashlib.sha256(ds_id.encode("ascii")).hexdigest(), 16) % 2 == 0


UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def curl(url, out, tries=6):
    for i in range(tries):
        r = subprocess.run(
            ["curl", "-sS", "-f", "-L", "--max-time", "180", "-A", UA, "-o", out, url],
            capture_output=True, text=True)
        if r.returncode == 0:
            return
        time.sleep(5 * (i + 1))
    raise RuntimeError(f"curl failed {url}: {r.stderr.strip()}")


def oai(args):
    os.makedirs(args.work, exist_ok=True)
    url = (f"{OAI}?verb=ListRecords&metadataPrefix=jpcoar_2.0"
           f"&from={args.oai_from}&until={args.oai_until}")
    out_path = os.path.join(args.work, "oai_candidates.tsv")
    seen = {}
    page = 0
    while url:
        page += 1
        fn = os.path.join(args.work, f"oai_page_{page:05d}.xml")
        if not os.path.exists(fn):
            curl(url, fn + ".part")
            os.replace(fn + ".part", fn)
            time.sleep(1.0)
        root = ET.parse(fn).getroot()
        err = root.find("oai:error", NS)
        if err is not None:
            if err.get("code") == "noRecordsMatch":
                break
            raise RuntimeError(f"OAI error {err.get('code')}: {err.text}")
        lr = root.find("oai:ListRecords", NS)
        for rec in lr.findall("oai:record", NS):
            hdr = rec.find("oai:header", NS)
            if hdr.get("status") == "deleted":
                continue
            ident = hdr.find("oai:identifier", NS).text
            ds = hdr.find("oai:datestamp", NS).text
            m = UUID_RE.search(ident)
            md = rec.find("oai:metadata", NS)
            if md is None or not m:
                continue
            titles = [t.text or "" for t in md.iter(f"{{{NS['dc']}}}title")]
            if not any(t.startswith(TITLE_PREFIX) for t in titles):
                continue
            files = [u.text for u in md.iter(f"{{{NS['jpcoar']}}}URI")
                     if u.get("label") == "phonopy_params.yaml.xz"]
            if len(files) != 1:
                continue
            title = next(t for t in titles if t.startswith(TITLE_PREFIX))
            seen[m.group(0)] = (ds, title, files[0])
        tok = lr.find("oai:resumptionToken", NS)
        url = f"{OAI}?verb=ListRecords&resumptionToken={tok.text}" if tok is not None and tok.text else None
        print(f"page={page} candidates={len(seen)}", flush=True)
    with open(out_path, "w") as f:
        for k in sorted(seen):
            ds, title, furl = seen[k]
            f.write(f"{k}\t{ds}\t{furl}\t{title}\n")
    print(f"oai done pages={page} candidates={len(seen)} -> {out_path}")


def fetch_api(work, ds_id):
    d = os.path.join(work, "api")
    fn = os.path.join(d, ds_id + ".json")
    if not os.path.exists(fn):
        curl(API + ds_id, fn + ".part")
        os.replace(fn + ".part", fn)
        time.sleep(0.2)
    return fn


def api(args):
    os.makedirs(os.path.join(args.work, "api"), exist_ok=True)
    ids = [l.split("\t")[0] for l in open(os.path.join(args.work, "oai_candidates.tsv"))]
    print(f"oai candidates={len(ids)}")
    ids = [i for i in ids if selected(i)]
    print(f"hash-selected={len(ids)}")
    done = 0
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for _ in ex.map(lambda i: fetch_api(args.work, i), ids):
            done += 1
            if done % 500 == 0:
                print(f"api {done}/{len(ids)}", flush=True)
    print(f"api done {done}")


def tsv(args):
    all_ids = [l.split("\t")[0] for l in open(os.path.join(args.work, "oai_candidates.tsv"))]
    ids = [i for i in all_ids if selected(i)]
    print(f"oai candidates={len(all_ids)} hash-selected={len(ids)}")
    rows, rejects = [], []
    for ds_id in sorted(ids):
        a = json.load(open(os.path.join(args.work, "api", ds_id + ".json")))["data"]
        at = a["attributes"]
        cols = [c["id"] for c in at.get("collections") or []]
        lic = [r.get("identifier") for r in at.get("rights") or []]
        fs = [f for f in at.get("filesets") or [] if f.get("filename") == "phonopy_params.yaml.xz"]
        title = at["titles"][0]["title"]
        why = []
        if a["id"] != ds_id:
            why.append("id")
        if COLLECTION not in cols:
            why.append("collection")
        if at.get("state") != "published" or at.get("visibility") != "open_to_public":
            why.append("state")
        if lic != ["https://creativecommons.org/licenses/by/4.0/"]:
            why.append("license")
        if len(fs) != 1:
            why.append("fileset")
        m = re.search(r"materials id (\d+)$", title)
        if not m:
            why.append("title")
        if why:
            rejects.append((ds_id, ",".join(why)))
            continue
        f = fs[0]
        rows.append((ds_id, f"mp-{m.group(1)}", f["id"], str(f["size"]), f["md5"]))
    with open(args.out, "w") as fo:
        fo.write("dataset_id\tmp_id\tfileset_id\tsize_bytes\tmd5\n")
        for r in rows:
            fo.write("\t".join(r) + "\n")
    print(f"pinned={len(rows)} bytes={sum(int(r[3]) for r in rows)} rejects={len(rejects)}")
    for r in rejects[:50]:
        print("reject", *r)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("step", choices=["oai", "api", "tsv"])
    p.add_argument("--work", required=True)
    p.add_argument("--oai-from", default="2025-08-25T00:00:00Z")
    p.add_argument("--oai-until", default="2025-08-25T23:59:59Z")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--out", default="sources.tsv")
    args = p.parse_args()
    {"oai": oai, "api": api, "tsv": tsv}[args.step](args)


if __name__ == "__main__":
    sys.exit(main())
