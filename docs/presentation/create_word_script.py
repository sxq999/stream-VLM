"""Create the eight-page speaker manuscript with one reference slide per page."""
import argparse,json,re,zipfile
from pathlib import Path
from docx import Document
from docx.shared import Cm,Pt,RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

p=argparse.ArgumentParser();p.add_argument('--figures',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
root=Path(__file__).resolve().parent
sections=json.loads((root/'word-script.json').read_text(encoding='utf-8'))
slides=json.loads((root/'content.json').read_text(encoding='utf-8'))
assert len(sections)==len(slides)==8
assert [s['title'] for s in sections]==[s['title'] for s in slides]
assert not a.out.exists(),'use a fresh output filename or review before overwriting'
doc=Document();sec=doc.sections[0]
sec.page_width=Cm(21);sec.page_height=Cm(29.7)
sec.top_margin=Cm(1.6);sec.bottom_margin=Cm(1.6);sec.left_margin=Cm(2);sec.right_margin=Cm(2)
sec.footer_distance=Cm(.7)
for name in ['Normal','Title','Subtitle','Heading 1','Heading 2','Caption']:
    st=doc.styles[name];st.font.name='Arial';st.font.color.rgb=RGBColor(0,0,0)
    rf=st.element.get_or_add_rPr().get_or_add_rFonts();rf.set(qn('w:eastAsia'),'宋体');rf.set(qn('w:ascii'),'Arial');rf.set(qn('w:hAnsi'),'Arial')
    lang=OxmlElement('w:lang');lang.set(qn('w:val'),'en-US');lang.set(qn('w:eastAsia'),'zh-CN');st.element.get_or_add_rPr().append(lang)
    st.font.underline=False
for st in doc.styles:
    for border in st.element.xpath('.//w:pBdr'):border.getparent().remove(border)
normal=doc.styles['Normal'];normal.font.size=Pt(12.5)
normal.paragraph_format.line_spacing=1.45;normal.paragraph_format.space_after=Pt(6)
normal.paragraph_format.widow_control=True
title=doc.styles['Title'];title.font.size=Pt(18);title.font.bold=True;title.paragraph_format.space_after=Pt(6)
heading=doc.styles['Heading 1'];heading.font.size=Pt(15);heading.font.bold=True;heading.paragraph_format.space_before=Pt(0);heading.paragraph_format.space_after=Pt(6)
caption=doc.styles['Caption'];caption.font.size=Pt(9);caption.font.italic=False;caption.paragraph_format.space_after=Pt(8)
doc.core_properties.title='StreamVLM 管线设计逐页讲稿';doc.core_properties.subject='八页 PPT 对应的口语汇报讲稿';doc.core_properties.author='StreamVLM 项目';doc.core_properties.keywords='StreamVLM 管线设计 逐页讲稿'
doc.core_properties.comments=''
for i,s in enumerate(sections,1):
    if i>1:doc.add_page_break()
    if i==1:
        doc.add_paragraph('StreamVLM 管线设计逐页讲稿',style='Title')
        intro=doc.add_paragraph('对应八页汇报版 PPT  建议主讲十至十二分钟')
        intro.paragraph_format.space_after=Pt(8)
        for r in intro.runs:r.font.size=Pt(10)
    doc.add_paragraph(f'第 {i} 页  {s["title"]}',style='Heading 1')
    image=a.figures/f'{i:02d}.png';assert image.is_file(),image
    par=doc.add_paragraph();par.alignment=WD_ALIGN_PARAGRAPH.CENTER;par.paragraph_format.space_after=Pt(2)
    par.add_run().add_picture(str(image),width=Cm(14.6))
    cap=doc.add_paragraph(f'对应 PPT 第 {i} 页',style='Caption');cap.alignment=WD_ALIGN_PARAGRAPH.CENTER
    for text in s['paragraphs']:
        par=doc.add_paragraph(text)
        par.paragraph_format.first_line_indent=Pt(25)
    if i==8:
        par=doc.add_paragraph('代码依据  github.com/sxq999/stream-VLM/tree/34b4218/src/stream_pipeline')
        par.paragraph_format.space_before=Pt(6)
        for r in par.runs:r.font.size=Pt(9)
for par in doc.paragraphs:
    kinsoku=OxmlElement('w:kinsoku');kinsoku.set(qn('w:val'),'1');par._p.get_or_add_pPr().append(kinsoku)
footer=sec.footer.paragraphs[0];footer.alignment=WD_ALIGN_PARAGRAPH.CENTER
run=footer.add_run('第 ');run.font.size=Pt(9)
fld=OxmlElement('w:fldSimple');fld.set(qn('w:instr'),'PAGE');footer._p.append(fld)
run=footer.add_run(' 页');run.font.size=Pt(9)
doc.save(a.out)
with zipfile.ZipFile(a.out) as z:
    assert z.testzip() is None
    xml=z.read('word/document.xml').decode('utf-8')
    assert xml.count('w:type="page"')==7
    assert len([x for x in z.namelist() if x.startswith('word/media/')])==8
    for s in sections:
        for text in s['paragraphs']:assert text.replace('&','&amp;').replace('<','&lt;') in xml
print(a.out)
