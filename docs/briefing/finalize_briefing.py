"""Publish briefing artifacts and validate PPTX text/notes against authored SVGs."""
import argparse
import base64
import hashlib
import html
import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('project',type=Path)
p.add_argument('--pptx',type=Path,required=True)
p.add_argument('--render',action='store_true')
a=p.parse_args()
here=Path(__file__).resolve().parent
project=a.project.resolve()
slides=json.loads((here/'slides.json').read_text(encoding='utf-8'))
svg_files=sorted((project/'svg_output').glob('*.svg'))
assert len(svg_files)==len(slides)==24
ns={'s':'http://www.w3.org/2000/svg','a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
checks=[]
with zipfile.ZipFile(a.pptx) as z:
    assert z.testzip() is None
    snames=[n for n in z.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml',n)]
    nnames=[n for n in z.namelist() if re.fullmatch(r'ppt/notesSlides/notesSlide\d+\.xml',n)]
    assert len(snames)==len(nnames)==24
    for i,(source,slide) in enumerate(zip(svg_files,slides),1):
        src=ET.parse(source).getroot()
        expected=[''.join(t.itertext()) for t in src.findall('.//s:text',ns)]
        root=ET.fromstring(z.read(f'ppt/slides/slide{i}.xml'))
        actual=[''.join(t.itertext()) for t in root.findall('.//a:t',ns)]
        joined=''.join(actual)
        missing=[x for x in expected if x not in joined]
        assert not missing,(i,missing)
        notes=''.join(ET.fromstring(z.read(f'ppt/notesSlides/notesSlide{i}.xml')).itertext())
        assert slide['notes'] in notes, f'notes mismatch {i}'
        checks.append(dict(slide=i,text_frames=len(expected),notes_verified=True))

target=here/'StreamVLM管线设计汇报.pptx'
shutil.copy2(a.pptx,target)
out_svg=here/'slide-source';out_svg.mkdir(exist_ok=True)
for source in svg_files:shutil.copy2(source,out_svg/source.name)
for name in ['design_spec.md','spec_lock.md']:
    shutil.copy2(project/name,out_svg/name)
for name in ['管线设计报告.md','slides.json']:
    shutil.copy2(here/name,project/'sources'/name)

import markdown
css='''body{font-family:"Microsoft YaHei",Arial,sans-serif;color:#203448;line-height:1.85;margin:40px auto;max-width:1120px;padding:0 32px;background:#fff}h1{font-size:32px;line-height:1.5;color:#16324f}h2{font-size:25px;color:#16324f;margin-top:48px;border-bottom:1px solid #cbd5df;padding-bottom:8px}h3{font-size:20px;color:#087f8c;margin-top:30px}p,li{font-size:16px}table{border-collapse:collapse;font-size:14px;width:100%;margin:24px 0}td,th{border:1px solid #cbd5df;padding:10px 12px;text-align:left;vertical-align:top}th{background:#e8f1f5}pre{background:#f1f5f9;padding:18px;white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px}code{font-family:Consolas,monospace}a{color:#087f8c;overflow-wrap:anywhere}hr{border:0;border-top:1px solid #cbd5df;margin:42px 0}@media print{body{max-width:none;margin:0;padding:0}h2{break-after:avoid}pre,table,tr{break-inside:avoid}a{color:inherit}}'''
for stem in ['管线设计报告','逐页讲稿']:
    body=markdown.markdown((here/(stem+'.md')).read_text(encoding='utf-8'),extensions=['tables','fenced_code','toc'])
    content=f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{stem}</title><style>{css}</style><body>{body}</body></html>'
    (here/(stem+'.html')).write_text(content,encoding='utf-8')

preview='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>StreamVLM 汇报预览</title><style>body{margin:0;background:#e5eaf0;font-family:Arial,"Microsoft YaHei",sans-serif}.slides{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;padding:20px}.slide{margin:0}img{width:100%;display:block}figcaption{height:28px;font-size:14px;padding:4px 0;color:#16324f}</style><div class="slides">'''
for i,f in enumerate(svg_files,1):
    encoded=base64.b64encode(f.read_bytes()).decode()
    preview+=f'<figure class="slide"><img src="data:image/svg+xml;base64,{encoded}"><figcaption>{i:02d}　{html.escape(slides[i-1]["title"])}</figcaption></figure>'
preview+='</div></html>'
(here/'PPT预览.html').write_text(preview,encoding='utf-8')

if a.render:
    edge=Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
    render=project/'validation/rendered';render.mkdir(exist_ok=True)
    jobs=[(here/'PPT预览.html',render/'contact.png','1560,2790')]
    for i in [4,5,8,11,15,19,22]:
        f=svg_files[i-1]
        page=render/f'{i:02d}.html'
        encoded=base64.b64encode(f.read_bytes()).decode()
        page.write_text(f'<!doctype html><meta charset="utf-8"><style>html,body{{margin:0;width:1280px;height:720px;overflow:hidden}}img{{display:block;width:1280px;height:720px}}</style><img src="data:image/svg+xml;base64,{encoded}">',encoding='utf-8')
        jobs.append((page,render/f'{i:02d}.png','1280,720'))
    for n,(page,png,size) in enumerate(jobs):
        command=[str(edge),'--headless','--disable-gpu','--no-first-run','--hide-scrollbars','--force-device-scale-factor=1',f'--user-data-dir={render/"edge-profile"}',f'--window-size={size}',f'--screenshot={png}',page.as_uri()]
        result=subprocess.run(command,capture_output=True,timeout=40,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if not png.is_file():raise RuntimeError(f'render failed {n}: {result.stderr[-400:]!r}')
        print('rendered',png.name,flush=True)

artifacts=['StreamVLM管线设计汇报.pptx','管线设计报告.md','管线设计报告.html','逐页讲稿.md','逐页讲稿.html','PPT预览.html']
manifest=dict(slides=24,notes=24,validation='PPTX ZIP integrity, per-slide SVG text coverage, exact narration inclusion',checks=checks,files={name:dict(bytes=(here/name).stat().st_size,sha256=hashlib.sha256((here/name).read_bytes()).hexdigest()) for name in artifacts})
(here/'delivery-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(slides=24,notes=24,files=artifacts),ensure_ascii=False))
