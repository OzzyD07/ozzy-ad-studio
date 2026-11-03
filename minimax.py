"""MiniMax H3 Omni prompt builder and linter.

Prompt order follows what the model weighs most: camera command and main action first, then
setting/light/style, reference tags (<Picture N>, <Audio N>), speech in <d>[Lang] ...</d> tags and
finally the hard rules. Lessons from earlier renders are encoded as lint rules, so a prompt that
would waste a ~20 minute generation is rejected before it is sent.
"""
import re

# Camera commands the model understands inside square brackets (up to three combined).
CAMERA_MOVES = ['Truck left', 'Truck right', 'Pan left', 'Pan right', 'Push in', 'Pull out',
                'Pedestal up', 'Pedestal down', 'Tilt up', 'Tilt down', 'Zoom in', 'Zoom out',
                'Shake', 'Tracking shot', 'Static shot']
LANGUAGES = {'en': 'English', 'tr': 'Turkish', 'de': 'German', 'es': 'Spanish', 'fr': 'French',
             'pt': 'Portuguese', 'it': 'Italian', 'ar': 'Arabic', 'ru': 'Russian'}
DEFAULT_LOOK = {
    'style': ('photorealistic premium commercial cinematography, full-frame cinema camera, 35mm lens, '
              'shallow depth of field, natural colour grade, true-to-life skin tones, fine film grain, '
              'smooth stable motion, sharp focus on the subject'),
    'setting': 'a tidy, warm, modern home interior',
    'lighting': 'soft natural window light with warm practical lamps',
    'voice': 'natural, warm adult narrator, clear accent, conversational pace, no long pauses',
    'music': 'soft original background music under the voice, no lyrics',
    'character': '',
}
REFERENCE_ROLES = {
    'character': 'keep exactly the same face, hair, body and outfit',
    'setting': 'keep the same room layout, furniture and colours',
    'style': 'match its colour grade, lighting and composition style only',
    'product': 'keep the object shape and colours exactly',
}
# <Video N>: the model copies movement, not content (people, places and text come from the prompt).
VIDEO_ROLES = {
    'motion': 'copy its camera movement, framing changes and pacing only, not its people, place or text',
    'action': 'copy the body movement and timing of the action only, performed by our main character',
    'trend': 'copy the format, rhythm and camera choreography of this trend only, not its people, place, music or text',
}
# <Audio N>: the narrator's timbre, or the mood of the background music.
AUDIO_ROLES = {
    'voice': 'the narrator keeps exactly this voice timbre',
    'music': 'the background music follows the mood, tempo and instrumentation of this track, without lyrics',
}
IMAGE_EXT = ('.png', '.jpg', '.jpeg', '.webp')
VIDEO_EXT = ('.mp4', '.mov', '.webm', '.m4v')
AUDIO_EXT = ('.mp3', '.wav', '.m4a', '.aac', '.ogg')
LIMITS = {'Picture': 9, 'Video': 3, 'Audio': 3}
RULES = (
    'Do not add on-screen text, subtitles, logos or CTA; they are added in post. '
    'Keep the lower-middle area of the frame clean for captions.\n'
    'This is a conceptual brand ad: do not present actors as real users or testimonials. '
    'Do not render app screens or user interfaces. '
    'No clinical or therapy claims, guaranteed results, unlimited use, free Premium, user counts or fake reviews.\n'
    'Paper, notebooks and cards stay blank or show only soft abstract pen strokes, never legible words. '
    'Absolutely no text, letters, titles or logos anywhere in any frame. '
    # Listing allowed props works better than forbidding devices: the model defaults to office desks.
    'Props: only the objects described above plus simple home decor (plants, mug, lamp, books); '
    'the background contains no electronic devices. '
    'No laptops, monitors, tablets or TVs anywhere in frame; a phone may appear only with both '
    'its screen and its back hidden. No brand logos on any product. '
    'No alcohol, cigarettes or wine bottles.')
WORDS_PER_SECOND = 2.6
CLAIM_PATTERNS = [r'\bfree\b', r'\bunlimited\b', r'\bguarantee', r'\btherap', r'\bcure', r'\bclinical',
                  r'#1\b', r'\bnumber one\b', r'\bmillions? of users\b', r'\b\d+[kK]?\+? (users|downloads)\b']
DEVICE_WORDS = r'\b(laptop|monitor|tablet|ipad|macbook|tv|television|computer|screen)\b'


def camera(moves):
    moves = moves or ['Static shot']
    if isinstance(moves, str):
        moves = [moves]
    if len(moves) > 3:
        raise ValueError('En fazla 3 kamera hareketi birleştirilebilir.')
    for m in moves:
        if m not in CAMERA_MOVES:
            raise ValueError(f'Bilinmeyen kamera hareketi: {m} (seçenekler: {", ".join(CAMERA_MOVES)})')
    return '[' + ','.join(moves) + ']'


def media_kind(file):
    suffix = '.' + str(file).rsplit('.', 1)[-1].lower()
    return 'Video' if suffix in VIDEO_EXT else 'Audio' if suffix in AUDIO_EXT else 'Picture'


def build_prompt(product, shot, *, index=1, total=1, language='en', references=(), continuity=False,
                 voice_reference=False, videos=(), audios=()):
    """One generation prompt for one shot.

    references: image refs [{'role': ...}] in <Picture N> order; videos: <Video N> refs;
    audios: extra audio refs (music) numbered after the voice reference, which is always <Audio 1>.
    """
    look = {**DEFAULT_LOOK, **(product.get('look') or {})}
    lang = LANGUAGES.get(language, language)
    category = product.get('category', 'mobile app')
    duration = int(shot.get('duration', 15))
    article = 'an' if lang[:1].lower() in 'aeiou' else 'a'
    position = f'shot {index} of {total} of {article} ' if total > 1 else ''
    lines = [f"{duration}-second vertical 9:16 (1080x1920) {position}{lang}-language lifestyle ad for a {category}."
             + (f" Theme: {shot['angle']}." if shot.get('angle') else ''),
             f"{camera(shot.get('camera'))} {shot['visual'].strip()}"]
    character = shot.get('character', look['character'])
    if character:
        lines.append(f'Main character: {character}.')
    lines.append(f"Setting: {shot.get('setting') or look['setting']}. "
                 f"Lighting: {shot.get('lighting') or look['lighting']}. Style: {look['style']}.")
    if shot.get('beats'):
        lines.append('Timeline: ' + ' '.join(f'{b.strip()}' for b in shot['beats']))
    for k, ref in enumerate(references, 1):
        role = ref.get('role', 'style')
        lines.append(f"<Picture {k}> is the {role} reference: {ref.get('note') or REFERENCE_ROLES[role]}.")
    for k, ref in enumerate(videos, 1):
        role = ref.get('role', 'motion')
        lines.append(f"<Video {k}> is the {role} reference: {ref.get('note') or VIDEO_ROLES[role]}.")
    for k, ref in enumerate(audios, 1 + bool(voice_reference)):
        lines.append(f"<Audio {k}>: {ref.get('note') or AUDIO_ROLES[ref.get('role', 'music')]}.")
    if continuity:
        lines.append(f'<Picture {len(references) + 1}> is the last frame of the previous shot: continue seamlessly '
                     'with the same person, outfit, room, props, lighting and colour grade.')
    if index == 1:
        lines.append('Opening hook: the very first frame is already striking and in motion; '
                     "the voiceover's first sentence starts immediately at 0.0 s.")
    else:
        lines.append('Continuation shot: no intro, no establishing pause; start mid-action and keep speaking at once.')
    if index == total:
        lines.append('The final seconds continue the scene calmly; no title card, end card, logo or brand name on screen.')
    # The <d>[Lang]</d> tag makes the model voice the text instead of drawing it in the scene.
    vo = shot.get('voiceover', '').strip()
    if vo:
        if shot.get('speaker') == 'on_camera':
            lines.append('The main character looks into the lens and speaks naturally with accurate lip-sync: '
                         f'<d>[{lang}] {vo}</d>')
        else:
            lines.append(f'Off-screen narrator voiceover (audio only, never written in the scene): <d>[{lang}] {vo}</d>')
        voice = f"Voice: {look['voice']}, in clear {lang}."
        if voice_reference:
            voice += ' The voice keeps exactly the timbre of <Audio 1>.'
        lines.append(voice + f" {look['music'][0].upper() + look['music'][1:]}. Do not cut sentences.")
    lines.append(RULES)
    return '\n'.join(lines)


def outside_speech(prompt):
    return re.sub(r'<d>.*?</d>', ' ', prompt, flags=re.S)


def lint_prompt(prompt, brand=None, images=0, audios=0, videos=0):
    """Return [(level, message)]; level is 'error' or 'warning'."""
    issues = []
    text = outside_speech(prompt)
    if brand and re.search(re.escape(brand), text, re.I):
        issues.append(('error', f'Marka adı "{brand}" <d> etiketi dışında: model sahte logo/bitiş kartı ekler.'))
    if re.search(r'"[^"]{3,}"|“[^”]{3,}”', text):
        issues.append(('warning', 'Tırnak içindeki metin sahnede yazı olarak çizilebilir.'))
    for tag, count, label in [('Picture', images, 'görsel'), ('Video', videos, 'video'), ('Audio', audios, 'ses')]:
        used = {int(n) for n in re.findall(rf'<{tag} (\d+)>', prompt)}
        if used and max(used) > count:
            issues.append(('error', f'<{tag} {max(used)}> kullanılıyor ama yalnızca {count} {label} referansı var.'))
        if count > LIMITS[tag]:
            issues.append(('error', f'{count} {label} referansı var; MiniMax en fazla {LIMITS[tag]} kabul eder.'))
    if prompt.count('<d>') != prompt.count('</d>'):
        issues.append(('error', '<d> etiketleri kapanmamış.'))
    if len(prompt) > 2600:
        issues.append(('warning', f'Prompt {len(prompt)} karakter; uzun promptlarda son kurallar zayıflar.'))
    return issues


def lint_shot(shot, product, label='Çekim'):
    issues = []
    if shot.get('clip'):
        return lint_copy([shot.get('voiceover', '')], label)  # Real footage: nothing is generated.
    duration = shot.get('duration', 15)
    if not isinstance(duration, int) or not 4 <= duration <= 15:
        issues.append(('error', f'{label}: süre 4–15 sn tam sayı olmalı.'))
        duration = 15
    try:
        camera(shot.get('camera'))
    except ValueError as exc:
        issues.append(('error', f'{label}: {exc}'))
    if not str(shot.get('visual', '')).strip():
        issues.append(('error', f'{label}: visual eksik.'))
    words = len(str(shot.get('voiceover', '')).split())
    # Speech must end before the clip does, or the model cuts the last sentence.
    if words > WORDS_PER_SECOND * (duration - .5) + 1:
        issues.append(('error', f'{label}: {words} kelime {duration} sn için fazla '
                                f'(en fazla ~{int(WORDS_PER_SECOND * (duration - .5))}).'))
    if re.search(DEVICE_WORDS, str(shot.get('visual', '')), re.I):
        issues.append(('warning', f'{label}: ekran/cihaz geçiyor; model Apple logolu cihaz çizebilir.'))
    brand = product.get('name')
    for field in ['visual', 'setting', 'character', 'lighting']:
        if brand and re.search(re.escape(brand), str(shot.get(field, '')), re.I):
            issues.append(('error', f'{label}: marka adı {field} alanında; yalnızca seslendirmede olmalı.'))
    return issues


def lint_copy(texts, label='Metin'):
    issues = []
    for text in texts:
        for pattern in CLAIM_PATTERNS:
            for m in re.finditer(pattern, text or '', re.I):
                # Disclaimers ("not a therapist", "no free trial") are fine.
                if re.search(r"\b(not|no|isn't|never)\b(\s+an?)?\s*$", text[max(0, m.start()-12):m.start()], re.I):
                    continue
                issues.append(('error', f'{label}: doğrulanmamış iddia riski ({pattern}) → "{text[:60]}"'))
                break
    return issues


def lint_script(script, product, number=1):
    label = f'Senaryo {number}'
    issues = []
    shots = (script.get('hooks') or []) + (script.get('shots') or [])
    if not shots:
        shots = [{**script, 'duration': script.get('duration', 15)}]
    for k, shot in enumerate(shots, 1):
        issues += lint_shot(shot, product, f'{label} çekim {k}')
    total = sum(s.get('duration', 15) for s in (script.get('shots') or [script])) + \
        (script['hooks'][0].get('duration', 15) if script.get('hooks') else 0)
    if total > 60:
        issues.append(('error', f'{label}: toplam {total} sn; kısa video reklamı için 60 sn üstü.'))
    copy = [script.get('caption', ''), script.get('cta', ''), script.get('hook_text', '')] + \
        [s.get('voiceover', '') for s in shots] + [s.get('hook_text', '') for s in shots]
    issues += lint_copy(copy, label)
    if len(str(script.get('hook_text', ''))) > 40:
        issues.append(('warning', f'{label}: hook_text 40 karakterden uzun; ekranda iki satırı geçer.'))
    return issues
