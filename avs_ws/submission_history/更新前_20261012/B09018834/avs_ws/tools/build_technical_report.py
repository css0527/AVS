"""从 TECHNICAL_REPORT.md 生成技术报告 PDF（需要 reportlab）。"""
from pathlib import Path
import argparse
import re
from xml.sax.saxutils import escape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.utils import ImageReader
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, KeepTogether

WS = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, default=WS.parents[1] / 'technical_report.pdf',
                    help='生成 PDF 的保存路径')
OUTPUT = parser.parse_args().output
pdfmetrics.registerFont(TTFont('Chinese', '/usr/share/fonts/truetype/arphic/uming.ttc'))
body = ParagraphStyle('body', fontName='Chinese', fontSize=10, leading=16, spaceAfter=7, wordWrap='CJK')
heading = ParagraphStyle('heading', parent=body, fontSize=14, leading=21, spaceBefore=13, spaceAfter=8, keepWithNext=True, textColor=colors.HexColor('#18364b'))
title = ParagraphStyle('title', parent=heading, fontSize=21, leading=30, alignment=TA_CENTER, spaceAfter=17)
caption = ParagraphStyle('caption', parent=body, fontSize=9, leading=14, textColor=colors.HexColor('#53616c'), alignment=TA_CENTER)
cell = ParagraphStyle('cell', parent=body, fontSize=9, leading=14, spaceAfter=0)

def inline(text):
    text = escape(text)
    text = re.sub(r'`([^`]+)`', r'<font color="#254b67">\1</font>', text)
    return re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1', text)

def footer(canvas, doc):
    canvas.setFont('Chinese', 8)
    canvas.setFillColor(colors.HexColor('#68747e'))
    canvas.drawString(42, 25, 'Simulator · B09018834 | 无人车仿真组技术实施报告')
    canvas.drawRightString(553, 25, str(doc.page))

lines = (WS/'TECHNICAL_REPORT.md').read_text().splitlines()
story = []
i = 0
while i < len(lines):
    line = lines[i].strip()
    if not line:
        i += 1
        continue
    if line.startswith('# '):
        story.append(Paragraph(inline(line[2:]), title))
    elif line.startswith('## '):
        story.append(Paragraph(inline(line[3:]), heading))
    elif line.startswith('!['):
        match = re.fullmatch(r'!\[([^\]]*)\]\(([^)]+)\)', line)
        path = WS / match[2]
        w, h = ImageReader(str(path)).getSize()
        maxw = 511 if 'slam_map' not in str(path) else 190
        factor = min(maxw/w, 280/h)
        figure = Image(str(path), width=w*factor, height=h*factor)
        group = [Spacer(1, 6), figure, Spacer(1, 5)]
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j < len(lines) and lines[j].startswith('图 '):
            group.append(Paragraph(inline(lines[j]), caption))
            i = j
        story.append(KeepTogether(group))
    elif line.startswith('|'):
        rows = []
        while i < len(lines) and lines[i].strip().startswith('|'):
            parts = [x.strip() for x in lines[i].strip().strip('|').split('|')]
            if not all(re.fullmatch(r':?-+:?', x) for x in parts):
                rows.append([Paragraph(inline(x), cell) for x in parts])
            i += 1
        table = Table(rows, colWidths=[245, 266], repeatRows=1, hAlign='LEFT')
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e5edf3')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f6f8fa')]),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LINEBELOW', (0, 0), (-1, 0), 0.6, colors.HexColor('#bccad5')),
        ]))
        story.extend([table, Spacer(1, 10)])
        continue
    else:
        story.append(Paragraph(inline(line), body))
    i += 1
SimpleDocTemplate(str(OUTPUT), pagesize=(595.276, 841.89), rightMargin=42, leftMargin=42, topMargin=38, bottomMargin=43, title='无人车仿真组技术实施报告', author='Simulator（B09018834）').build(story, onFirstPage=footer, onLaterPages=footer)
print(OUTPUT)
