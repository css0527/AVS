#!/usr/bin/env python3
"""Read-only final verification. Writes only its JSON report to stdout."""
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as E
import hashlib, json, posixpath, re, subprocess

ROOT = Path('/home/c/AVS')
D = ROOT / '国赛答辩'
A = D / '配音制作'
NS = {'p':'http://schemas.openxmlformats.org/presentationml/2006/main',
      'a':'http://schemas.openxmlformats.org/drawingml/2006/main',
      'r':'http://schemas.openxmlformats.org/package/2006/relationships'}

def sha_stream(f):
    h = hashlib.sha256()
    for b in iter(lambda:f.read(2**20), b''): h.update(b)
    return h.hexdigest()

def sha(p):
    with p.open('rb') as f: return sha_stream(f)

def run(args): return subprocess.check_output(args, stderr=subprocess.STDOUT).decode()

def probe(p): return json.loads(run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(p)]))

def video_hash(p):
    return run(['ffmpeg','-v','error','-i',str(p),'-map','0:v:0','-c:v','copy','-f','hash','-hash','sha256','-']).strip()

def canon(s): return re.sub(r'\s+', '', s)

plan = json.loads((A/'配音时间线.json').read_text())
proof = json.loads((A/'音画核对.json').read_text())
content = json.loads((D/'roadshow_content.json').read_text())
output = ROOT/plan['output_video']
source = ROOT/plan['source_video']
hash_final = sha(output)
paths = [output,D/'B09018834.mp4',ROOT/'avs_ws/submission/B09018834.mp4']
result = {'final_video_hash':hash_final,
          'external_video_copies_match':{str(p.relative_to(ROOT)):sha(p)==hash_final for p in paths},
          'proof_hash_matches':proof.get('video_sha256')==hash_final,
          'proof_status_complete':proof.get('status')=='complete',
          'plan_status_complete':plan.get('status')=='complete',
          'video_stream_unchanged':video_hash(source)==video_hash(output)}
vp = probe(output)
result['duration_seconds'] = float(vp['format']['duration'])
result['video_frames'] = [int(s['nb_frames']) for s in vp['streams'] if s['codec_type']=='video']
result['audio_streams'] = sum(s['codec_type']=='audio' for s in vp['streams'])
result['subtitle_streams'] = sum(s['codec_type']=='subtitle' for s in vp['streams'])
result['all_segments_fit_windows'] = all(row['start']<=row['actual_start']<row['actual_end']<=row['end']<=plan['video_duration_seconds'] for row in proof['segments'])
result['segments_do_not_overlap'] = all(a['actual_end']<=b['actual_start'] for a,b in zip(proof['segments'],proof['segments'][1:]))
result['final_metrics_only_after_complete'] = next(row['actual_start'] for row in proof['segments'] if '返航' in row['text'] and '四点三' in row['text'])>=161.25

with ZipFile(D/'AVS_国赛答辩.pptx') as z:
    slides = sorted((n for n in z.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml',n)), key=lambda n:int(re.search(r'(\d+)\.xml',n).group(1)))
    result['slides'] = len(slides)
    result['hidden_slide_numbers'] = [i for i,n in enumerate(slides,1) if E.fromstring(z.read(n)).get('show')=='0']
    movie_entries = [n for n in z.namelist() if n.startswith('ppt/media/') and n.lower().endswith(('.mp4','.m4v','.mov'))]
    result['embedded_movie_entries'] = movie_entries
    embedded_hashes = {}
    for n in movie_entries:
        with z.open(n) as f: embedded_hashes[n] = sha_stream(f)
    result['embedded_movie_hashes'] = embedded_hashes
    result['embedded_movie_hash_matches'] = bool(embedded_hashes) and all(h==hash_final for h in embedded_hashes.values())
    rel = E.fromstring(z.read('ppt/slides/_rels/slide3.xml.rels'))
    targets = [posixpath.normpath(posixpath.join('ppt/slides',r.get('Target'))) for r in rel if r.get('Type','').endswith(('/video','/media'))]
    result['slide3_movie_targets'] = targets
    result['slide3_uses_matching_embedded_movie'] = bool(targets) and all(t in embedded_hashes and embedded_hashes[t]==hash_final for t in targets)
    note_texts = []
    for i in range(1,len(slides)+1):
        note = E.fromstring(z.read(f'ppt/notesSlides/notesSlide{i}.xml'))
        body = next(sp for sp in note.findall('.//p:sp',NS) if any(ph.get('type')=='body' for ph in sp.findall('./p:nvSpPr/p:nvPr/p:ph',NS)))
        note_texts.append('\n'.join(''.join(p.itertext()) for p in body.findall('./p:txBody/a:p',NS)))
    md = (D/'AVS_国赛答辩逐页讲稿.md').read_text()
    sections = re.split(r'(?m)(?=^## 第\d+页｜)',md)[1:]
    result['script_note_alignment'] = len(sections)==len(note_texts) and all(canon(m)==canon(n) for m,n in zip(sections,note_texts))
    result['notes_have_no_pending_audio_status'] = not any(s in '\n'.join(note_texts) for s in ['音轨尚未','尚未按新稿','没有改视频画面、时长或音轨'])

cjk = lambda s: ''.join(re.findall(r'[\u4e00-\u9fff]',s))
voice = cjk(''.join(row['text'] for row in plan['segments']))
speech = cjk(''.join(s.get('speech','') for s in content['slides'] if not s.get('backup')))
result['voice_cjk_chars'] = len(voice)
result['spoken_cjk_chars'] = len(speech)
result['shared_10_character_spoken_phrases'] = sorted({voice[i:i+10] for i in range(len(voice)-9)} & {speech[i:i+10] for i in range(len(speech)-9)})
result['video_metric_repetition'] = any(s in speech for s in ['九十九点六','七点五到十三点九','四点三厘米'])
result['pdf_pages'] = int(re.search(r'(?m)^Pages:\s*(\d+)',run(['pdfinfo',str(D/'AVS_国赛答辩.pdf')])).group(1))
result['preview_pages'] = len([p for p in (D/'预览/路演新版').glob('*.jpg') if re.fullmatch(r'\d{2}\.jpg',p.name)])
result['main_slides'] = len(slides)-len(result['hidden_slide_numbers'])
result['target_seconds'] = sum(float(s.get('seconds',0)) for s in content['slides'] if not s.get('backup') and s.get('layout')!='video')+result['duration_seconds']+8

stale = {}
for p in [D/'AVS_国赛答辩逐页讲稿.md', D/'AVS_国赛答辩逐页讲稿.txt', D/'PPT更新说明.md', ROOT/'AVS作品配音讲稿与评分自评.md', ROOT/'avs_ws/docs/submission_voiceover.md',ROOT/'avs_ws/submission/B09018834/avs_ws/docs/submission_voiceover.md']:
    text = p.read_text()
    matches=[{'line':i,'text':line} for i,line in enumerate(text.splitlines(),1) if any(s in line for s in ['音轨尚未','尚未按新稿','没有改视频画面、时长或音轨','配音制作中','PDF 为静态 17 页'])]
    if matches: stale[str(p.relative_to(ROOT))]=matches
result['stale_audio_or_page_status'] = stale
checks = [*result['external_video_copies_match'].values(),result['proof_hash_matches'],result['proof_status_complete'],result['plan_status_complete'],result['video_stream_unchanged'],result['audio_streams']==1,result['subtitle_streams']==0,result['all_segments_fit_windows'],result['segments_do_not_overlap'],result['final_metrics_only_after_complete'],result['slides']==18,result['hidden_slide_numbers']==[15,16,17,18],result['embedded_movie_hash_matches'],result['slide3_uses_matching_embedded_movie'],result['script_note_alignment'],result['notes_have_no_pending_audio_status'],not result['video_metric_repetition'],result['pdf_pages']==18,result['preview_pages']==18,not stale]
result['all_automated_checks_pass'] = all(checks)
print(json.dumps(result,ensure_ascii=False,indent=2))
