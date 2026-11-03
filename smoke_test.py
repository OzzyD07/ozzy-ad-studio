"""Exercise the real renderer and MCP transport using a local synthetic fixture."""
import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import media
import pipeline

root = Path(__file__).resolve().parent
cfg = pipeline.config(root/'config.json')
ws = root/'workspace'/'smoke'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
cfg['workspace'] = str(ws)
pipeline.initialize(cfg)
# The smoke run is an app of its own, like any real product.
pipeline.new_app(cfg, 'smoke', 'Smoke')
ws, cfg = pipeline.open_app(cfg, 'smoke')
raw = ws/'fixture.mp4'
ff = [media.ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y']
# 768x1344 is MiniMax H3's 9:16 output size.
subprocess.run(ff + ['-f', 'lavfi', '-i', 'testsrc2=s=768x1344:r=24:d=6',
    '-f', 'lavfi', '-i', 'sine=frequency=440:duration=6', '-c:v', 'libx264',
    '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(raw)], check=True)
# Stand-ins for the official store badges and the app icon (real ones go in assets/).
badges = ws/'badges'
badges.mkdir()
subprocess.run(ff + ['-f', 'lavfi', '-i', 'color=c=black:s=400x134', '-frames:v', '1', str(badges/'app-store.png')], check=True)
subprocess.run(ff + ['-f', 'lavfi', '-i', 'color=c=0x1a73e8:s=448x134', '-frames:v', '1', str(badges/'google-play.png')], check=True)
subprocess.run(ff + ['-f', 'lavfi', '-i', 'color=c=0xff5a36:s=512x512', '-frames:v', '1', str(ws/'icon.png')], check=True)
log = ws/'mcp.log'
cfg['mcp'].update(transport='stdio', command=sys.executable, args=[str(root/'tests'/'mock_mcp.py')],
    env={'TEST_VIDEO_PATH': str(raw), 'TEST_LOG': str(log)}, timeout_seconds=30)
cfg['video']['preset'] = 'veryfast'
cfg['end_card'] = {'enabled': True, 'seconds': 3, 'extend_seconds': 1.5, 'icon': str(ws/'icon.png'),
                   'badges_dir': str(badges), 'stores': ['app_store', 'google_play']}

# 1) Single-shot job: generate → poll → render with SRT, end card with PNG badges.
pipeline.write(ws/'jobs'/'smoke.json', {'id': 'smoke', 'prompt': 'sentetik test',
    'status': 'planned', 'caption': 'Bu gerçek bir ürün reklamı değildir; işlem testi.',
    'cta': 'Hemen keşfet', 'app_name': 'Demo', 'hook_text': 'Test kancası', 'remote_id': None})
pipeline.generate(argparse.Namespace(id='smoke', poll=False), cfg, ws)
assert pipeline.read(ws/'jobs'/'smoke.json')['status'] == 'waiting'
pipeline.generate(argparse.Namespace(id='smoke', poll=True), cfg, ws)
assert pipeline.read(ws/'jobs'/'smoke.json')['status'] == 'raw_ready'
pipeline.render_job(argparse.Namespace(id='smoke', srt=str(root/'examples'/'demo.srt'), no_subtitles=False), cfg, ws)
assert pipeline.read(ws/'jobs'/'smoke.json')['status'] == 'done'
out = ws/'exports'/'smoke'
assert (out/'caption.txt').read_text(encoding='utf-8').startswith('Bu gerçek')
meta = json.loads((out/'metadata.json').read_text(encoding='utf-8'))
assert abs(meta['duration'] - 7.5) < .2 and meta['end_card']['drawn'] == [], meta
print('PASS: tek çekim — MCP generate/poll → altyazı + hook + rozetli bitiş kartı')

# 2) Multi-shot plan with A/B hooks: shared body, continuity references, montage, render.
pipeline.plan(root/'examples'/'product.multishot.example.json', root/'examples'/'research.example.json',
              '2026-11-01', 1, ws)
parents = [pipeline.read(p) for p in (ws/'jobs').glob('2026-*.json') if pipeline.read(p).get('role') == 'edit']
assert len(parents) == 2
for p in parents:
    (ws/'raw'/f"{p['id']}.srt").write_text('1\n00:00:00,300 --> 00:00:03,000\nDoes every day feel the same?\n\n'
                                           '2\n00:00:05,800 --> 00:00:09,500\nWrite three lines and pick your mood.\n'
                                           '\n3\n00:00:09,800 --> 00:00:11,000\nTry DemoApp.\n', encoding='utf-8')
for _ in range(6):
    pipeline.run_queue(argparse.Namespace(limit=10), cfg, ws)
    if all(pipeline.complete(pipeline.read(p)) for p in (ws/'jobs').glob('*.json')):
        break
for p in parents:
    job = pipeline.read(ws/'jobs'/f"{p['id']}.json")
    assert job['status'] == 'done', job['status']
    assert abs(job['assembled_duration'] - (12 - .35)) < .1, job['assembled_duration']
calls = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
body = [c for c in calls if c['tool'] == 'generate' and c['images']]
assert len(body) == 1 and len(body[0]['audios']) == 1 and body[0]['ref_image_size'] == 'max', body
print('PASS: çok çekim — 2 hook varyantı + ortak gövde, süreklilik referansı, montaj, render')
sheet = ws/'preview.png'
first = ws/'exports'/parents[0]['id']/'video.mp4'
inputs = sum([['-ss', str(t), '-i', str(first)] for t in (1, 6, 10.5, 12.5)], [])
subprocess.run(ff + inputs + ['-filter_complex', '[0:v][1:v][2:v][3:v]hstack=4,scale=1440:-2',
                              '-frames:v', '1', str(sheet)], check=True)
print('PREVIEW: ' + str(sheet))
