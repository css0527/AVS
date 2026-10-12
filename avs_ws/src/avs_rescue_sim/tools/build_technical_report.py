#!/usr/bin/env python3
"""Render the maintained technical report and an optional measured-run appendix."""
import argparse
import json
import re
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph,
                               SimpleDocTemplate, Spacer, Table, TableStyle)

WORKSPACE = Path(__file__).resolve().parents[3]


def inline(text):
    """Escape ReportLab markup before supporting our small Markdown subset."""
    text = escape(text)
    text = re.sub(r'`([^`]+)`', r'<font color="#254b67">\1</font>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)
    return re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1', text)


def build_report(markdown, output, *, acceptance=None):
    markdown, output = Path(markdown), Path(output)
    pdfmetrics.registerFont(TTFont('AVSChinese',
        '/usr/share/fonts/truetype/arphic/uming.ttc', subfontIndex=0))
    body = ParagraphStyle('body', fontName='AVSChinese', fontSize=10,
        leading=16, spaceAfter=7, wordWrap='CJK')
    heading = ParagraphStyle('heading', parent=body, fontSize=14,
        leading=21, spaceBefore=13, spaceAfter=8, keepWithNext=True,
        textColor=colors.HexColor('#18364b'))
    subheading = ParagraphStyle('subheading', parent=heading, fontSize=11.5,
        leading=18, spaceBefore=9)
    title = ParagraphStyle('title', parent=heading, fontSize=21,
        leading=30, alignment=TA_CENTER, spaceAfter=17)
    caption = ParagraphStyle('caption', parent=body, fontSize=9, leading=14,
        textColor=colors.HexColor('#53616c'), alignment=TA_CENTER)
    cell = ParagraphStyle('cell', parent=body, fontSize=9, leading=14,
        spaceAfter=0)
    width = A4[0] - 84
    story = []

    def add_table(rows):
        count = len(rows[0])
        widths = ([width * .42, width * .58] if count == 2 else
                  [width / count] * count)
        table = Table([[Paragraph(inline(str(x)), cell) for x in row]
                      for row in rows], colWidths=widths, repeatRows=1,
                      hAlign='LEFT')
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e5edf3')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1),
             [colors.white, colors.HexColor('#f6f8fa')]),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 7),
            ('RIGHTPADDING', (0, 0), (-1, -1), 7),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LINEBELOW', (0, 0), (-1, 0), .6,
             colors.HexColor('#bccad5')),
        ]))
        story.extend([table, Spacer(1, 10)])

    def add_image(path, text=None, max_height=280):
        w, h = ImageReader(str(path)).getSize()
        factor = min(width / w, max_height / h)
        group = [Spacer(1, 6), Image(str(path), width=w * factor,
                 height=h * factor), Spacer(1, 5)]
        if text:
            group.append(Paragraph(inline(text), caption))
        story.append(KeepTogether(group))

    lines = markdown.read_text(encoding='utf-8').splitlines()
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
        elif line.startswith('### '):
            story.append(Paragraph(inline(line[4:]), subheading))
        elif line.startswith('!['):
            match = re.fullmatch(r'!\[([^\]]*)\]\(([^)]+)\)', line)
            if not match:
                raise ValueError(f'Invalid report image line: {line}')
            image_path = markdown.parent / match[2]
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            text = None
            if j < len(lines) and lines[j].startswith('图 '):
                text, i = lines[j], j
            add_image(image_path, text)
        elif line.startswith('|'):
            rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                parts = [x.strip() for x in
                         lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-+:?', x) for x in parts):
                    rows.append(parts)
                i += 1
            add_table(rows)
            continue
        elif line.startswith('- '):
            story.append(Paragraph(inline(line[2:]), body, bulletText='•'))
        else:
            paragraph = [line]
            while (i + 1 < len(lines) and lines[i + 1].strip()
                   and not lines[i + 1].lstrip().startswith(('#', '|', '![', '- '))):
                i += 1
                paragraph.append(lines[i].strip())
            story.append(Paragraph(inline(' '.join(paragraph)), body))
        i += 1

    if acceptance is not None:
        acceptance = Path(acceptance)
        evidence = json.loads((acceptance / 'evaluation.json').read_text())
        story.extend([PageBreak(), Paragraph('附录：整车演示验收记录', heading),
            Paragraph(inline(f'运行目录：{acceptance.name}。下表只使用该目录的 '
                'evaluation.json。无界面速度对比实验见正文第 7 章。'), body)])
        def measured(name, precision=4, unit=''):
            value = evidence.get(name)
            return '未记录' if value is None else f'{value:.{precision}f}{unit}'
        rows = [['指标', '本次实测'],
                ['自动验收', '通过' if evidence.get('passed') else '未通过'],
                ['任务完成', '是' if evidence.get('mission_complete') else '否'],
                ['采集运行时长（含启动、采集尾段）',
                 measured('duration_wall_s', 2, ' s')],
                ['走廊类别', ', '.join(evidence.get('corridor_labels', []))],
                ['箱体实际位移', measured('barrier_displacement_m', 4, ' m')],
                ['返航位置误差', measured('return_error_m', 4, ' m')],
                ['红箱检测帧数', evidence.get('barrier_detection_frames', '未记录')],
                ['独立在线 SLAM 留档', '已记录' if
                 evidence.get('online_slam_recorded') else '未记录'],
                ['墙体轮廓重叠采样数', len(evidence.get('wall_overlap_samples', []))]]
        for tag, err in sorted((evidence.get('core_marker_errors_m') or {}).items()):
            rows.append([f'Tag {tag} 同坐标系平面误差',
                         '无坐标转换记录' if err is None else f'{err:.4f} m'])
        add_table(rows)
        story.append(Paragraph('Marker 误差以记录的 map←odom 变换将真实位置与视觉结果'
            '放到同一坐标系后比较；原始 world/map 坐标差保留在 JSON。'
            '墙体检查采用离散采样完整轮廓，不等同于连续接触传感器。', body))
        for name, text in [('trajectory.png', '图 附录 A：本次验收工具根据真实模型位姿绘制的轨迹；任务节点不读取该真值。'),
                           ('slam_map.png', '图 附录 B：本次独立 slam_toolbox 留档的占据栅格，未替换导航原图。')]:
            path = acceptance / name
            if path.is_file():
                add_image(path, text, max_height=310)

    def footer(canvas, doc):
        canvas.setFont('AVSChinese', 8)
        canvas.setFillColor(colors.HexColor('#68747e'))
        canvas.drawString(42, 25, 'AVS 救援巡检平台 | 无人车仿真组技术实施报告')
        canvas.drawRightString(A4[0] - 42, 25, str(doc.page))

    output.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(output), pagesize=A4, rightMargin=42,
        leftMargin=42, topMargin=38, bottomMargin=43,
        title='无人车仿真组技术实施报告', author='Simulator 队').build(story,
        onFirstPage=footer, onLaterPages=footer)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--markdown', type=Path,
                        default=WORKSPACE / 'TECHNICAL_REPORT.md')
    parser.add_argument('--acceptance', type=Path)
    parser.add_argument('--output', type=Path,
                        default=WORKSPACE / 'submission/technical_report.pdf')
    args = parser.parse_args()
    print(build_report(args.markdown, args.output, acceptance=args.acceptance))


if __name__ == '__main__':
    main()
