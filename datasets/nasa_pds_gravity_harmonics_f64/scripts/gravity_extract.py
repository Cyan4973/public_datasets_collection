#!/usr/bin/env python3
# Local decoder for the accepted NASA GRAIL gravity-harmonics recipe.
from __future__ import annotations
import argparse, gzip, io, json, math, re, shutil, statistics, struct, zipfile
from pathlib import Path

ID="nasa_pds_gravity_harmonics_f64"; C_ID="gravity_cosine_cnm_f64"; S_ID="gravity_sine_snm_f64"

def text_payload(path: Path) -> tuple[str,str]:
    raw=path.read_bytes()
    if raw[:2]==b'\x1f\x8b': return gzip.decompress(raw).decode('ascii',errors='strict'),path.name+'::gzip'
    if raw[:4]==b'PK\x03\x04':
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names=[n for n in z.namelist() if not n.endswith('/') and any(x in n.lower() for x in ['.gfc','.sha','.tab','.txt'])]
            if not names: raise ValueError('ZIP has no gravity coefficient text member')
            ranked=sorted(names,key=lambda n:(0 if 'grgm1200' in n.lower() else 1,len(n)))
            return z.read(ranked[0]).decode('ascii',errors='strict'),path.name+'::'+ranked[0]
    return raw.decode('ascii',errors='strict'),path.name

def integer(token: str):
    return int(token) if re.fullmatch(r'[+-]?\d+',token) else None

def parse(path: Path) -> dict:
    text,member=text_payload(path); rows=[]; seen=set(); recognized={'gfc','gfct','grcoef','recoef','grvcoef','coef','coefficient'}
    for number,line in enumerate(text.splitlines(),1):
        stripped=line.strip()
        if not stripped or stripped.startswith(('#','%',';','/*')): continue
        tokens=[t for t in re.split(r'[\s,]+',stripped) if t]
        start=1 if tokens and tokens[0].lower() in recognized else 0
        if len(tokens)<start+4: continue
        n=integer(tokens[start]); m=integer(tokens[start+1])
        if n is None or m is None: continue
        if n<0 or m<0 or m>n or n>10000: continue
        try: c=float(tokens[start+2].replace('D','E').replace('d','e')); s=float(tokens[start+3].replace('D','E').replace('d','e'))
        except ValueError as e: raise ValueError(f'malformed coefficient at line {number}') from e
        if not math.isfinite(c) or not math.isfinite(s): raise ValueError(f'non-finite coefficient at line {number}')
        if (n,m) in seen: raise ValueError(f'duplicate degree/order {(n,m)}')
        seen.add((n,m)); rows.append((n,m,c,s))
    if len(rows)<10000: raise ValueError(f'only {len(rows)} coefficient rows; need at least 10000')
    max_degree=max(r[0] for r in rows)
    if max_degree<100: raise ValueError(f'maximum degree {max_degree} is below 100')
    c=[r[2] for r in rows]; s=[r[3] for r in rows]
    if min(c)==max(c) or min(s)==max(s): raise ValueError('constant coefficient field')
    return {'member':member,'rows':rows,'c':c,'s':s,'row_count':len(rows),'max_degree':max_degree}

def write(path: Path, vals: list[float]):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('wb') as h:
        for i in range(0,len(vals),65536):
            x=vals[i:i+65536]; h.write(struct.pack('<'+'d'*len(x),*x))

def rows_for(model, samples: Path, data: Path):
    out=[]
    for sid,name in [(C_ID,'cnm.bin'),(S_ID,'snm.bin')]:
        p=samples/sid/name; n=model['row_count']
        out.append({'dataset_id':ID,'series_id':sid,'sample_path':p.resolve().relative_to(data.resolve()).as_posix(),'numeric_kind':'float','bit_width':64,'endianness':'little','element_size_bytes':8,'sample_size_bytes':n*8,'value_count':n})
    return out

def inspect(args):
    m=parse(Path(args.input)); print(f"validated member={m['member']} rows={m['row_count']} max_degree={m['max_degree']}")

def extract(args):
    m=parse(Path(args.input)); samples,data=Path(args.samples_root),Path(args.data_root)
    if samples.exists(): shutil.rmtree(samples)
    write(samples/C_ID/'cnm.bin',m['c']); write(samples/S_ID/'snm.bin',m['s'])
    rows=rows_for(m,samples,data); index=Path(args.index); index.parent.mkdir(parents=True,exist_ok=True); index.write_text(''.join(json.dumps(r,sort_keys=True)+'\n' for r in rows))
    stats=Path(args.stats); stats.parent.mkdir(parents=True,exist_ok=True); stats.write_text(json.dumps({'dataset_id':ID,'source_member':m['member'],'coefficient_rows':m['row_count'],'maximum_degree':m['max_degree'],'primary_values':m['row_count']*2,'primary_bytes':m['row_count']*16},indent=2,sort_keys=True)+'\n')
    print(f"built samples=2 values={m['row_count']*2} bytes={m['row_count']*16} max_degree={m['max_degree']}")

def verify(args):
    m=parse(Path(args.input)); samples,data=Path(args.samples_root),Path(args.data_root); expected=rows_for(m,samples,data)
    actual=[json.loads(x) for x in Path(args.index).read_text().splitlines() if x.strip()]
    if actual!=expected: raise ValueError('index differs from source decode')
    for sid,name,vals in [(C_ID,'cnm.bin',m['c']),(S_ID,'snm.bin',m['s'])]:
        raw=(samples/sid/name).read_bytes(); got=[x[0] for x in struct.iter_unpack('<d',raw)]
        if got!=vals: raise ValueError(f'{sid} differs from source decode')
    stats=json.loads(Path(args.stats).read_text())
    if stats['coefficient_rows']!=m['row_count'] or stats['maximum_degree']!=m['max_degree']: raise ValueError('stats mismatch')
    if statistics.median(r['value_count'] for r in actual)<1000 or sum(r['sample_size_bytes'] for r in actual)>1_000_000_000: raise ValueError('acceptance bounds failed')
    print(f"verified samples=2 values={m['row_count']*2} bytes={m['row_count']*16}")

def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='cmd',required=True)
    q=sub.add_parser('inspect'); q.add_argument('--input',required=True); q.set_defaults(func=inspect)
    for name,func in [('extract',extract),('verify',verify)]:
        q=sub.add_parser(name)
        for a in ['input','data-root','samples-root','index','stats']: q.add_argument('--'+a,required=True)
        q.set_defaults(func=func)
    a=p.parse_args()
    try: a.func(a)
    except (OSError,ValueError,EOFError,zipfile.BadZipFile) as e: p.error(str(e))
    return 0
if __name__=='__main__': raise SystemExit(main())
