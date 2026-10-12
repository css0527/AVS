"""Inventory source images without altering them; select raw-frame review sheets."""
from pathlib import Path
from collections import Counter, defaultdict
import csv
import hashlib
import json
import sys

sys.path.insert(0, '/tmp/avs_ppt_deps')

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / '创新点PPT/图片审查'
EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.svg', '.pgm', '.ppm', '.gif', '.tif', '.tiff'}
FONT = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'


def group(path):
    parts = path.relative_to(ROOT).parts
    if parts[:2] == ('avs_ws', 'acceptance'):
        return '/'.join(parts[:3])
    if parts[:2] in (('avs_ws', 'build'), ('avs_ws', 'install'), ('avs_ws', 'submission')):
        return '/'.join(parts[:3])
    return '/'.join(parts[:2])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows, raw = [], defaultdict(list)
    for path in sorted(ROOT.rglob('*')):
        if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
            continue
        rel = path.relative_to(ROOT)
        if '.git' in rel.parts or rel.parts[:2] == ('创新点PPT', '图片审查'):
            continue
        if '历史版本' in rel.parts or '新版' in rel.parts or '预览' in rel.parts:
            continue
        row = dict(path=str(rel), group=group(path), bytes=path.stat().st_size,
                   sha256=hashlib.sha256(path.read_bytes()).hexdigest(), width='', height='', status='ok')
        try:
            with Image.open(path) as im:
                row.update(width=im.width, height=im.height)
                if 'raw_images' in rel.parts:
                    small = np.asarray(im.convert('RGB').resize((32, 24)), dtype=float)
                    raw[group(path)].append((path, small))
                im.load()
        except Exception as exc:
            row['status'] = type(exc).__name__ + ': ' + str(exc)
        rows.append(row)
    with (OUT / '项目图片清单.csv').open('w', newline='', encoding='utf-8-sig') as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = dict(total=len(rows), unique_sha256=len({r['sha256'] for r in rows}),
                   groups=dict(Counter(r['group'] for r in rows)),
                   unreadable=[r for r in rows if r['status'] != 'ok'],
                   method='全量读取尺寸和文件哈希；原始视频帧按时间覆盖与画面变化选取缩略图；入选PPT图片另做逐张视觉复核。',
                   raw_review_sheets=[])
    font = ImageFont.truetype(FONT, 18)
    for key, frames in raw.items():
        # All raw frames are decoded; temporal samples plus largest visual changes
        # retain diverse views instead of thousands of nearly identical images.
        changes = np.array([0.] + [np.mean(np.abs(frames[i][1]-frames[i-1][1])) for i in range(1, len(frames))])
        selected = set(np.linspace(0, len(frames)-1, min(32, len(frames))).round().astype(int))
        for i in np.argsort(changes)[::-1]:
            if len(selected) >= 48:
                break
            if all(abs(int(i)-j) > 5 for j in selected):
                selected.add(int(i))
        picks = [frames[i][0] for i in sorted(selected)]
        sheet = Image.new('RGB', (1920, 1360), '#101b2c')
        draw = ImageDraw.Draw(sheet)
        draw.text((16, 10), key + '｜原始图：时间覆盖与画面变化筛选', font=font, fill='#ffffff')
        for i, path in enumerate(picks):
            x, y = 10+(i%8)*239, 55+(i//8)*213
            with Image.open(path) as im:
                im = im.convert('RGB')
                im.thumbnail((229, 172), Image.Resampling.LANCZOS)
                sheet.paste(im, (x, y))
            draw.text((x, y+176), path.name, font=font, fill='#b9cadc')
        target = OUT / (key.split('/')[-1] + '_原始图筛选.jpg')
        sheet.save(target, quality=91)
        summary['raw_review_sheets'].append(dict(path=str(target.relative_to(ROOT)), source_count=len(frames),
                                                  selections=[str(p.relative_to(ROOT)) for p in picks]))
    (OUT / '图片盘点.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(dict(total=summary['total'], unique_sha256=summary['unique_sha256'],
                         groups=summary['groups'], unreadable_count=len(summary['unreadable']),
                         raw_review_sheets=len(summary['raw_review_sheets'])), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
