"""Local, Unicode-safe video finishing. FFmpeg commands never use a shell."""
import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


def ffmpeg():
    from imageio_ffmpeg import get_ffmpeg_exe
    return get_ffmpeg_exe()


def media_duration(path):
    """Duration of any audio or video file (None if FFmpeg cannot read one)."""
    p = subprocess.run([ffmpeg(), '-hide_banner', '-i', str(path)], capture_output=True,
                       encoding='utf-8', errors='replace')
    m = re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)', p.stderr)
    return int(m[1])*3600 + int(m[2])*60 + float(m[3]) if m else None


def probe(path):
    p = subprocess.run([ffmpeg(), '-hide_banner', '-i', str(path)], capture_output=True,
                       encoding='utf-8', errors='replace')
    m = re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)', p.stderr)
    if not m or 'Video:' not in p.stderr:
        raise ValueError('Geçerli, süre bilgisi bulunan bir video gerekli: ' + str(path))
    duration = int(m[1])*3600 + int(m[2])*60 + float(m[3])
    if duration <= 0:
        raise ValueError('Video süresi sıfır.')
    size = re.search(r'Video:.*?(\d{2,5})x(\d{2,5})', p.stderr)
    return {'duration': duration, 'has_audio': 'Audio:' in p.stderr,
            'width': int(size[1]) if size else None, 'height': int(size[2]) if size else None}


def timestamp(t, ass=False):
    unit = 100 if ass else 1000
    value = round(t * unit)
    seconds, fraction = divmod(value, unit)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return (f'{hours}:{minutes:02}:{seconds:02}.{fraction:02}' if ass else
            f'{hours:02}:{minutes:02}:{seconds:02},{fraction:03}')


def read_srt(path):
    text = Path(path).read_text(encoding='utf-8-sig').replace('\r\n', '\n')
    out = []
    for block in re.split(r'\n\s*\n', text.strip()):
        lines = block.splitlines()
        if lines and lines[0].strip().isdigit():
            lines.pop(0)
        if not lines or '-->' not in lines[0]:
            raise ValueError('Geçersiz SRT bloğu: ' + block[:80])
        times = re.findall(r'(\d+):(\d+):(\d+)[,.](\d{3})', lines[0])
        if len(times) != 2:
            raise ValueError('Geçersiz SRT zaman kodu.')
        start, end = [int(h)*3600+int(m)*60+int(s)+int(ms)/1000 for h,m,s,ms in times]
        out.append({'start': start, 'end': end, 'text': ' '.join(lines[1:]).strip()})
    return out


def validate_segments(segments, duration):
    previous = 0.0
    for s in segments:
        if not (math.isfinite(s['start']) and math.isfinite(s['end']) and
                0 <= s['start'] < s['end'] <= duration + .1 and s['start'] >= previous):
            raise ValueError('Altyazı zamanları sıralı ve video süresi içinde olmalı.')
        if not s['text'].strip():
            raise ValueError('Boş altyazı satırı.')
        previous = s['end']


def transcribe(video, cfg, cache):
    from faster_whisper import WhisperModel
    import numpy as np
    import wave
    model = WhisperModel(cfg['model'], device=cfg['device'], compute_type=cfg['compute_type'],
                         download_root=str(cache))
    # Decode with the bundled FFmpeg; PyAV versions differ in metadata_errors support.
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='audio-', dir=cache) as tmp:
        wav = Path(tmp) / 'speech.wav'
        subprocess.run([ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y',
                        '-i', str(video), '-vn', '-ac', '1', '-ar', '16000',
                        '-c:a', 'pcm_s16le', str(wav)], check=True, capture_output=True)
        with wave.open(str(wav), 'rb') as stream:
            samples = np.frombuffer(stream.readframes(stream.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    segments, _ = model.transcribe(samples, language=cfg.get('language'),
                                   word_timestamps=True, vad_filter=True)
    def emit(chunk):
        # Word timings drive the word-by-word highlight in the styled subtitles.
        result.append({'start': chunk[0].start, 'end': chunk[-1].end,
                       'text': ''.join(w.word for w in chunk).strip(),
                       'words': [{'start': w.start, 'end': w.end, 'text': w.word.strip()}
                                 for w in chunk if w.word.strip()]})

    result = []
    for seg in segments:
        words = seg.words or []
        chunk = []
        for word in words:
            if word.end <= word.start:
                continue
            chunk.append(word)
            if len(''.join(w.word for w in chunk)) >= 36 or word.end-chunk[0].start >= 2.5:
                emit(chunk)
                chunk = []
        if chunk:
            emit(chunk)
        if not words and seg.text.strip():
            result.append({'start': seg.start, 'end': seg.end, 'text': seg.text.strip()})
    if not result:
        raise ValueError('Konuşma bulunamadı. SRT sağlayın veya --no-subtitles kullanın.')
    return result


def align_script(segments, script):
    """Keep Whisper's timing but use the known script text, so captions are always spelled right."""
    import difflib
    heard = [w for s in segments for w in (s.get('words') or estimate_words(s))]
    words = script.split()
    if not heard or not words:
        return segments
    norm = lambda t: re.sub(r'\W+', '', t.lower())
    times = [None] * len(words)
    matcher = difflib.SequenceMatcher(None, [norm(w['text']) for w in heard], [norm(w) for w in words],
                                      autojunk=False)
    for op, a0, a1, b0, b1 in matcher.get_opcodes():
        if op == 'equal':
            for k in range(b1 - b0):
                times[b0+k] = (heard[a0+k]['start'], heard[a0+k]['end'])
        elif op == 'replace':
            # Misheard stretch: spread its time over the script words it stands for.
            t0, t1 = heard[a0]['start'], heard[a1-1]['end']
            for k in range(b1 - b0):
                times[b0+k] = (t0 + (t1-t0)*k/(b1-b0), t0 + (t1-t0)*(k+1)/(b1-b0))
    # Script words the model never said ('insert') borrow time from their neighbours.
    for i, t in enumerate(times):
        if t is None:
            prev = times[i-1][1] if i and times[i-1] else heard[0]['start']
            nxt = next((x[0] for x in times[i+1:] if x), heard[-1]['end'])
            times[i] = (prev, max(prev + .01, min(nxt, prev + .3)))
    out, current = [], []
    for w, (start, end) in zip(words, times):
        start = max(start, current[-1]['end'] if current else (out[-1]['end'] if out else 0))
        current.append({'start': start, 'end': max(end, start + .01), 'text': w})
        if w[-1] in '.!?' or len(current) >= 12:
            out.append({'start': current[0]['start'], 'end': current[-1]['end'],
                        'text': ' '.join(x['text'] for x in current), 'words': current})
            current = []
    if current:
        out.append({'start': current[0]['start'], 'end': current[-1]['end'],
                    'text': ' '.join(x['text'] for x in current), 'words': current})
    return out


def escape_ass(text):
    # Do not allow input text to become ASS override tags or line-break commands.
    return text.replace('\\', '／').replace('{', '｛').replace('}', '｝').replace('\n', ' ')




# ASS colours are &HAABBGGRR. "classic" is the original plain look.
SUBTITLE_STYLES = {
    'pop': {'font': 'Arial Black', 'size': 92, 'outline': 7, 'shadow': 4,
            'highlight': '&H0000E5FF', 'outline_colour': '&H00000000', 'back': '&H96000000'},
    'neon': {'font': 'Arial Black', 'size': 92, 'outline': 6, 'shadow': 0,
             'highlight': '&H0014FF39', 'outline_colour': '&H00200A00', 'back': '&H00000000',
             'glow': '&H0014FF39'},
    'tiktok': {'font': 'Arial Black', 'size': 92, 'outline': 7, 'shadow': 4,
               'highlight': '&H00552CFE', 'outline_colour': '&H00000000', 'back': '&H96000000'},
    # Two big words at a time, active word green and clearly larger (high-retention UGC look).
    'hormozi': {'font': 'Arial Black', 'size': 104, 'outline': 8, 'shadow': 3, 'max_words': 2,
                'active_scale': 125, 'highlight': '&H0041F25B', 'outline_colour': '&H00000000',
                'back': '&H96000000'},
    # Each group sits on a dark box: readable on any background.
    'box': {'font': 'Arial Black', 'size': 80, 'outline': 18, 'shadow': 0, 'border_style': 3,
            'highlight': '&H0000E5FF', 'outline_colour': '&H26000000', 'back': '&H00000000'},
    'classic': {'font': 'Arial', 'size': 60, 'outline': 3, 'shadow': 1,
                'outline_colour': '&H00101010', 'back': '&H80000000'},
}
WHITE = '&H00FFFFFF'
ACCENT = '&H00552CFE'
STORE_LABELS = {'app_store': ('Download on the', 'App Store'), 'google_play': ('GET IT ON', 'Google Play')}
# Both store badges share one height (Apple's rule: equal size, neither store favoured) after the
# transparent clear-space is trimmed; Google's PNG ships with wide padding, Apple's with none.
BADGE_Y, BADGE_H, BADGE_W, BADGE_GAP, BADGE_MAX_ROW = 1100, 118, 340, 28, 920


def upper_tr(text):
    # str.upper() maps i→I; Turkish needs i→İ and ı→I.
    return text.replace('i', 'İ').replace('ı', 'I').upper()


def upper_word(word, language='tr'):
    if language != 'tr':
        return word.upper()
    # Brand names with inner capitals (MentorAi'yi) keep Latin I; the Turkish suffix does not.
    stem, sep, suffix = (re.split(r"(['’])", word, maxsplit=1) + ['', ''])[:3]
    if re.search(r'[a-zçğıöşü][A-ZÇĞİÖŞÜ]', stem):
        return stem.upper() + sep + upper_tr(suffix)
    return upper_tr(word)


def estimate_words(segment):
    # SRT has no word timings: spread the line's time over words by length.
    words = segment['text'].split()
    total = sum(len(w) + 1 for w in words)
    span, t, out = segment['end'] - segment['start'], segment['start'], []
    for w in words:
        end = t + span * (len(w) + 1) / total
        out.append({'start': t, 'end': end, 'text': w})
        t = end
    return out


def word_groups(segments, max_words=3, max_chars=16):
    """Split speech into short punchy groups of 1–3 words, like Reels/TikTok captions."""
    groups = []
    for s in segments:
        words = s.get('words') or estimate_words(s)
        current = []
        for w in words:
            text = w['text'].strip()
            if not text:
                continue
            if current and (len(current) >= max_words or
                            len(' '.join(x['text'] for x in current + [w])) > max_chars or
                            w['start'] - current[-1]['end'] > .6):
                groups.append(current)
                current = []
            current.append({**w, 'text': text})
            if text[-1] in '.!?,;:':
                groups.append(current)
                current = []
        if current:
            groups.append(current)
    return groups


def clean_word(text, language='tr'):
    # Trailing commas/periods look noisy at this size; keep ! and ? for tone.
    return upper_word(escape_ass(text.rstrip('.,;:…')) or escape_ass(text), language)


def norm(text):
    return re.sub(r'\W+', '', text.lower())


def styled_events(segments, style, language='tr', emphasis=()):
    st = SUBTITLE_STYLES[style]
    groups = word_groups(segments, st.get('max_words', 3))
    # Brand names, numbers and chosen keywords keep the accent colour even when not spoken.
    keys = {norm(w) for phrase in emphasis for w in phrase.split()} - {''}
    scale = st.get('active_scale', 116)
    events = []
    for gi, group in enumerate(groups):
        next_start = groups[gi+1][0]['start'] if gi + 1 < len(groups) else math.inf
        # Hold each group until the next one starts (short gaps) so captions don't flicker.
        gap = next_start - group[-1]['end']
        group_end = next_start if gap < .8 else group[-1]['end'] + .35
        words = [clean_word(w['text'], language) for w in group]
        marked = [norm(w['text']) in keys or bool(re.search(r'\d', w['text'])) for w in group]
        for wi, w in enumerate(group):
            start = group[0]['start'] if wi == 0 else w['start']
            end = group[wi+1]['start'] if wi + 1 < len(group) else group_end
            if end <= start:
                continue
            parts = []
            for k, text in enumerate(words):
                if k == wi:
                    # Active word: brand colour plus a small bounce.
                    parts.append(f"{{\\c{st['highlight']}\\fscx100\\fscy100"
                                 f"\\t(0,80,\\fscx{scale}\\fscy{scale})\\t(80,160,\\fscx{scale-6}\\fscy{scale-6})}}"
                                 f"{text}{{\\c{WHITE}\\fscx100\\fscy100}}")
                elif marked[k]:
                    parts.append(f"{{\\c{st['highlight']}\\fscx106\\fscy106}}{text}{{\\c{WHITE}\\fscx100\\fscy100}}")
                else:
                    parts.append(text)
            # The whole group pops in when it first appears.
            intro = ('{\\fad(60,0)\\fscx70\\fscy70\\t(0,90,\\fscx106\\fscy106)'
                     '\\t(90,170,\\fscx100\\fscy100)}') if wi == 0 else ''
            line = intro + ' '.join(parts)
            t0, t1 = timestamp(start, True), timestamp(end, True)
            if 'glow' in st:
                # Blurred outline-only copy underneath gives the neon glow.
                events.append(f"Dialogue: 0,{t0},{t1},Glow,,0,0,0,,{{\\blur14\\1a&HFF&}}{line}")
            events.append(f"Dialogue: 1,{t0},{t1},Sub,,0,0,0,,{line}")
    return events


def rounded_rect(w, h, r):
    return (f'm {r} 0 l {w-r} 0 b {w} 0 {w} 0 {w} {r} l {w} {h-r} b {w} {h} {w} {h} {w-r} {h} '
            f'l {r} {h} b 0 {h} 0 {h} 0 {h-r} l 0 {r} b 0 0 0 0 {r} 0')


def badge_slots(stores, widths=None):
    """Left x of each badge; the row (real widths, one gap) is centred on the frame."""
    widths = widths or {}
    row = sum(widths.get(s, BADGE_W) for s in stores) + BADGE_GAP * (len(stores) - 1)
    x, slots = 540 - row // 2, {}
    for store in stores:
        slots[store] = x
        x += widths.get(store, BADGE_W) + BADGE_GAP
    return slots


def opaque_box(png):
    """Bounding box (w, h, x, y) of the non-transparent pixels, via alpha → cropdetect."""
    run = subprocess.run([ffmpeg(), '-hide_banner', '-i', str(png), '-vf',
                          'format=rgba,alphaextract,cropdetect=limit=0.02:round=2:skip=0:reset=0',
                          '-frames:v', '1', '-f', 'null', '-'], capture_output=True, text=True)
    found = re.findall(r'crop=(\d+):(\d+):(\d+):(\d+)', run.stderr)
    return tuple(map(int, found[-1])) if found else None


def end_card_events(card, language):
    """App name, CTA pill and (when official PNGs are missing) drawn store badges."""
    t0, t1 = card['start'], card['end']
    ts = lambda t: timestamp(t, True)
    events = []
    name_y = 880 if card.get('has_icon') else 760
    logo_only = card.get('brand_style') == 'logo_only' and card.get('has_icon')
    if card.get('app_name') and not logo_only:
        events.append(f"Dialogue: 3,{ts(t0+.3)},{ts(t1)},Card,,0,0,0,,{{\\an5\\fad(250,0)"
                      f"\\move(540,{name_y+40},540,{name_y},0,350)}}{escape_ass(card['app_name'])}")
    if card.get('headline') and not logo_only:
        pulse = ''.join(f'\\t({t},{t+450},\\fscx105\\fscy105)\\t({t+450},{t+900},\\fscx100\\fscy100)'
                        for t in range(700, int((t1-t0-.45)*1000) - 900, 900))
        events.append(f"Dialogue: 3,{ts(t0+.45)},{ts(t1)},Pill,,0,0,0,,{{\\an5\\pos(540,1005)\\fad(150,0)"
                      f"\\fscx60\\fscy60\\t(0,180,\\fscx108\\fscy108)\\t(180,280,\\fscx100\\fscy100){pulse}}}"
                      f"{upper_word(escape_ass(card['headline']), language)}")
    slots = card.get('badge_x') or badge_slots(card.get('stores', []))
    for k, store in enumerate(card.get('drawn', [])):
        x, start = slots[store], t0 + .55 + .15 * k
        small, big = STORE_LABELS[store]
        move = lambda dx, dy: f'\\move({x+dx},{BADGE_Y+dy+50},{x+dx},{BADGE_Y+dy},0,350)'
        events.append(f"Dialogue: 3,{ts(start)},{ts(t1)},Badge,,0,0,0,,{{\\an7{move(0,0)}\\fad(250,0)"
                      f"\\p1\\bord2\\3c&HA6A6A6&\\1c&H000000&\\shad0}}{rounded_rect(BADGE_W, BADGE_H, 22)}{{\\p0}}")
        events.append(f"Dialogue: 4,{ts(start)},{ts(t1)},Badge,,0,0,0,,{{\\an7{move(34,18)}\\fad(250,0)\\fs28}}{small}")
        events.append(f"Dialogue: 4,{ts(start)},{ts(t1)},Badge,,0,0,0,,{{\\an7{move(32,46)}\\fad(250,0)\\fs54}}{big}")
    return events


def make_ass(segments, duration, cta, seconds, style='pop', language='tr', *, hook_text=None,
             emphasis=(), end_card=None, font=None, margin_v=640):
    if style not in SUBTITLE_STYLES:
        raise ValueError('Bilinmeyen altyazı stili: ' + str(style) + ' (seçenekler: ' +
                         ', '.join(SUBTITLE_STYLES) + ')')
    st = {**SUBTITLE_STYLES[style], **({'font': font} if font else {})}
    bold = 0 if st['font'] == 'Arial Black' else -1  # Arial Black is already heavy.
    glow = st.get('glow', st['outline_colour'])
    header = f'''[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{st['font']},{st['size']},{WHITE},{WHITE},{st['outline_colour']},{st['back']},{bold},0,0,0,100,100,0,0,{st.get('border_style', 1)},{st['outline']},{st['shadow']},2,90,90,{margin_v},1
Style: Glow,{st['font']},{st['size']},{glow},{glow},{glow},&H00000000,{bold},0,0,0,100,100,0,0,1,{st['outline']+10},0,2,90,90,{margin_v},1
Style: CTA,Arial Black,58,&H00FFFFFF,&H00FFFFFF,{ACCENT},&H64000000,0,0,0,0,100,100,0,0,3,26,0,2,130,160,420,1
Style: Hook,Arial Black,64,&H00111111,&H00111111,&H00FFFFFF,&H00000000,0,0,0,0,100,100,0,0,3,22,0,8,110,110,0,1
Style: Card,Arial Black,84,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,4,3,5,60,60,0,1
Style: Pill,Arial Black,56,&H00FFFFFF,&H00FFFFFF,{ACCENT},&H00000000,0,0,0,0,100,100,0,0,3,24,0,5,130,130,0,1
Style: Badge,Arial,54,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    if style == 'classic':
        events = [f"Dialogue: 0,{timestamp(s['start'], True)},{timestamp(s['end'], True)},Sub,,0,0,0,,{escape_ass(s['text'])}" for s in segments]
    else:
        if cta:
            segments = drop_spoken_cta(segments, cta, duration - seconds)
        events = styled_events(segments, style, language, emphasis)
    if hook_text:
        # Native-looking text hook at the top for the first seconds (sound-off viewers).
        end = min(2.8, duration)
        events.append(f"Dialogue: 2,{timestamp(.05, True)},{timestamp(end, True)},Hook,,0,0,0,,"
                      f"{{\\an8\\pos(540,300)\\fad(60,180)\\fscx70\\fscy70\\t(0,120,\\fscx104\\fscy104)"
                      f"\\t(120,200,\\fscx100\\fscy100)}}{escape_ass(hook_text)}")
    if cta:
        if len(cta) > 45:
            raise ValueError('CTA en fazla 45 karakter olmalı.')
        # Pop in, then pulse gently to draw the eye.
        pulse = ''.join(f'\\t({t},{t+400},\\fscx106\\fscy106)\\t({t+400},{t+800},\\fscx100\\fscy100)'
                        for t in range(300, int(seconds*1000) - 800, 800))
        anim = f'{{\\fad(120,0)\\fscx60\\fscy60\\t(0,180,\\fscx108\\fscy108)\\t(180,280,\\fscx100\\fscy100){pulse}}}'
        events.append(f'Dialogue: 2,{timestamp(max(0, duration-seconds), True)},{timestamp(duration, True)},CTA,,0,0,0,,{anim}{upper_word(escape_ass(cta), language)}')
    if end_card:
        events += end_card_events(end_card, language)
    return header + '\n'.join(events) + '\n'


def drop_spoken_cta(segments, cta, after):
    # A spoken CTA would repeat the CTA box/end card underneath it; let the card carry it.
    return [s for s in segments if not (cta and norm(s['text']) == norm(cta) and s['end'] > after)]


def clip_segments(segments, t):
    """Captions stop where the end card starts."""
    out = []
    for s in segments:
        words = [{**w, 'end': min(w['end'], t)} for w in (s.get('words') or estimate_words(s))
                 if w['start'] < t - .05]
        if words:
            out.append({'start': words[0]['start'], 'end': words[-1]['end'],
                        'text': ' '.join(w['text'] for w in words), 'words': words})
    return out


def asset_path(value):
    path = Path(value)
    return path if path.is_absolute() else Path(__file__).resolve().parent / path


def fit_graph(src, out, w, h, info, mode='auto'):
    """Fill the frame when the aspect ratio is close (no bars); otherwise centre on a blurred copy."""
    fill = f'scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h}'
    ratio = info['width'] / info['height'] if info.get('width') and info.get('height') else w / h
    if mode == 'fill' or (mode == 'auto' and abs(ratio / (w / h) - 1) < .07):
        return f'[{src}]{fill}[{out}]'
    if mode == 'pad':
        return (f'[{src}]scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,'
                f'pad={w}:{h}:(ow-iw)/2:(oh-ih)/2[{out}]')
    # Blur at quarter size: same look, a fraction of the cost.
    return (f'[{src}]split[{out}b][{out}f];'
            f'[{out}b]scale={w//4}:{h//4}:force_original_aspect_ratio=increase,crop={w//4}:{h//4},'
            f'gblur=sigma=10,eq=brightness=-0.08,scale={w}:{h}[{out}bg];'
            f'[{out}f]scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos[{out}fg];'
            f'[{out}bg][{out}fg]overlay=(W-w)/2:(H-h)/2[{out}]')


def probe_image(path):
    p = subprocess.run([ffmpeg(), '-hide_banner', '-i', str(path)], capture_output=True,
                       encoding='utf-8', errors='replace')
    size = re.search(r'Video:.*?(\d{2,5})x(\d{2,5})', p.stderr)
    return int(size[1]), int(size[2])


def contact_sheet(video, target, cols=4, rows=3, width=240):
    """Evenly spaced frames on one image, to spot logos, text or devices without scrubbing."""
    info = probe(video)
    rate = cols * rows / max(info['duration'], .1)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-i', str(video), '-vf',
                    f'fps={rate:.5f},scale={width}:-2,tile={cols}x{rows}:padding=6:color=white',
                    '-frames:v', '1', str(target)], check=True, capture_output=True)
    return target


def still(source, target, filters):
    subprocess.run([ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-i', str(source),
                    '-vf', filters, '-frames:v', '1', str(target)], check=True, capture_output=True)


ROUND_ICON = ('scale=280:280:flags=lanczos,format=rgba,geq=r=r(X\\,Y):g=g(X\\,Y):b=b(X\\,Y):'
              'a=if(gt(abs(X-W/2)\\,W/2-62)*gt(abs(Y-H/2)\\,H/2-62)\\,'
              'if(lte(hypot(abs(X-W/2)-(W/2-62)\\,abs(Y-H/2)-(H/2-62))\\,62)\\,alpha(X\\,Y)\\,0)\\,alpha(X\\,Y))')


def end_card_assets(card, card_cfg, stage):
    """Copy the icon/official badges into the stage; returns overlays [(file, x, y, t0)]."""
    overlays = []
    icon = card_cfg.get('icon') and asset_path(card_cfg['icon'])
    if icon and icon.is_file():
        still(icon, stage/'icon.png', ROUND_ICON)  # Rounded corners, like the store listing.
        card['brand_style'] = card_cfg.get('brand_style', 'standard')
        icon_y = 740 if card['brand_style'] == 'logo_only' else 520
        overlays.append(('icon.png', '(W-w)/2', icon_y, card['start'] + .15))
        card['has_icon'] = True
    stores = list(card_cfg.get('stores', ['app_store', 'google_play']))
    card['stores'], card['drawn'] = stores, []
    height = int(card_cfg.get('badge_height', BADGE_H))
    sources, widths = {}, {}
    for store in stores:
        png = asset_path(card_cfg.get('badges_dir', 'assets/badges')) / (store.replace('_', '-') + '.png')
        if not png.is_file():
            card['drawn'].append(store)  # Fallback: badge drawn in the ASS layer.
            continue
        box = opaque_box(png)
        crop = f'crop={box[0]}:{box[1]}:{box[2]}:{box[3]},' if box and box[0] > 8 and box[1] > 8 else ''
        sources[store] = (png, crop)
        size = box[:2] if crop else probe_image(png)
        widths[store] = round(size[0] * height / size[1])
    # Shrink the whole row evenly if it would leave the safe area; badges stay the same height.
    row = sum(widths.get(s, BADGE_W) for s in stores) + BADGE_GAP * (len(stores) - 1)
    if row > BADGE_MAX_ROW:
        height = int(height * BADGE_MAX_ROW / row)
        widths = {k: round(v * BADGE_MAX_ROW / row) for k, v in widths.items()}
    card['badge_x'] = slots = badge_slots(stores, widths)
    for k, store in enumerate(stores):
        if store not in sources:
            continue
        png, crop = sources[store]
        still(png, stage/f'{store}.png', f'format=rgba,{crop}scale={widths[store]}:{height}:flags=lanczos')
        overlays.append((f'{store}.png', str(slots[store]), BADGE_Y, card['start'] + .55 + .15 * k))
    return overlays


def finish(video, output, cfg, srt=None, no_subtitles=False, cta=None, language=None, script=None, *,
           hook_text=None, emphasis=(), app_name=None, music=None):
    # A job's own language (e.g. English ads) overrides the default Whisper language.
    language = language or cfg['whisper'].get('language') or 'tr'
    video = Path(video).resolve()
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Çıktı klasörü zaten var; farklı bir çıktı adı seçin: ' + str(output))
    info = probe(video)
    if srt:
        segments = read_srt(srt)
    elif no_subtitles:
        segments = []
    elif not info['has_audio']:
        raise ValueError('Videoda ses yok. SRT sağlayın veya --no-subtitles kullanın.')
    else:
        segments = transcribe(video, {**cfg['whisper'], 'language': language},
                              Path(cfg['workspace']) / 'models')
        if script:
            segments = align_script(segments, script)
    validate_segments(segments, info['duration'])
    sub_cfg = cfg.get('subtitles') or {}
    card_cfg = cfg.get('end_card') or {}
    cta_seconds = float(cfg['cta']['seconds'])
    card, extend, total = None, 0.0, info['duration']
    captions = segments
    if card_cfg.get('enabled') and (cta or app_name):
        extend = float(card_cfg.get('extend_seconds', 1.5))
        total += extend
        spoken = drop_spoken_cta(segments, cta, info['duration'] - cta_seconds)
        speech_end = spoken[-1]['end'] if spoken else 0
        # Start once speech ends, but always leave the card on screen long enough to read.
        start = max(0, min(max(speech_end + .15, total - float(card_cfg.get('seconds', 3))), total - 2.0))
        card = {'start': start, 'end': total, 'app_name': app_name, 'headline': cta}
        captions = clip_segments(spoken, start)
    output.parent.mkdir(parents=True, exist_ok=True)
    v = cfg['video']
    w, h, fps = int(v['width']), int(v['height']), v['fps']
    if w < 2 or h < 2 or w % 2 or h % 2:
        raise ValueError('Video boyutları pozitif çift sayılar olmalı.')
    with tempfile.TemporaryDirectory(prefix='render-', dir=output.parent) as tmp:
        stage = Path(tmp)
        overlays = end_card_assets(card, card_cfg, stage) if card else []
        ass = make_ass(captions, total, None if card else cta, cta_seconds,
                       sub_cfg.get('style', 'pop'), language, hook_text=hook_text,
                       emphasis=[*emphasis, *([app_name] if app_name else [])], end_card=card,
                       font=sub_cfg.get('font'), margin_v=int(sub_cfg.get('margin_v', 640)))
        (stage/'subtitles.ass').write_text(ass, encoding='utf-8')
        (stage/'subtitles.srt').write_text('\n\n'.join(
            f"{i}\n{timestamp(s['start'])} --> {timestamp(s['end'])}\n{s['text']}"
            for i,s in enumerate(segments, 1)) + '\n', encoding='utf-8')
        fonts = asset_path(sub_cfg.get('fonts_dir', 'assets/fonts'))
        fontsdir = ''
        if fonts.is_dir() and any(f.suffix.lower() in ('.ttf', '.otf') for f in fonts.iterdir()):
            shutil.copytree(fonts, stage/'fonts')
            fontsdir = ':fontsdir=fonts'
        sharpen = ',unsharp=5:5:0.45:5:5:0' if v.get('sharpen', True) else ''
        chains = [fit_graph('0:v', 'fit', w, h, info, v.get('fit', 'auto')),
                  f'[fit]fps={fps},setsar=1{sharpen}' +
                  (f',tpad=stop_mode=clone:stop_duration={extend:.3f}' if extend else '') + '[base]']
        inputs, current = [], 'base'
        if card:
            s0 = card['start']
            # The live footage fades into a blurred, darkened backdrop behind the end card.
            chains += ['[base]split[main][forblur]',
                       f'[forblur]trim=start={s0:.3f},setpts=PTS-STARTPTS,gblur=sigma=22,'
                       'eq=brightness=-0.18:saturation=0.85,format=yuva420p,fade=t=in:st=0:d=0.45:alpha=1,'
                       f'setpts=PTS+{s0:.3f}/TB[blur]',
                       '[main][blur]overlay=0:0:eof_action=pass[card]']
            current = 'card'
            for k, (name, x, y, t0) in enumerate(overlays):
                inputs += ['-loop', '1', '-framerate', str(fps), '-t', f'{total:.3f}', '-i', name]
                chains += [f'[{k+1}:v]format=rgba,fade=t=in:st={t0:.3f}:d=0.35:alpha=1[img{k}]',
                           f"[{current}][img{k}]overlay=x='{x}':y='{y}+60*max(0,1-(t-{t0:.3f})/0.35)'"
                           f':shortest=1:eval=frame[ov{k}]']
                current = f'ov{k}'
        chains.append(f'[{current}]ass=subtitles.ass{fontsdir},format=yuv420p[vout]')
        extra, chains_a = audio_graph(info, cfg, total, extend, 1 + len(overlays), music)
        if chains_a:
            chains += chains_a
            inputs += extra
        command = ([ffmpeg(), '-hide_banner', '-y', '-i', str(video)] + inputs +
                   ['-filter_complex', ';'.join(chains), '-map', '[vout]'] +
                   (['-map', '[aout]'] if chains_a else []) +
                   ['-c:v', 'libx264', '-preset', v.get('preset', 'fast'), '-crf', str(v['crf']),
                    '-profile:v', 'high', '-pix_fmt', 'yuv420p', '-r', str(fps), '-t', f'{total:.3f}',
                    '-c:a', 'aac', '-b:a', v.get('audio_bitrate', '192k'), '-ar', '48000',
                    '-movflags', '+faststart', 'video.mp4'])
        p = subprocess.run(command, cwd=stage, capture_output=True, encoding='utf-8', errors='replace')
        (stage/'render.log').write_text(' '.join(command) + '\n\n' + p.stderr, encoding='utf-8')
        if p.returncode:
            log = output.parent / (output.name + '.error.log')
            shutil.copy2(stage/'render.log', log)
            raise RuntimeError('FFmpeg başarısız. Log: ' + str(log))
        rendered = probe(stage/'video.mp4')
        if abs(rendered['duration'] - total) > .5:
            raise RuntimeError('Çıktı süresi beklenenle uyuşmuyor.')
        for name, *_ in overlays:
            (stage/name).unlink(missing_ok=True)
        shutil.rmtree(stage/'fonts', ignore_errors=True)
        music_path = music or (cfg.get('music') or {}).get('file')
        (stage/'metadata.json').write_text(json.dumps({
            'source': str(video), 'duration': rendered['duration'], 'cta': cta, 'app_name': app_name,
            'hook_text': hook_text, 'subtitle_count': len(segments), 'language': language,
            'subtitle_style': sub_cfg.get('style', 'pop'), 'width': w, 'height': h,
            'end_card': card and {k: card.get(k) for k in ['start', 'end', 'stores', 'drawn', 'has_icon', 'brand_style']},
            'music': str(music_path) if music_path else None, 'review_required': True},
            ensure_ascii=False, indent=2), encoding='utf-8')
        # Same-parent rename exposes only a fully rendered export to consumers.
        stage.rename(output)
    return output


def audio_graph(info, cfg, total, extend, index, music=None):
    """Voice (+ optional ducked music bed), faded and normalised to -14 LUFS for social feeds.
    Returns (extra ffmpeg inputs, filter chains ending in [aout])."""
    music = music or (cfg.get('music') or {}).get('file')
    loud = ',loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000' if (cfg.get('audio') or {}).get('loudnorm', True) else ''
    voice = None
    if info['has_audio']:
        # With an end card the clip's own audio fades at its end and silence covers the extension.
        fade = (f'afade=t=out:st={max(0, info["duration"]-.5):.3f}:d=0.5,apad=pad_dur={extend:.3f},'
                if extend else f'afade=t=out:st={max(0, total-.4):.3f}:d=0.4,')
        voice = f'[0:a]aresample=48000,aformat=channel_layouts=stereo,{fade}atrim=0:{total:.3f}'
    if not music:
        return [], ([voice + loud + '[aout]'] if voice else [])
    vol = float((cfg.get('music') or {}).get('volume', .22))
    bed = (f'[{index}:a]aresample=48000,aformat=channel_layouts=stereo,volume={vol},atrim=0:{total:.3f},'
           f'afade=t=in:d=0.6,afade=t=out:st={max(0, total-1.2):.3f}:d=1.2')
    inputs = ['-stream_loop', '-1', '-i', str(asset_path(music))]
    if not voice:
        return inputs, [bed + loud + '[aout]']
    # The music ducks under the voice (sidechain), so narration stays clear.
    return inputs, [voice + ',asplit[voice][key]', bed + '[bed]',
                    '[bed][key]sidechaincompress=threshold=0.04:ratio=10:attack=15:release=350[duck]',
                    f'[voice][duck]amix=inputs=2:duration=first:normalize=0{loud}[aout]']


TRANSITIONS = ['cut', 'fade', 'fadeblack', 'fadewhite', 'dissolve', 'slideleft', 'slideright', 'slideup',
               'slidedown', 'smoothleft', 'smoothright', 'smoothup', 'smoothdown', 'circleopen',
               'circleclose', 'zoomin', 'wipeleft', 'wiperight', 'radial', 'hblur', 'pixelize']


def assemble(clips, target, cfg):
    """Join clips with xfade/acrossfade into one near-lossless master. clips: [{path, start, end,
    transition, transition_seconds}]; a clip's transition is the one leading into it."""
    if not clips:
        raise ValueError('Montaj için en az bir klip gerekli.')
    v, edit = cfg['video'], cfg.get('edit') or {}
    w, h, fps = int(v['width']), int(v['height']), v['fps']
    inputs, chains, durations = [], [], []
    for i, c in enumerate(clips):
        info = probe(c['path'])
        start = float(c.get('start') or 0)
        end = min(float(c.get('end') or info['duration']), info['duration'])
        if end - start < .5:
            raise ValueError(f'Klip {i+1} kırpma aralığı çok kısa.')
        inputs += ['-i', str(c['path'])]
        chains += [f'[{i}:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[t{i}]',
                   fit_graph(f't{i}', f'f{i}', w, h, info, v.get('fit', 'auto')),
                   f'[f{i}]fps={fps},format=yuv420p,setsar=1[v{i}]']
        if info['has_audio']:
            chains.append(f'[{i}:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS,aresample=48000,'
                          f'aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}]')
        else:
            chains.append(f'anullsrc=r=48000:cl=stereo,atrim=0:{end-start:.3f},aformat=sample_fmts=fltp[a{i}]')
        durations.append(end - start)
    vcur, acur, total = 'v0', 'a0', durations[0]
    for i in range(1, len(clips)):
        kind = clips[i].get('transition') or edit.get('transition', 'fade')
        if kind not in TRANSITIONS:
            raise ValueError(f'Bilinmeyen geçiş: {kind} (seçenekler: {", ".join(TRANSITIONS)})')
        if kind == 'cut':
            # A true cut is a concat. A one-frame xfade looked equivalent, but FFmpeg 7 then drops
            # every following video frame while the audio keeps playing.
            # fps= restores the 1/fps time base that a following xfade requires.
            chains.append(f'[{vcur}][{acur}][v{i}][a{i}]concat=n=2:v=1:a=1[c{i}][y{i}];[c{i}]fps={fps}[x{i}]')
            vcur, acur, total = f'x{i}', f'y{i}', total + durations[i]
            continue
        d = float(clips[i].get('transition_seconds') or edit.get('transition_seconds', .35))
        if d >= min(durations[i], total) / 2:
            raise ValueError(f'Geçiş {i}: süre kliplere göre çok uzun.')
        chains += [f'[{vcur}][v{i}]xfade=transition={kind}:duration={d:.3f}:offset={total-d:.3f}[x{i}]',
                   f'[{acur}][a{i}]acrossfade=d={d:.3f}:c1=tri:c2=tri[y{i}]']
        vcur, acur, total = f'x{i}', f'y{i}', total + durations[i] - d
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix('.part.mp4')
    command = ([ffmpeg(), '-hide_banner', '-y'] + inputs + ['-filter_complex', ';'.join(chains),
               '-map', f'[{vcur}]', '-map', f'[{acur}]', '-c:v', 'libx264', '-preset', 'medium', '-crf', '12',
               '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '320k', '-ar', '48000', str(tmp)])
    p = subprocess.run(command, capture_output=True, encoding='utf-8', errors='replace')
    if p.returncode:
        log = target.with_suffix('.error.log')
        log.write_text(' '.join(command) + '\n\n' + p.stderr, encoding='utf-8')
        tmp.unlink(missing_ok=True)
        raise RuntimeError('Montaj başarısız. Log: ' + str(log))
    tmp.replace(target)
    return {'path': str(target), 'duration': total}
