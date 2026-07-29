#!/usr/bin/env python3
# Local decoder for the accepted NOAA CORS RINEX recipe.
from __future__ import annotations

import argparse, gzip, json, math, re, shutil, statistics, struct
from pathlib import Path

DATASET_ID="noaa_cors_rinex_observations_f64"
SERIES={"C":"gnss_pseudorange_m_f64","P":"gnss_pseudorange_m_f64","L":"gnss_carrier_phase_cycles_f64","D":"gnss_doppler_hz_f64","S":"gnss_signal_strength_dbhz_f64"}

def parse_float(text: str, context: str) -> float:
    try: value=float(text.replace('D','E'))
    except ValueError as e: raise ValueError(f"bad observation {text!r} at {context}") from e
    if not math.isfinite(value): raise ValueError(f"non-finite observation at {context}")
    return value

def read_header(lines: list[str], path: Path) -> tuple[int,list[str]]:
    if not lines or 'RINEX VERSION / TYPE' not in lines[0] or len(lines[0]) < 21 or lines[0][20].upper()!='O':
        raise ValueError(f"not a RINEX observation file: {path}")
    try: version=float(lines[0][:9])
    except ValueError as e: raise ValueError(f"invalid RINEX version in {path}") from e
    if version >= 3: raise ValueError(f"RINEX {version} is unsupported; expected RINEX 2")
    codes=[]; expected=None
    for i,line in enumerate(lines):
        label=line[60:80].strip() if len(line)>=60 else ''
        if label=='# / TYPES OF OBSERV':
            if expected is None: expected=int(line[:6])
            codes.extend(line[6:60].split())
        if label=='END OF HEADER':
            if expected is None or len(codes)<expected: raise ValueError(f"missing observation types in {path}")
            return i+1,codes[:expected]
    raise ValueError(f"missing END OF HEADER in {path}")

def parse_file(path: Path) -> dict:
    with gzip.open(path,'rt',encoding='ascii',errors='strict',newline='') as h:
        lines=[line.rstrip('\r\n') for line in h]
    pos,codes=read_header(lines,path); values={code:[] for code in codes if code and code[0] in SERIES}
    epochs=0; satellites=0
    while pos < len(lines):
        line=lines[pos]; pos+=1
        if not line.strip(): continue
        if len(line)<32: raise ValueError(f"short epoch line {path}:{pos}")
        try: flag=int(line[28:29]); count=int(line[29:32])
        except ValueError as e: raise ValueError(f"bad epoch header {path}:{pos}") from e
        if flag in (2,3,4,5):
            pos += count
            continue
        if flag not in (0,1,6):
            raise ValueError(f"unsupported epoch flag {flag} at {path}:{pos}")
        sat_text=line[32:68]
        while len(sat_text)//3 < count:
            if pos>=len(lines): raise ValueError(f"truncated satellite list in {path}")
            sat_text += lines[pos][32:68]; pos+=1
        obs_lines=(len(codes)+4)//5
        if flag==6:
            pos += count*obs_lines
            if pos>len(lines): raise ValueError(f"truncated cycle-slip records in {path}")
            continue
        for sat_index in range(count):
            fields=''
            for _ in range(obs_lines):
                if pos>=len(lines): raise ValueError(f"truncated observations in {path}")
                fields += lines[pos].ljust(80); pos+=1
            for idx,code in enumerate(codes):
                if code not in values: continue
                field=fields[idx*16:(idx+1)*16][:14]
                if field.strip(): values[code].append(parse_float(field,f"{path.name}:epoch{epochs}:sat{sat_index}:{code}"))
        epochs+=1; satellites+=count
    return {"path":path,"codes":codes,"values":values,"epochs":epochs,"satellite_records":satellites}

def scan(downloads: Path) -> tuple[list[dict],list[dict]]:
    paths=sorted(downloads.glob('*o.gz'))+sorted(downloads.glob('*O.gz'))
    paths=list(dict.fromkeys(paths))
    if not paths: raise ValueError(f"no RINEX observation gzip files in {downloads}")
    kept=[]; skipped=[]
    for path in paths:
        parsed=parse_file(path)
        stem=re.sub(r'[^A-Za-z0-9]+','_',path.name).strip('_').lower()
        for code,vals in parsed['values'].items():
            item={"source":path.name,"code":code,"series_id":SERIES[code[0]],"values":vals,"epochs":parsed['epochs'],"satellite_records":parsed['satellite_records'],"sample_name":f"{stem}_{code.lower()}.bin"}
            if len(vals)<1000: skipped.append({k:v for k,v in item.items() if k!='values'}|{"value_count":len(vals),"reason":"natural_sample_below_1000_values"})
            elif min(vals)==max(vals): raise ValueError(f"constant retained sample {path.name} {code}")
            else: kept.append(item)
    if not kept: raise ValueError("no station-day/code samples meet the natural-sample floor")
    return kept,skipped

def write_values(path: Path, values: list[float]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('wb') as h:
        for offset in range(0,len(values),65536):
            chunk=values[offset:offset+65536]; h.write(struct.pack('<'+'d'*len(chunk),*chunk))

def expected(downloads: Path, samples_root: Path, data_root: Path) -> tuple[list[dict],list[dict]]:
    kept,skipped=scan(downloads); rows=[]
    for item in kept:
        path=samples_root/item['series_id']/item['sample_name']
        rows.append({"dataset_id":DATASET_ID,"series_id":item['series_id'],"sample_path":path.resolve().relative_to(data_root.resolve()).as_posix(),"numeric_kind":"float","bit_width":64,"endianness":"little","element_size_bytes":8,"sample_size_bytes":len(item['values'])*8,"value_count":len(item['values']),"source_file":item['source'],"source_field":item['code']})
    return rows,skipped

def enforce(rows: list[dict]) -> None:
    counts=[r['value_count'] for r in rows]; total=sum(counts); size=sum(r['sample_size_bytes'] for r in rows)
    if total<10000 and size<102400: raise ValueError("aggregate floor not met")
    if statistics.median(counts)<1000: raise ValueError("median sample floor not met")
    if size>1_000_000_000: raise ValueError("primary output exceeds 1 GB")

def extract(args) -> None:
    downloads,samples,data=Path(args.downloads),Path(args.samples_root),Path(args.data_root)
    kept,skipped=scan(downloads)
    if samples.exists(): shutil.rmtree(samples)
    rows=[]
    for item in kept:
        path=samples/item['series_id']/item['sample_name']; write_values(path,item['values'])
        rows.append({"dataset_id":DATASET_ID,"series_id":item['series_id'],"sample_path":path.resolve().relative_to(data.resolve()).as_posix(),"numeric_kind":"float","bit_width":64,"endianness":"little","element_size_bytes":8,"sample_size_bytes":path.stat().st_size,"value_count":len(item['values']),"source_file":item['source'],"source_field":item['code']})
    enforce(rows); index=Path(args.index); index.parent.mkdir(parents=True,exist_ok=True); index.write_text(''.join(json.dumps(r,sort_keys=True)+'\n' for r in rows))
    stats=Path(args.stats); stats.parent.mkdir(parents=True,exist_ok=True); stats.write_text(json.dumps({"dataset_id":DATASET_ID,"primary_sample_count":len(rows),"primary_value_count":sum(r['value_count'] for r in rows),"primary_sample_bytes":sum(r['sample_size_bytes'] for r in rows),"median_primary_sample_value_count":statistics.median(r['value_count'] for r in rows),"skipped_samples":skipped},indent=2,sort_keys=True)+'\n')
    print(f"built samples={len(rows)} values={sum(r['value_count'] for r in rows)} bytes={sum(r['sample_size_bytes'] for r in rows)}")

def verify(args) -> None:
    downloads,samples,data=Path(args.downloads),Path(args.samples_root),Path(args.data_root)
    kept,skipped=scan(downloads); expected_rows,_=expected(downloads,samples,data); enforce(expected_rows)
    actual=[json.loads(x) for x in Path(args.index).read_text().splitlines() if x.strip()]
    if actual!=expected_rows: raise ValueError("sample index differs from independent source decode")
    by_name={(i['series_id'],i['sample_name']):i for i in kept}
    for row in actual:
        path=data/row['sample_path']; raw=path.read_bytes(); item=by_name[(row['series_id'],path.name)]
        vals=[x[0] for x in struct.iter_unpack('<d',raw)]
        if vals!=item['values']: raise ValueError(f"sample differs from source decode: {path}")
    stats=json.loads(Path(args.stats).read_text())
    if stats['primary_value_count']!=sum(r['value_count'] for r in actual) or len(stats['skipped_samples'])!=len(skipped): raise ValueError("stats mismatch")
    print(f"verified samples={len(actual)} values={sum(r['value_count'] for r in actual)} bytes={sum(r['sample_size_bytes'] for r in actual)}")

def main() -> int:
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='cmd',required=True)
    for name,func in [('extract',extract),('verify',verify)]:
        q=sub.add_parser(name)
        for arg in ['downloads','data-root','samples-root','index','stats']: q.add_argument('--'+arg,required=True)
        q.set_defaults(func=func)
    a=p.parse_args()
    try: a.func(a)
    except (OSError,ValueError,EOFError) as e: p.error(str(e))
    return 0
if __name__=='__main__': raise SystemExit(main())
