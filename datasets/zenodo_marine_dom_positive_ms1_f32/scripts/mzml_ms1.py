#!/usr/bin/env python3
# Local decoder for the accepted marine-DOM positive MS1 recipe.
from __future__ import annotations
import argparse,base64,json,math,re,shutil,statistics,struct,xml.etree.ElementTree as ET,zlib
from pathlib import Path
ID='zenodo_marine_dom_positive_ms1_f32'; MZ_ID='positive_ms1_mz_f32'; IN_ID='positive_ms1_intensity_f32'
def loc(t): return t.rsplit('}',1)[-1]
def acc(e): return {x.attrib.get('accession','') for x in e.iter() if loc(x.tag)=='cvParam'}
def decode(bda,n,ctx):
 a=acc(bda); kind=MZ_ID if 'MS:1000514' in a else IN_ID if 'MS:1000515' in a else None
 if not kind or 'MS:1000521' not in a or 'MS:1000523' in a: return None
 b=next((x for x in bda if loc(x.tag)=='binary'),None)
 if b is None: raise ValueError(f'missing binary {ctx}')
 raw=base64.b64decode(''.join((b.text or '').split()),validate=True); raw=zlib.decompress(raw) if 'MS:1000574' in a else raw
 if len(raw)!=n*4: raise ValueError(f'length mismatch {ctx}')
 vals=[x[0] for x in struct.iter_unpack('<f',raw)]
 if not all(math.isfinite(x) for x in vals): raise ValueError(f'nonfinite {ctx}')
 return kind,vals
def scan(root):
 items=[]; fs={}
 for p in sorted(root.glob('*.mzML')):
  count=ms1=0; stem=re.sub(r'\W+','_',p.stem).lower()
  for _,e in ET.iterparse(p,events=('end',)):
   if loc(e.tag)!='spectrum': continue
   count+=1; a=acc(e); level=next((x.attrib.get('value') for x in e.iter() if loc(x.tag)=='cvParam' and x.attrib.get('accession')=='MS:1000511'),None)
   if level!='1' or 'MS:1000130' not in a or 'MS:1000127' not in a: e.clear(); continue
   ms1+=1; n=int(e.attrib.get('defaultArrayLength','0')); found={}
   for bda in (x for x in e.iter() if loc(x.tag)=='binaryDataArray'):
    d=decode(bda,n,f'{p.name}:{count}')
    if d: found[d[0]]=d[1]
   if set(found)!={MZ_ID,IN_ID}: raise ValueError(f'missing native f32 arrays {p.name}:{count}')
   for sid,vals in found.items():
    if min(vals)==max(vals): raise ValueError(f'constant array {p.name}:{count}:{sid}')
    items.append({'series_id':sid,'values':vals,'file':p.name,'record':e.attrib.get('id',str(count)),'name':f'{stem}_spectrum_{count:06d}_{"mz" if sid==MZ_ID else "intensity"}.bin'})
   e.clear()
  fs[p.name]={'spectra':count,'positive_ms1':ms1}
 if not items: raise ValueError('no positive MS1 float32 arrays')
 return items,fs
def write(p,v): p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(struct.pack('<'+'f'*len(v),*v))
def rows(items,samples,data): return [{'dataset_id':ID,'series_id':x['series_id'],'sample_path':(samples/x['series_id']/x['name']).resolve().relative_to(data.resolve()).as_posix(),'numeric_kind':'float','bit_width':32,'endianness':'little','element_size_bytes':4,'sample_size_bytes':len(x['values'])*4,'value_count':len(x['values']),'source_file':x['file'],'source_record':x['record']} for x in items]
def enforce(rs):
 c=[r['value_count'] for r in rs]
 if sum(c)<10000 or statistics.median(c)<1000 or sum(r['sample_size_bytes'] for r in rs)>1_000_000_000: raise ValueError('acceptance floors failed')
def extract(a):
 d,s,r=Path(a.downloads),Path(a.samples_root),Path(a.data_root); items,fs=scan(d)
 if s.exists(): shutil.rmtree(s)
 for x in items: write(s/x['series_id']/x['name'],x['values'])
 rs=rows(items,s,r); enforce(rs); p=Path(a.index); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in rs)); q=Path(a.stats); q.parent.mkdir(parents=True,exist_ok=True); q.write_text(json.dumps({'files':fs,'samples':len(rs),'values':sum(x['value_count'] for x in rs),'bytes':sum(x['sample_size_bytes'] for x in rs),'median':statistics.median(x['value_count'] for x in rs)},indent=2,sort_keys=True)+'\n'); print(f"built samples={len(rs)} values={sum(x['value_count'] for x in rs)} bytes={sum(x['sample_size_bytes'] for x in rs)} median={statistics.median(x['value_count'] for x in rs)}")
def verify(a):
 d,s,r=Path(a.downloads),Path(a.samples_root),Path(a.data_root); items,fs=scan(d); exp=rows(items,s,r); enforce(exp); got=[json.loads(x) for x in Path(a.index).read_text().splitlines() if x.strip()]
 if got!=exp: raise ValueError('index mismatch')
 look={(x['series_id'],x['name']):x['values'] for x in items}
 for x in got:
  p=r/x['sample_path']; vals=[z[0] for z in struct.iter_unpack('<f',p.read_bytes())]
  if vals!=look[(x['series_id'],p.name)]: raise ValueError(f'sample mismatch {p}')
 print(f"verified samples={len(got)} values={sum(x['value_count'] for x in got)} bytes={sum(x['sample_size_bytes'] for x in got)}")
def main():
 p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='cmd',required=True)
 for n,f in [('extract',extract),('verify',verify)]:
  q=sub.add_parser(n)
  for x in ['downloads','data-root','samples-root','index','stats']: q.add_argument('--'+x,required=True)
  q.set_defaults(func=f)
 a=p.parse_args()
 try:a.func(a)
 except Exception as e:p.error(str(e))
if __name__=='__main__': main()
