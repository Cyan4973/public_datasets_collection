#!/usr/bin/env python3
"""Resolve the pinned file inventory from PDS4 labels (used by discover.sh).

  select_files.py labels <scratch>          -> <scratch>/labels.tsv
  select_files.py select <scratch> <N> <out_files.tsv>

Selection rule (fixed before looking at pressure values): among full-sol
ps_calib products whose label reports a table of 887,000..888,500 records
spanning 88,700..88,800 s (one Mars sol at 10 samples/s), choose N products
evenly spaced over the ordered candidate list (index round(i*(M-1)/(N-1))).
"""
import datetime as dt
import os
import re
import sys
import xml.etree.ElementTree as ET

NS = {"p": "http://pds.nasa.gov/pds4/pds/v1",
      "i": "http://pds.nasa.gov/pds4/mission/insight/v1"}


def ts(s):
    return dt.datetime.strptime(s.rstrip("Z"), "%Y-%m-%dT%H:%M:%S.%f")


def labels(scratch):
    rows = []
    with open(os.path.join(scratch, "candidates.txt")) as fh:
        cands = [ln.split() for ln in fh if ln.strip()]
    for d, f in cands:
        root = ET.parse(os.path.join(scratch, "labels", f[:-4] + ".xml")).getroot()
        fe = root.find(".//p:File_Area_Observational/p:File", NS)
        assert fe.findtext("p:file_name", namespaces=NS) == f, f
        size = int(fe.findtext("p:file_size", namespaces=NS))
        md5 = fe.findtext("p:md5_checksum", namespaces=NS).strip().lower()
        tab = root.find(".//p:Table_Delimited", NS)
        recs = int(tab.findtext("p:records", namespaces=NS))
        off = int(tab.findtext("p:offset", namespaces=NS))
        start = root.findtext(".//p:Time_Coordinates/p:start_date_time", namespaces=NS)
        stop = root.findtext(".//p:Time_Coordinates/p:stop_date_time", namespaces=NS)
        sol = int(root.findtext(".//i:sol_number", namespaces=NS))
        lid = root.findtext(".//p:logical_identifier", namespaces=NS)
        vid = root.findtext("p:Identification_Area/p:version_id", namespaces=NS)
        names = [e.findtext("p:name", namespaces=NS) for e in tab.findall(".//p:Field_Delimited", NS)]
        dur = (ts(stop) - ts(start)).total_seconds()
        rows.append((d, f, sol, size, md5, recs, off, start, stop, f"{dur:.3f}", lid, vid, "|".join(names)))
    rows.sort(key=lambda r: (r[2], r[1]))
    with open(os.path.join(scratch, "labels.tsv"), "w") as out:
        out.write("dir\tfile\tsol\tsize\tmd5\trecords\theader_bytes\tstart\tstop\tduration_s\tlid\tversion_id\tfields\n")
        for r in rows:
            out.write("\t".join(map(str, r)) + "\n")
    print(f"labels.tsv rows={len(rows)}")


def select(scratch, n, out_path):
    with open(os.path.join(scratch, "labels.tsv")) as fh:
        hdr = fh.readline().rstrip("\n").split("\t")
        rows = [dict(zip(hdr, ln.rstrip("\n").split("\t"))) for ln in fh]
    ok = [r for r in rows
          if 887000 <= int(r["records"]) <= 888500
          and 88700.0 <= float(r["duration_s"]) <= 88800.0
          and r["fields"] == "AOBT|SCLK|LMST|LTST|UTC|PRESSURE|PRESSURE_FREQUENCY|PRESSURE_TEMP|PRESSURE_TEMP_FREQUENCY"]
    m = len(ok)
    pick = sorted({round(i * (m - 1) / (n - 1)) for i in range(n)})
    assert len(pick) == n
    with open(out_path, "w") as out:
        out.write("dir\tfile\tsol\tsize_bytes\tmd5\trecords\theader_bytes\tstart\tstop\n")
        for i in pick:
            r = ok[i]
            out.write("\t".join([r["dir"], r["file"], r["sol"], r["size"], r["md5"], r["records"],
                                 r["header_bytes"], r["start"], r["stop"]]) + "\n")
    print(f"eligible={m} of {len(rows)} selected={n} bytes={sum(int(ok[i]['size']) for i in pick)}")


if __name__ == "__main__":
    if sys.argv[1] == "labels":
        labels(sys.argv[2])
    else:
        select(sys.argv[2], int(sys.argv[3]), sys.argv[4])
