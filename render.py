"""Remotion bridge: fill defaults from config, stage local media, run remotion/scripts/render.mjs."""
import copy
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import media

ROOT = Path(__file__).resolve().parent
REMOTION = ROOT/'remotion'
COMPOSITIONS = {'AdVideo': 'video', 'TemplatePromo': 'video', 'PostStill': 'still', 'Carousel': 'stills'}
# Prop keys whose string values may be local files; everything else is passed through untouched.
MEDIA_KEYS = {'src', 'icon', 'background', 'badges'}
BADGE_FILES = {'app_store': 'app-store.png', 'google_play': 'google-play.png'}
URL_PREFIXES = ('http://', 'https://', 'data:')
# Remotion merges a composition's Studio demo defaultProps into every render; sending null for optional
# fields the spec leaves out keeps demo captions/texts out of real output.
OPTIONAL = {'AdVideo': ['captions', 'hookText', 'voiceover', 'music'],
            'TemplatePromo': ['captions', 'voiceover', 'music', 'transition'],
            'PostStill': ['background', 'kicker', 'body', 'cta', 'icon', 'appName', 'badges'],
            'Carousel': []}


def words_from_segments(segments):
    """Transcription/alignment segments (media.transcribe, align_script, read_srt) → caption words."""
    words = []
    for s in segments:
        for w in s.get('words') or media.estimate_words(s):
            text = w['text'].strip()
            if text:
                words.append({'text': text, 'start': round(w['start'], 3), 'end': round(w['end'], 3)})
    return words


def resolve(value, base):
    path = Path(value)
    for candidate in ([path] if path.is_absolute() else [Path(base)/path, ROOT/path]):
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError('Remotion girdisi bulunamadı: ' + str(value))


def is_local(value):
    return isinstance(value, str) and not value.startswith(URL_PREFIXES)


def stage(props, public, base):
    """Link every local media file into the public dir; props then reference it by relative name."""
    copied = {}

    def visit(node, key=None):
        if isinstance(node, dict):
            return {k: visit(v, k) for k, v in node.items()}
        if isinstance(node, list):
            return [visit(v, key) for v in node]
        if key in MEDIA_KEYS and is_local(node):
            path = resolve(node, base)
            if path not in copied:
                name = f'm/{len(copied):02d}-{path.name}'
                target = public/name
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.link(path, target)  # Same volume: no copy of multi-GB clips.
                except OSError:
                    shutil.copy2(path, target)
                copied[path] = name
            return copied[path]
        return node
    return visit(props)


def store_badges(cfg, folder):
    """Official badge PNGs with their transparent clear-space trimmed, so both get one height."""
    card = cfg.get('end_card') or {}
    badges_dir = Path(card.get('badges_dir', 'assets/badges'))
    badges_dir = badges_dir if badges_dir.is_absolute() else ROOT/badges_dir
    out = []
    for store in card.get('stores', []):
        source = badges_dir/BADGE_FILES.get(store, store + '.png')
        if not source.is_file():
            continue
        box = media.opaque_box(source)
        target = Path(folder)/('badge-' + source.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if box:
            w, h, x, y = box
            subprocess.run([media.ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-i', str(source),
                            '-vf', f'crop={w}:{h}:{x}:{y}', str(target)], check=True)
        else:
            shutil.copy2(source, target)
        out.append(str(target))
    return out


def with_defaults(composition, props, cfg, base, scratch):
    """Theme, end card, caption language and clip durations from config, unless the spec sets them."""
    props = copy.deepcopy(props)
    for key in OPTIONAL[composition]:
        props.setdefault(key, None)
    if cfg.get('theme') or props.get('theme'):
        props['theme'] = {**(cfg.get('theme') or {}), **(props.get('theme') or {})}
    if COMPOSITIONS[composition] == 'video':
        card_cfg = cfg.get('end_card') or {}
        card = props.get('endCard', {} if card_cfg.get('enabled') else None)
        if card is True:
            card = {}
        if isinstance(card, dict):
            app = cfg.get('app') or {}
            defaults = {'seconds': card_cfg.get('seconds', 3.0), 'extendSeconds': card_cfg.get('extend_seconds', 1.5),
                        'appName': app.get('name'), 'headline': (cfg.get('cta') or {}).get('text')}
            icon = card_cfg.get('icon')
            if icon and (Path(icon).is_file() or (ROOT/icon).is_file()):
                defaults['icon'] = str(icon)
            if 'badges' not in card:
                defaults['badges'] = store_badges(cfg, scratch)
            card = {**{k: v for k, v in defaults.items() if v}, **card}
        props['endCard'] = card or None
        if props.get('captions'):
            props['captions'].setdefault('language', (cfg.get('whisper') or {}).get('language', 'en'))
    if composition == 'AdVideo':
        edit = cfg.get('edit') or {}
        props.setdefault('transition', {'type': edit.get('transition', 'fade'), 'seconds': edit.get('transition_seconds', 0.35)})
        for clip in props.get('clips', []):
            if 'duration' not in clip:
                total = media.media_duration(resolve(clip['src'], base))
                if not total:
                    raise ValueError('Klip süresi okunamadı: ' + clip['src'])
                clip['duration'] = round(total - clip.get('trimBefore', 0), 3)
    return props


def normalize(path, cfg):
    """-14 LUFS like the FFmpeg pipeline; Remotion itself has no loudness normalisation."""
    if not media.probe(path)['has_audio']:
        return
    tmp = Path(path).with_name(Path(path).stem + '.norm.mp4')
    subprocess.run([media.ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-i', str(path),
                    '-map', '0:v', '-map', '0:a', '-c:v', 'copy',
                    '-af', 'loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000', '-c:a', 'aac',
                    '-b:a', (cfg.get('video') or {}).get('audio_bitrate', '320k'), '-movflags', '+faststart', str(tmp)],
                   check=True)
    tmp.replace(path)


def check_setup():
    if not shutil.which('node'):
        raise RuntimeError('Node.js bulunamadı (Remotion için gerekli).')
    if not (REMOTION/'node_modules'/'@remotion'/'renderer').is_dir():
        raise RuntimeError('Remotion paketleri kurulu değil: cd remotion; npm ci')


def render(composition, props, output, cfg, base=ROOT, quiet=False):
    """Render one composition; returns the output files (one video/PNG, or one PNG per carousel slide)."""
    if composition not in COMPOSITIONS:
        raise ValueError('Bilinmeyen kompozisyon: ' + composition + ' (' + ', '.join(COMPOSITIONS) + ')')
    check_setup()
    kind = COMPOSITIONS[composition]
    output = Path(output).resolve()
    scratch = ROOT/'.tmp'/'remotion'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    public = scratch/'public'
    public.mkdir(parents=True)
    try:
        props = with_defaults(composition, props, cfg, base, scratch/'badges')
        staged = stage(props, public, base)
        v = cfg.get('video') or {}
        job = {'composition': composition, 'props': staged, 'output': str(output), 'publicDir': str(public),
               'crf': v.get('crf', 16), 'x264Preset': v.get('preset', 'slow'),
               'audioBitrate': v.get('audio_bitrate', '320k')}
        if kind == 'still':
            job['frames'] = [0]
        elif kind == 'stills':
            job['frames'] = list(range(len(props.get('slides', []))))
        job_file = scratch/'job.json'
        job_file.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding='utf-8')
        proc = subprocess.Popen(['node', str(REMOTION/'scripts'/'render.mjs'), str(job_file)], cwd=REMOTION,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8', errors='replace')
        outputs, tail = [], []
        for line in proc.stdout:
            tail = (tail + [line.rstrip()])[-40:]
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get('event') == 'progress' and not quiet:
                print(f"  render %{event['percent']}", flush=True)
            elif event.get('event') == 'done':
                outputs = [Path(p) for p in event['outputs']]
        if proc.wait() or not outputs:
            raise RuntimeError('Remotion render başarısız:\n' + '\n'.join(tail))
        if kind == 'video' and (cfg.get('audio') or {}).get('loudnorm', True):
            normalize(output, cfg)
        return outputs
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def render_spec(spec_path, cfg, output=None):
    """CLI entry: a JSON spec {"composition", "props", "output"}; relative paths are read from the spec's folder."""
    spec_path = Path(spec_path).resolve()
    spec = json.loads(spec_path.read_text(encoding='utf-8-sig'))
    target = Path(output or spec.get('output') or (spec_path.stem + ('.mp4' if COMPOSITIONS.get(spec['composition']) == 'video' else '.png')))
    if not target.is_absolute():
        target = Path.cwd()/target
    return render(spec['composition'], spec.get('props', {}), target, cfg, base=spec_path.parent)
