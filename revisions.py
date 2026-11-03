"""Revision waves without hand-made copies: retry a clip, split it into two parts, keep the old one.

A revision is a new job `<id>-rN` next to the original (which stays untouched for comparison).
When a shot is replaced, every montage using it gets its own `-rN` copy with the new shot list,
so the original montage still renders the old version. `chain` also re-plans the shots that
continue from the replaced one, because their continuity frame would otherwise come from the
old clip.
"""
import re
from datetime import datetime
from pathlib import Path

import minimax

RESULT_KEYS = ['raw_video', 'export', 'mcp_result', 'artifact_url', 'error', 'caption_file',
               'assembled_duration', 'submitted_at', 'remote_status']
CONTINUATION = 'Continuation shot: no intro, no establishing pause; start mid-action and keep speaking at once.'


def read(path):
    import json
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, data):
    import pipeline
    pipeline.write(path, data)


def known(ws):
    """id → (path, job) over the queue and earlier revision waves."""
    found = {}
    for f in [*sorted((ws/'revisions').glob('*/jobs/*.json')), *sorted((ws/'jobs').glob('*.json'))]:
        job = read(f)
        found[job['id']] = (f, job)
    return found


def next_id(ws, identity):
    taken = set(known(ws))
    n = 2
    while any(t == f'{identity}-r{n}' or t.startswith(f'{identity}-r{n}-') for t in taken):
        n += 1
    return f'{identity}-r{n}'


def fresh(job, new_id, note=None):
    copy = {k: v for k, v in job.items() if k not in RESULT_KEYS}
    copy.update(id=new_id, status='planned', remote_id=None, revision_of=job['id'],
                created=datetime.now().isoformat(timespec='seconds'))
    if note:
        copy['revision_note'] = note
    if 'selected_for_publication' in copy:
        copy['selected_for_publication'] = False
    return copy


def with_extra(prompt, extra):
    """Add one instruction right before the hard rules, where the model still weighs it."""
    if not extra:
        return prompt
    head, sep, tail = prompt.rpartition(minimax.RULES)
    return f'{head}{extra.strip()}\n{sep}{tail}' if sep else f'{prompt}\n{extra.strip()}'


def lint(job, brand):
    images = len(job.get('references') or []) + bool(job.get('continuity_from'))
    audios = len(job.get('audio_references') or []) + bool(job.get('voice_from_previous'))
    issues = minimax.lint_prompt(job['prompt'], brand, images, audios, len(job.get('video_references') or []))
    words = len(re.sub(r'\[[^\]]*\]', '', ' '.join(re.findall(r'<d>(.*?)</d>', job['prompt'], re.S))).split())
    limit = minimax.WORDS_PER_SECOND * (job['duration_seconds'] - .5) + 1
    if words > limit:
        issues.append(('error', f"{words} kelime {job['duration_seconds']} sn için fazla (en fazla ~{int(limit - 1)})."))
    errors = [m for level, m in issues if level == 'error']
    if errors:
        raise ValueError(f"{job['id']}: " + '; '.join(errors))
    return [m for level, m in issues if level == 'warning']


def swap_into_montages(ws, replaced, note, jobs):
    """New `-rN` montage for every montage that uses a replaced shot. replaced: old id → [new ids]."""
    created = []
    for _, (path, job) in sorted(jobs.items()):
        if job.get('role') != 'edit' or not any(s in replaced for s in job.get('shots', [])):
            continue
        copy = fresh(job, next_id(ws, job['id']), note)
        copy['shots'] = [new for s in job['shots'] for new in replaced.get(s, [s])]
        created.append(copy)
    return created


def continuations(jobs, shot_id):
    return [job for _, (_, job) in sorted(jobs.items()) if job.get('continuity_from') == shot_id]


def plan_chain(ws, jobs, old_id, new_last_id, note, replaced, out):
    """Re-plan shots that continued from old_id so they continue from the new clip instead."""
    for dependent in continuations(jobs, old_id):
        copy = fresh(dependent, next_id(ws, dependent['id']), note)
        copy['continuity_from'] = new_last_id
        out.append(copy)
        replaced[dependent['id']] = [copy['id']]
        plan_chain(ws, jobs, dependent['id'], copy['id'], note, replaced, out)


def save(ws, jobs, brand):
    warnings = []
    for job in jobs:
        if job.get('prompt'):
            warnings += lint(job, brand)
    for job in jobs:
        path = ws/'jobs'/f"{job['id']}.json"
        if path.exists():
            raise ValueError('İş zaten var: ' + job['id'])
    for job in jobs:
        write(ws/'jobs'/f"{job['id']}.json", job)
        print(f"{job['id']}: {'montaj' if job.get('role') == 'edit' else 'yeni deneme'} planlandı"
              + (f" ← {job['revision_of']}" if job.get('revision_of') else ''))
    for w in warnings:
        print('UYARI: ' + w)
    return jobs


def generatable(job):
    if not job.get('prompt'):
        raise ValueError(f"{job['id']}: promptu olan bir çekim veya tek parça reklam seçin "
                         '(montaj işleri kendi çekimlerinden oluşur).')


def warn_dependents(jobs, identity, chain):
    deps = continuations(jobs, identity)
    if deps and not chain:
        print('UYARI: şu çekimler hâlâ eski klipten devam ediyor (--zincir ile onlar da yenilenir): '
              + ', '.join(d['id'] for d in deps))


def revise(ws, identity, brand=None, note=None, extra=None, chain=False):
    jobs = known(ws)
    if identity not in jobs:
        raise ValueError('İş bulunamadı: ' + identity)
    job = jobs[identity][1]
    generatable(job)
    new = fresh(job, next_id(ws, identity), note)
    new['prompt'] = with_extra(job['prompt'], extra)
    out, replaced = [new], {identity: [new['id']]}
    if chain:
        plan_chain(ws, jobs, identity, new['id'], note, replaced, out)
    else:
        warn_dependents(jobs, identity, chain)
    out += swap_into_montages(ws, replaced, note, jobs)
    return save(ws, out, brand)


def split_voiceover(text, first_share):
    """Split at the sentence boundary closest to the duration share; never mid-sentence."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if len(sentences) < 2:
        raise ValueError('Seslendirme tek cümle; bölmek için önce cümleyi ikiye ayırın.')
    total = len(text.split())
    best = min(range(1, len(sentences)),
               key=lambda k: abs(len(' '.join(sentences[:k]).split()) - total * first_share))
    return ' '.join(sentences[:best]), ' '.join(sentences[best:])


BEAT = re.compile(r'(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?) s: (.*?)(?=\s*\d+(?:\.\d+)?-\d+(?:\.\d+)? s: |$)', re.S)


def split_beats(prompt, original, durations):
    """Share the 'Timeline:' beats between the parts, rescaled to each part's length.

    Returns (timeline 1, timeline 2, action for part 2) or None when the prompt has no timeline."""
    line = next((l for l in prompt.split('\n') if l.startswith('Timeline: ')), None)
    beats = [(float(a), float(b), text.strip()) for a, b, text in BEAT.findall(line[10:])] if line else []
    if not beats:
        return None
    cut = original * durations[0] / sum(durations)
    first = [b for b in beats if b[0] < cut] or beats[:1]
    second = [b for b in beats if b not in first]
    if not second:
        return None

    def timeline(part, start, end, seconds):
        scale = seconds / (end - start)
        return 'Timeline: ' + ' '.join(
            f'{round((a - start) * scale)}-{round((min(b, end) - start) * scale)} s: {t}' for a, b, t in part)
    split_at = second[0][0]
    return (timeline(first, 0, split_at, durations[0]), timeline(second, split_at, original, durations[1]),
            ' '.join(t for _, _, t in second))


def part_prompt(prompt, seconds, voiceover, *, first, references, timeline=None, action=None):
    if timeline:
        prompt = '\n'.join(timeline if l.startswith('Timeline: ') else l for l in prompt.split('\n'))
    if action:
        # Part 2 starts mid-scene: its main action is what is left of the scene, not the whole scene.
        prompt = re.sub(r'^(\[[^\]]*\] ).*$', lambda m: m[1] + 'Continuing the same moment: ' + action, prompt,
                        count=1, flags=re.M)
    prompt = re.sub(r'^\d+-second', f'{seconds}-second', prompt)
    prompt = re.sub(r'(<d>\[[^\]]*\]\s*).*?(</d>)', lambda m: m[1] + voiceover + m[2], prompt, count=1, flags=re.S)
    lines = prompt.split('\n')
    if first:
        # The second part now carries the ending.
        return '\n'.join(l for l in lines if not l.startswith('The final seconds continue'))
    lines = [CONTINUATION if l.startswith('Opening hook:') else l for l in lines]
    if 'last frame of the previous shot' not in prompt:
        at = next(i for i, l in enumerate(lines) if l == CONTINUATION or l.startswith('Continuation shot:'))
        lines.insert(at, f'<Picture {references + 1}> is the last frame of the previous shot: continue seamlessly '
                         'with the same person, outfit, room, props, lighting and colour grade.')
    prompt = '\n'.join(lines)
    if 'timbre of <Audio 1>' not in prompt:
        prompt = re.sub(r'(Voice: [^\n]*?\.)( [A-Z])', r'\1 The voice keeps exactly the timbre of <Audio 1>.\2', prompt,
                        count=1)
    return prompt


def split(ws, identity, durations, brand=None, note=None, chain=False, second_visual=None):
    """Replace one clip with two continuous parts, e.g. a 15 s shot → 8 + 8 s.

    second_visual: what happens in part 2; by default it comes from the prompt's timeline."""
    if len(durations) != 2 or not all(4 <= d <= 15 for d in durations):
        raise ValueError('Bölme iki parça olmalı, her biri 4–15 sn (ör. 8+8).')
    jobs = known(ws)
    if identity not in jobs:
        raise ValueError('İş bulunamadı: ' + identity)
    job = jobs[identity][1]
    generatable(job)
    first_vo, second_vo = split_voiceover(job.get('voiceover') or '', durations[0] / sum(durations))
    base = next_id(ws, identity)
    refs = len(job.get('references') or [])
    has_voice = 'timbre of <Audio 1>' in job['prompt']
    beats = split_beats(job['prompt'], job['duration_seconds'], durations) or (None, None, None)
    action = second_visual or beats[2]
    if not action:
        print('UYARI: promptta zaman çizelgesi yok; 2. parça aynı aksiyonu baştan oynayabilir. '
              '--gorsel2 ile 2. parçada ne olacağını yazın.')
    p1 = fresh(job, f'{base}-p1', note)
    p1.update(prompt=part_prompt(job['prompt'], durations[0], first_vo, first=True, references=refs,
                                 timeline=beats[0]),
              duration_seconds=durations[0], voiceover=first_vo, role='shot', trim=None)
    p2 = fresh(job, f'{base}-p2', note)
    p2.update(prompt=part_prompt(job['prompt'], durations[1], second_vo, first=False, references=refs,
                                 timeline=beats[1], action=action),
              duration_seconds=durations[1], voiceover=second_vo, role='shot', trim=None, transition='cut',
              continuity_from=p1['id'], hook_text=None,
              # The narrator is <Audio 1>: a voice sample if the clip had one, else part 1's own voice.
              voice_from_previous=job.get('voice_from_previous', False) if has_voice else not job.get('audio_references'))
    out = [p1, p2]
    if job.get('role') == 'shot':
        p1['parent'] = p2['parent'] = job.get('parent')
        replaced = {identity: [p1['id'], p2['id']]}
        if chain:
            plan_chain(ws, jobs, identity, p2['id'], note, replaced, out)
        else:
            warn_dependents(jobs, identity, chain)
        out += swap_into_montages(ws, replaced, note, jobs)
    else:
        # A one-piece ad becomes a two-shot montage that renders like any other.
        montage = fresh(job, base, note)
        for key in ['prompt', 'visual_direction', 'camera', 'references', 'video_references', 'audio_references',
                    'continuity_from', 'voice_from_previous', 'seed', 'trim', 'transition', 'model']:
            montage.pop(key, None)
        montage.update(role='edit', shots=[p1['id'], p2['id']], duration_seconds=sum(durations))
        for part in (p1, p2):
            part['parent'] = base
            for key in ['caption', 'cta', 'app_name', 'emphasis', 'music', 'research', 'selected_for_publication',
                        'review_required', 'angle', 'feature', 'hook', 'timezone']:
                part.pop(key, None)
        out.append(montage)
    if not p1.get('continuity_from'):
        p1.pop('continuity_from', None)
    return save(ws, out, brand)
