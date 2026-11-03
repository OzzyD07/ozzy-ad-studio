"""Render all four Remotion compositions from synthetic fixtures (no GPU, no MCP).

Output: workspace/remotion-smoke/<time>/ — ad.mp4, promo.mp4, post.png, carousel/01..03.png and frame sheets.
"""
import json
import subprocess
from datetime import datetime
from pathlib import Path

import media
import pipeline
import render

root = Path(__file__).resolve().parent
cfg = pipeline.config(root/'config.json')
cfg['video'] = {**cfg.get('video', {}), 'preset': 'veryfast'}
cfg['end_card'] = {**cfg.get('end_card', {}), 'enabled': True}
out = root/'workspace'/'remotion-smoke'/datetime.now().strftime('%Y%m%d-%H%M%S')
fx = out/'fixtures'
fx.mkdir(parents=True)
ff = [media.ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y']


def clip(name, colors, seconds, freq):
    # 768x1344 is MiniMax H3's 9:16 output size; a tone stands in for the generated speech.
    path = fx/name
    subprocess.run(ff + ['-f', 'lavfi', '-i', f'gradients=s=768x1344:r=24:d={seconds}:speed=0.04:c0={colors[0]}:c1={colors[1]}',
                         '-f', 'lavfi', '-i', f'sine=frequency={freq}:duration={seconds}', '-shortest',
                         '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(path)], check=True)
    return str(path)


def image(name, colors, size):
    path = fx/name
    subprocess.run(ff + ['-f', 'lavfi', '-i', f'gradients=s={size}:c0={colors[0]}:c1={colors[1]}:n=3',
                         '-frames:v', '1', str(path)], check=True)
    return str(path)


line = 'Your week feels blurry? Write one line a day and MentorAi shows the pattern in 7 days.'
words = [{'text': w, 'start': round(0.4 + i * 0.36, 2), 'end': round(0.4 + i * 0.36 + 0.32, 2)}
         for i, w in enumerate(line.split())]
icon = root/'workspace'/'apps'/'mentorai'/'assets'/'app-icon.png'
icon = str(icon) if icon.is_file() else image('icon.png', ('0xff5a36', '0x7a1cff'), '512x512')
shot = image('screen.png', ('0x101820', '0x3b5bdb'), '1080x2340')
cfg['end_card']['icon'] = icon
cfg['app'] = {'name': 'MentorAi'}
cfg['cta'] = {'text': 'Try it free'}

specs = {
    'ad.mp4': ('AdVideo', {
        'clips': [{'src': clip('a.mp4', ('0x1d2b64', '0xf8cdda'), 4, 220)},
                  {'src': clip('b.mp4', ('0x134e5e', '0x71b280'), 4, 330)},
                  {'src': clip('c.mp4', ('0x42275a', '0x734b6d'), 4, 440), 'fit': 'contain-blur'}],
        'transition': {'type': 'fade', 'seconds': 0.35},
        'captions': {'words': words, 'style': 'pop', 'emphasis': ['MentorAi'], 'language': 'en'},
        'hookText': 'POV: every day feels the same',
    }),
    'promo.mp4': ('TemplatePromo', {
        'scenes': [{'duration': 2.6, 'kicker': 'New in MentorAi', 'title': 'Your week in *one* score'},
                   {'duration': 3.2, 'title': 'Write one line', 'body': 'We find the *pattern* for you.',
                    'media': {'src': shot, 'device': 'phone'}},
                   {'duration': 2.6, 'title': 'See it in *7 days*'}],
        'captions': {'words': words, 'style': 'box', 'emphasis': ['MentorAi'], 'language': 'en'},
    }),
    'post.png': ('PostStill', {
        'background': image('bg.jpg', ('0x2b5876', '0x4e4376'), '1080x1350'),
        'kicker': 'Journaling tip', 'title': 'One line a day beats *one page* a month',
        'body': 'Small entries, real patterns.', 'icon': icon, 'appName': 'MentorAi', 'cta': 'Try free'}),
    'carousel': ('Carousel', {'slides': [
        {'title': '3 signs you need a *reset*', 'layout': 'center'},
        {'kicker': '1', 'title': 'Every day feels the *same*', 'background': image('s2.jpg', ('0x0f2027', '0x2c5364'), '1080x1350')},
        {'kicker': '2', 'title': 'Start with *one line* tonight', 'icon': icon, 'appName': 'MentorAi', 'cta': 'Try free'}]}),
}
for name, (composition, props) in specs.items():
    print(composition, '→', out/name, flush=True)
    for path in render.render(composition, props, out/name, cfg):
        if path.suffix == '.mp4':
            media.contact_sheet(path, path.with_suffix('.sheet.png'))
            print(' ', path, json.dumps(media.probe(path)))
        else:
            print(' ', path)
print('OK', out)
