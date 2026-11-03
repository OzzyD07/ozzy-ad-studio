"""Campaign strategy scaffold: concept matrix, hook variants, shot structure and test plan.

The output is a brief for the local agent (Claude/Codex), which writes the final scripts into
product.json. Frameworks are starting points, not a cage: timely trend concepts come from
research.json `trends`, the agent may replace any slot with a free-form concept, and the
reference library (assets/refs) is listed so ads can be built on images, motion videos or
real footage. Hook lines are drafts; the agent rewrites them and keeps every claim verifiable.
"""
from datetime import date, timedelta
from pathlib import Path

import minimax

ROOT = Path(__file__).resolve().parent

# Each framework is a beat sheet; seconds sum to the ad length and map onto 1–3 MiniMax shots.
FRAMEWORKS = {
    'pas': {'name': 'Problem → Agitate → Solve', 'length': 30, 'beats': [
        ('hook', 3, 'Name the pain in one line while it is happening on screen.'),
        ('agitate', 7, 'Show the cost of the problem in a relatable daily moment.'),
        ('solve', 14, 'The feature as the turning point; calm, concrete result on screen.'),
        ('cta', 6, 'Spoken CTA; the end card with store badges carries the action.')]},
    'before_after': {'name': 'Before / After', 'length': 30, 'beats': [
        ('hook', 3, 'Show the messy "before" state with a pattern-interrupt camera move.'),
        ('before', 9, 'Same person, same room: the struggle in two quick beats.'),
        ('after', 12, 'Same framing, transformed state; one feature makes the difference.'),
        ('cta', 6, 'Spoken CTA over the "after" state.')]},
    'pov': {'name': 'POV story', 'length': 15, 'beats': [
        ('hook', 3, '"POV: ..." situation the audience instantly recognises (text hook on screen).'),
        ('moment', 8, 'First-person feel, handheld camera, one small win with the feature.'),
        ('cta', 4, 'Short spoken CTA.')]},
    'listicle': {'name': '3 reasons / 3 ways', 'length': 30, 'beats': [
        ('hook', 3, 'Number promise: "3 small ways to ..."'),
        ('one', 7, 'Reason 1, its own visual moment.'),
        ('two', 7, 'Reason 2, new angle in the same setting.'),
        ('three', 7, 'Reason 3 = the app feature.'),
        ('cta', 6, 'CTA.')]},
    'creator': {'name': 'Creator talking to camera (lip-sync)', 'length': 30, 'beats': [
        ('hook', 3, 'On-camera speaker opens with a confession or bold line (speaker: on_camera).'),
        ('story', 13, 'Short personal-style story, framed as a concept, never a testimonial.'),
        ('feature', 8, 'What the app does, shown with hands/objects, no UI.'),
        ('cta', 6, 'Speaker says the CTA.')]},
    'routine': {'name': 'Routine / day-in-the-life', 'length': 15, 'beats': [
        ('hook', 3, 'Satisfying ritual close-up (lamp click, pen cap, mug).'),
        ('routine', 8, 'Three fast routine beats ending with the app moment.'),
        ('cta', 4, 'CTA.')]},
    'trend': {'name': 'Trend / topical moment', 'length': 15, 'needs': 'trend', 'beats': [
        ('hook', 3, 'Open on the moment or format everyone already knows (season, event, trending format).'),
        ('bridge', 8, 'Bridge it naturally to the everyday problem; the feature is the twist, not an add-on.'),
        ('cta', 4, 'CTA in the tone of the trend.')]},
    'demo': {'name': 'Real app demo + lifestyle', 'length': 20, 'needs': 'footage', 'beats': [
        ('hook', 5, 'Generated lifestyle hook: the problem moment, no screens.'),
        ('demo', 8, 'Real screen recording (clip shot) of one flow; the only place real UI appears.'),
        ('result', 7, 'Generated payoff shot: the calm result + spoken CTA.')]},
}
# Shot recipes for reference-driven ads (shown in the brief when matching files exist).
REFERENCE_IDEAS = {
    'Picture': 'character/setting/product sheets in `look.references` keep every shot on-model; '
               'a `style` frame copies a grade or composition you like.',
    'Video': 'a 2–15 s motion clip as `{"file": ..., "role": "motion" | "action" | "trend"}` copies the camera '
             'move, a gesture or a trend format (<Video N>); people, place and text still come from the prompt.',
    'Audio': '`voice` (2–15 s narrator sample) fixes the timbre across shots; `music` steers the background track.',
    'Clip': 'real footage as a shot `{"clip": "assets/refs/demo.mp4@0-6", "voiceover": ...}` is cut in as-is: '
            'screen recordings, product close-ups, UGC. Real UI is allowed only this way.',
}
TREND_RULES = [
    'Use a trend only while it is fresh (the brief shows `expires`); a late trend is worse than none.',
    'Borrow the format, rhythm or the moment, never copyrighted audio, memes, real people, celebrities or other brands.',
    'Skip tragedies, politics, religion and anything that makes the product look opportunistic.',
    'The trend has to fit the product problem in one sentence; if it needs explaining, drop it.',
    'Trend ads are 15 s, one shot; a `trend` motion reference (<Video N>) can copy the format.',
]

HOOK_FORMULAS = [
    ('question', 'What if {effort} could help you {outcome}?'),
    ('stop', 'Stop waiting for motivation to {outcome}.'),
    ('pov', 'POV: you finally {outcome}.'),
    ('number', '3 small ways to {outcome}.'),
    ('contrarian', "You don't need more willpower. You need a smaller first step."),
    ('confession', 'I was tired of {pain}. This is what helped.'),
    ('curiosity', 'One habit, {effort}. Here is why it works.'),
]
PLATFORMS = {
    'TikTok': '9:16, 15–30 s; text hook in the first 2 s; keep the bottom ~420 px and right ~140 px clear.',
    'Instagram Reels': '9:16, 15–30 s; same safe zones; captions on (most viewers start muted).',
    'YouTube Shorts': '9:16, ≤60 s; the first frame is the thumbnail, make it readable.',
}
TEST_RULES = [
    'Week 1: 3 concepts × 2 hook variants (A/B share the body shots, only the opening shot is new).',
    'Judge each variant after ~1,000–2,000 impressions, not earlier.',
    'Hook rate (3 s views / impressions) under ~25% → replace the opening shot, keep the body.',
    'Hold rate (15 s or ThruPlay / 3 s views) under ~15% → tighten the middle beats or shorten to 15 s.',
    'CTR under ~0.8% with good hold → test a different CTA line or end card headline.',
    'Scale the winner; make 2 new hooks for it every week to fight creative fatigue.',
    'These thresholds are starting heuristics; replace them with the account\'s own benchmarks.',
]


def draft_hooks(product, feature, script_hints):
    # outcome: verb phrase, effort: noun phrase, pain: noun phrase (see strategy_hints in the product file).
    values = {'outcome': script_hints.get('outcome', 'stay consistent'),
              'effort': script_hints.get('effort', 'two minutes a day'),
              'pain': script_hints.get('pain', 'days that blur together')}
    return [{'type': kind, 'line': template.format(**values)} for kind, template in HOOK_FORMULAS]


def shot_plan(framework, frameworks=FRAMEWORKS):
    """Group beats into MiniMax shots of at most 15 s (the model's limit)."""
    shots, current = [], []
    for beat in frameworks[framework]['beats']:
        if current and sum(b[1] for b in current) + beat[1] > 15:
            shots.append(current)
            current = []
        current.append(beat)
    shots.append(current)
    return [{'duration': max(4, sum(b[1] for b in s)), 'beats': [b[0] for b in s],
             'max_words': int(minimax.WORDS_PER_SECOND * (sum(b[1] for b in s) - .5))} for s in shots]


def reference_library(product, folder=None, ws=None):
    """Files the agent can build on: the app's assets/refs, shared assets/refs and the look references."""
    from media import media_duration
    folders = [Path(folder)] if folder else [Path(ws)/'assets'/'refs'] * bool(ws) + [ROOT/'assets'/'refs']
    files = sorted(f for d in folders if d.is_dir() for f in d.glob('*') if f.is_file())
    items = []
    for f in files:
        kind = minimax.media_kind(f.name)
        if kind == 'Picture' and f.suffix.lower() not in minimax.IMAGE_EXT:
            continue
        # Paths as the product file writes them: relative to the app folder, else to the project.
        home = next((b for b in (ws, ROOT) if b and f.is_relative_to(b)), None)
        item = {'file': f.relative_to(home).as_posix() if home else str(f), 'kind': kind}
        if kind != 'Picture':
            seconds = media_duration(f)
            if not seconds:
                continue
            item['seconds'] = round(seconds, 1)
        items.append(item)
    used = {r['file'] for r in (product.get('look') or {}).get('references', [])}
    for item in items:
        item['in_look'] = item['file'] in used
    return items


def schedule(product, research, start, days, library):
    """Day → framework. Trends take their date (or the earliest free day); the rest rotates."""
    hints = product.get('strategy_hints') or {}
    frameworks = {**FRAMEWORKS, **hints.get('frameworks', {})}
    has_footage = any(i['kind'] == 'Video' for i in library)
    rotation = [n for n in hints.get('mix') or list(frameworks)
                if frameworks[n].get('needs') not in ('trend',) and
                (frameworks[n].get('needs') != 'footage' or has_footage)]
    days_list = [(start + timedelta(days=i)).isoformat() for i in range(days)]
    slots = {d: None for d in days_list}
    for trend in research.get('trends', []):
        if trend.get('expires') and trend['expires'] < days_list[0]:
            print('Trend süresi dolmuş, atlandı: ' + trend.get('topic', '?'))
            continue
        fits = [d for d in days_list if slots[d] is None and (not trend.get('date') or d >= trend['date'])
                and (not trend.get('expires') or d <= trend['expires'])]
        if fits:
            slots[fits[0]] = ('trend', trend)
    k = 0
    for d in days_list:
        if slots[d] is None:
            slots[d] = (rotation[k % len(rotation)], None)
            k += 1
    return frameworks, slots


FORMAT_GUIDE = {
    'image_post': '`image_prompt` (a text-free scene: Qwen is asked for no letters/logos; describe blank screens/paper) + '
                  '`post` {kicker, title with *highlight*, body, cta, layout: bottom|center|top}. One idea, ≤12 words of title.',
    'carousel': '`slides` (4–6): slide 1 is the hook (layout center, no image), the middle slides each carry one point '
                '(optional `image_prompt`), the last slide has `cta` and `"brand": true`. `swipe_label` in the post language.',
    'template_video': '`promo` {scenes [{duration, kicker, title, body, media {src: assets/refs/..., device: phone}}], '
                      '`voiceover` {text, voice}, `fitToVoiceover`: true, `captions` {style}}. No GPU: use it for '
                      'app-screen demos, tips and listicles.',
    'ai_video': 'MiniMax concept from the concept list above (hooks/shots); add `cuts` for extra edits of the same footage.',
}


def slot_plan(start, days, per_day, cfg):
    """Markdown section: which format each day/slot gets, with the GPU budget applied."""
    import takvim
    rows = takvim.suggest(start, days, per_day, cfg)
    s = takvim.settings(cfg)
    lines = ['## Daily slots and formats', '',
             f'{per_day} posts a day. AI video at most {s["budget"]["ai_videos_per_week"]} per week (GPU budget); '
             'a slot that ran out of AI video budget falls back to its next format. Write one `scripts` entry per '
             'row, in this order, with `"format"` and `"slot"` set as listed.', '',
             '| Day | Slot | Time | Format |', '|---|---|---|---|']
    lines += [f'| {d} | {slot or "-"} | {takvim.slot_time(slot, cfg) or "-"} | {f} |' for d, slot, f in rows]
    lines += ['', '### Writing each format', ''] + [f'- **{k}:** {v}' for k, v in FORMAT_GUIDE.items()] + ['']
    return lines


def build(product, research, start, days, ws, refs_dir=None, cfg=None, per_day=1):
    features = product['features']
    hints = product.get('strategy_hints') or {}
    start = date.fromisoformat(start)
    library = reference_library(product, refs_dir, ws)
    frameworks, slots = schedule(product, research, start, days, library)
    findings = research.get('findings') or [{'implication': '-'}]
    concepts = []
    for i, (day, (framework, trend)) in enumerate(slots.items()):
        feature = features[i % len(features)]
        concept = {'day': day, 'framework': framework, 'feature': feature,
                   'length': frameworks[framework]['length'], 'shots': shot_plan(framework, frameworks),
                   'hooks': draft_hooks(product, feature, hints)[i % 3::3][:3],
                   'research': findings[i % len(findings)]}
        if trend:
            concept['trend'] = trend
        concepts.append(concept)
    lines = [f"# {product['name']} — creative strategy ({start}, {days} days)", '',
             f"**Audience:** {product['audience']}", '',
             '## Principles', '',
             '- The first 2 seconds decide everything: motion in frame 1, voice at 0.0 s, a text hook on screen.',
             '- One ad = one feature = one feeling. No feature lists.',
             '- Show the outcome in the real world (hands, rooms, rituals); never fake app UI or testimonials.',
             '- Captions always on; brand name and numbers highlighted; end card with App Store + Google Play badges.',
             '- 30 s ads = 2 MiniMax shots joined with continuity references; 15 s ads = 1 shot.',
             '- Every hook gets an A/B twin; variants reuse the body shots, so a test costs one extra generation.',
             '- The frameworks below are defaults, not rules. Replace any slot with a free-form concept when you have '
             'a better idea (new format, seasonal moment, a reference video worth copying); keep the principles above.',
             '', '## Platforms', ''] + [f'- **{k}:** {v}' for k, v in PLATFORMS.items()] + [
             '', '## Testing and iteration', ''] + [f'- {r}' for r in TEST_RULES] + [
             '', '## Trends and topical ads', ''] + [f'- {r}' for r in TREND_RULES] + [
             '', '## Reference library', '']
    if library:
        lines += [f"- `{i['file']}` — {i['kind'].lower()}" + (f", {i['seconds']} s" if 'seconds' in i else '')
                  + (' (in look)' if i['in_look'] else '') for i in library]
    else:
        lines += ['- assets/refs is empty: add character sheets, motion clips or screen recordings to unlock '
                  'reference-driven concepts.']
    kinds = {i['kind'] for i in library} | ({'Clip'} if any(i['kind'] == 'Video' for i in library) else set())
    lines += [''] + [f'- **{k}:** {REFERENCE_IDEAS[k]}' for k in REFERENCE_IDEAS if k in kinds or not library]
    lines += ['', '## Excluded claims', ''] + [f'- {c}' for c in product.get('claims_excluded', [])] + ['', '## Concepts', '']
    for c in concepts:
        fw = frameworks[c['framework']]
        lines += [f"### {c['day']} — {fw['name']} · {c['feature']} · {c['length']} s", '',
                  '**Beats:** ' + ' → '.join(f'{b[0]} ({b[1]} s): {b[2]}' for b in fw['beats']), '',
                  '**Shots:** ' + ' | '.join(f"shot {k} = {s['duration']} s [{', '.join(s['beats'])}], "
                                             f"≤{s['max_words']} words" for k, s in enumerate(c['shots'], 1)), '',
                  '**Draft hooks (rewrite naturally, pick two for A/B):** ' +
                  ' / '.join(f"{h['line']} ({h['type']})" for h in c['hooks']), '',
                  f"**Research angle:** {c['research']['implication']}", '']
        if c.get('trend'):
            t = c['trend']
            lines[-1:-1] = [f"**Trend:** {t.get('topic')} — {t.get('angle', '')}"
                            + (f" (until {t['expires']})" if t.get('expires') else '')
                            + (f" · source: {t['source']}" if t.get('source') else ''), '']
    if per_day > 1:
        lines += slot_plan(start, days, per_day, cfg)
    lines += ['## How to write the scripts (for the agent)', '',
              'Fill `scripts` in the product file. A 30 s concept uses `hooks` (2 alternative opening shots) and',
              '`shots` (the shared body). Each shot: `duration` (4–15), `camera` (from: ' +
              ', '.join(minimax.CAMERA_MOVES) + '), `visual` (subject + action first, then details), `voiceover`',
              '(only this shot\'s words), optional `speaker: "on_camera"` for lip-sync, `beats` (timeline lines),',
              '`references` ([{"file", "role"}]: images, motion videos or audio, see the reference library),',
              '`transition` (into this shot) and `hook_text` on hook shots. A shot can instead be real footage:',
              '`{"clip": "file@start-end", "voiceover"}`. Add `"framework"` to each script (a name above or',
              '`"free"`) so results can be compared later. Put the brand name only in voiceover/caption/cta.',
              'Then run `lint` and `plan`.']
    out = ws/'plans'/f'strategy-{start}.md'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    import pipeline
    pipeline.write(ws/'plans'/f'strategy-{start}.json', {'product': product['name'], 'concepts': concepts})
    print(f'{len(concepts)} konsept; strateji: {out}')
    return concepts
