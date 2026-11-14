"""Prepare the diagram-led design brief and validate/publish its authored slides."""
import argparse,base64,hashlib,html,json,re,shutil,zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('mode',choices=['plan','notes','publish'])
p.add_argument('--project',type=Path,required=True)
p.add_argument('--base-project',type=Path)
p.add_argument('--pptx',type=Path)
a=p.parse_args();here=Path(__file__).resolve().parent;proj=a.project.resolve()
items=json.loads((here/'content.json').read_text(encoding='utf-8'))
if a.mode=='plan':
    base=a.base_project
    text=(base/'design_spec.md').read_text(encoding='utf-8').split('## IX. Content Outline')[0]
    text=text.replace('streamvlm_briefing','streamvlm_talk').replace('streamvlm_design','streamvlm_talk')
    text=re.sub(r'\| Page Count \| \d+ \|',f'| Page Count | {len(items)} |',text)
    text=text.replace('解释 Qwen3-VL 计算路径、管线设计与 GPU 研究接入方式','说明最终管线的模块、数据流、时序和接口')
    text=text.replace('能指出输入约束、被测实现、指标口径及当前验收边界','能够沿一条查询路径解释各模块的职责与输入输出')
    text=text.replace('当前交付是可执行实验底座，供后续 GPU 实现比较使用','管线把定时输入组织成可配置、可测量的 GPU 推理实验')
    text=text.replace('组内现场技术汇报，主讲 22 页，附录 2 页','面向师兄的管线设计汇报，共 10 页')
    text=text.replace('依任务、基座、输入、执行、测量、证据逐步解释，具体双会话例子衔接抽象协议。','总图定位模块，逐页展开输入、状态、执行、实验组织，最后以同一查询贯穿。')
    text=text.replace('面向师兄的管线设计汇报，共 10 页','面向师兄的管线设计汇报，共 8 页')
    text=text.replace('总图定位模块，逐页展开输入、状态、执行、实验组织，最后以同一查询贯穿。','系统总图、配置组的双泳道时序、运行阶段展开、多组组织、完整例子。')
    text+='## IX. Content Outline\n\n### Part 1: 管线设计\n'
    for i,s in enumerate(items,1):
        text+=f"\n#### Slide {i:02d} - {s['title']}\n\n- **Audience move**: 理解本模块在总图中的作用及输入输出\n- **Relationships**: {s['relation']}\n- **Title**: {s['title']}\n- **Core message**: {s['subtitle']}\n- **Content**: {s['explanation']}\n- **Composition**: 单张清晰的原生技术图；模块、接口、连线和时序准确，图占页面主体\n"
    text+='\n## X. Speaker Notes Requirements\n\n- **Generation**: enabled\n- **Filename**: match each SVG filename under notes/\n- **Content**: 先连接上一页，再沿图讲谁做什么、交给谁，解释术语后再给名称。\n- **Total duration**: 约 10–12 分钟\n- **Notes style**: 自然口语，面向师兄讲述最终设计\n- **Presentation purpose**: 说明管线如何设计与运行\n'
    (proj/'design_spec.md').write_text(text,encoding='utf-8')
    lock=(base/'spec_lock.md').read_text(encoding='utf-8')
    lock=lock.replace('解释管线设计、真实能力与 GPU 改进接入方式，使师兄能审核边界。','说明最终管线的数据流、控制流和接口，使师兄能够理解设计。')
    lock=lock.replace('逐步解释任务、模型、输入、执行、测量与验收，具体例子贯穿。','总图、模块展开、完整查询路径；每页一张主图。')
    lock=lock.split('## page_rhythm')[0]+'## page_rhythm\n'+''.join(f'- P{i:02d}: anchor\n' for i in range(1,len(items)+1))+'## pptx_structure\n- mode: flat\n## forbidden\n- `mask`, `<style>`, `class`, external CSS, `<foreignObject>`, `textPath`, `@font-face`, `<animate*>`, `<set>`, `<script>` / event attributes, `<iframe>`\n- HTML named entities in text; write typography as raw Unicode and escape XML reserved characters\n'
    (proj/'spec_lock.md').write_text(lock,encoding='utf-8')
    (proj/'sources/content.json').write_bytes((here/'content.json').read_bytes())
    print('design plan ready:',len(items),'slides');raise SystemExit()

if a.mode=='notes':
    source='来源：本项目 events.py、runner.py、backends.py、deployment.py、suite.py、identity.py、report.py。\nhttps://github.com/sxq999/stream-VLM/tree/34b4218/src/stream_pipeline'
    notes='\n\n---\n\n'.join(f"# {i:02d}_{s['title']}\n\n{s['notes']}\n\n{source}" for i,s in enumerate(items,1))
    (proj/'notes/total.md').write_text(notes,encoding='utf-8')
    (here/'逐页讲稿.md').write_text('# StreamVLM 管线设计汇报讲稿\n\n对应八页汇报。主讲约十至十二分钟，可按讨论需要展开。每页均以连接上一页的口语开场，随后沿图说明动作和接口。\n\n'+notes,encoding='utf-8')
    raise SystemExit()

files=sorted((proj/'svg_output').glob('*.svg'));assert len(files)==len(items)
shutil.copy2(here/'content.json',proj/'sources/content.json')
ns={'s':'http://www.w3.org/2000/svg','a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
checks=[]
with zipfile.ZipFile(a.pptx) as z:
    assert z.testzip() is None
    assert len([n for n in z.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml',n)])==len(items)
    assert len([n for n in z.namelist() if re.fullmatch(r'ppt/notesSlides/notesSlide\d+\.xml',n)])==len(items)
    for i,(f,s) in enumerate(zip(files,items),1):
        expected=[''.join(t.itertext()) for t in ET.parse(f).getroot().findall('.//s:text',ns)]
        actual=''.join(ET.fromstring(z.read(f'ppt/slides/slide{i}.xml')).itertext())
        assert all(t in actual for t in expected),i
        note=''.join(ET.fromstring(z.read(f'ppt/notesSlides/notesSlide{i}.xml')).itertext())
        assert s['notes'] in note,i
        checks.append({'slide':i,'text_and_notes':'pass'})
shutil.copy2(a.pptx,here/'StreamVLM管线设计_汇报版.pptx')
src=here/'图源';src.mkdir(exist_ok=True)
for f in files:shutil.copy2(f,src/f.name)
for f in ['design_spec.md','spec_lock.md']:shutil.copy2(proj/f,src/f)
report='# StreamVLM 实验管线设计\n\n本管线在 CPU 上控制输入、维护视频历史、提交请求并记录结果；独立运行的 vLLM 调用 GPU 执行模型。本文先说明整体层次，再展开运行阶段。\n\n**层次约定：**实验套件包含多个配置组；每个托管配置组启动一次引擎服务，运行阶段可回放多轮；每轮回放产生多个查询请求。图中的时间、两帧窗口和重复次数均为设计说明示例，不是性能测量。\n\n'
for i,(f,s) in enumerate(zip(files,items),1):
    report+=f"## {i}. {s['title']}\n\n![{s['title']}](图源/{f.name})\n\n{s['explanation']}\n\n**设计规则：**{s['rule']}。\n\n"
report+='## 实现对应\n\n| 设计职责 | 实现入口 |\n|---|---|\n| 输入校验、会话与快照 | events.py |\n| 回放、预算、线程与时间线 | runner.py |\n| 请求与响应适配 | backends.py、native.py |\n| 服务生命周期 | deployment.py、cli.py |\n| 工作负载与实验套件 | workloads.py、suite.py |\n| 结果指标与身份记录 | report.py、identity.py |\n\n文中图示反映当前实现。主计算路径为本机 vLLM HTTP 服务；当前输入为帧与文字问题，采用历史图片前缀重放。\n'
(here/'管线设计图解.md').write_text(report,encoding='utf-8')
import markdown
css='body{font-family:"Microsoft YaHei",Arial,sans-serif;color:#203448;max-width:1200px;margin:36px auto;padding:0 24px;line-height:1.9}h1,h2{color:#16324f}h2{margin-top:50px}p{font-size:18px}img{width:100%;height:auto;display:block;margin:24px 0}table{border-collapse:collapse;width:100%}th,td{border:1px solid #cbd5df;padding:10px;text-align:left}a{color:#087f8c;overflow-wrap:anywhere}pre{white-space:pre-wrap}hr{border:0;border-top:1px solid #cbd5df;margin:36px 0}'
for stem in ['管线设计图解','逐页讲稿']:
    body=markdown.markdown((here/(stem+'.md')).read_text(encoding='utf-8'),extensions=['tables'])
    if stem=='管线设计图解':
        for f in files:body=body.replace('图源/'+f.name,'data:image/svg+xml;base64,'+base64.b64encode(f.read_bytes()).decode())
    (here/(stem+'.html')).write_text(f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{stem}</title><style>{css}</style><body>{body}</body></html>',encoding='utf-8')
preview='<meta charset="utf-8"><title>管线设计预览</title><style>body{margin:0;background:#dce3ea}.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;padding:20px}img{width:100%;display:block}</style><div class="grid">'
for f in files:preview+='<img src="data:image/svg+xml;base64,'+base64.b64encode(f.read_bytes()).decode()+'">'
(here/'PPT预览.html').write_text(preview+'</div>',encoding='utf-8')
art=['StreamVLM管线设计_汇报版.pptx','管线设计图解.md','管线设计图解.html','逐页讲稿.md','逐页讲稿.html','PPT预览.html']
(here/'交付核对.json').write_text(json.dumps({'slides':len(items),'notes':len(items),'checks':checks,'files':{f:hashlib.sha256((here/f).read_bytes()).hexdigest() for f in art}},ensure_ascii=False,indent=2),encoding='utf-8')
print('published:',len(items),'editable slides and speaker notes, illustrated report')
