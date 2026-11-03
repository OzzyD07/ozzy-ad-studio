"""OtoReklam: file-backed advertising production queue."""
import argparse
import base64
import copy
import csv
import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib.request
from urllib.parse import urljoin
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import minimax

ROOT = Path(__file__).resolve().parent
# Kept on disk for history, never worked on: cleaned-up clips and plans replaced by a revision.
RETIRED = {'removed_by_cleanup', 'superseded'}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def config(path):
    cfg = read(path)
    cfg['workspace'] = str((ROOT / cfg['workspace']).resolve())
    return cfg


@contextmanager
def lock(workspace):
    path = Path(workspace) / '.queue.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = path.open('x')
    except FileExistsError:
        raise ValueError('Kuyruk kilitli. Başka işlem olmadığından emin olduktan sonra .queue.lock dosyasını kaldırın.')
    try:
        handle.write(str(os.getpid()))
        handle.close()
        yield
    finally:
        path.unlink(missing_ok=True)


APP_FOLDERS = ['input', 'analysis', 'plans', 'jobs', 'raw', 'exports', 'refs', 'assets/refs', 'assets/music']


def initialize(cfg):
    ws = Path(cfg['workspace'])
    for name in ['apps', 'models']:
        (ws/name).mkdir(parents=True, exist_ok=True)
    print('Çalışma klasörü: ' + str(ws))
    print('Yeni uygulama: new-app KISA-AD --name "Uygulama Adı"')


# Each app lives in workspace/apps/<slug>/: its product and research files, plans, jobs, raw clips,
# exports, icon and reference library. Whisper models, badges and fonts stay shared.
def app_root(cfg):
    return Path(cfg['workspace'])/'apps'


def app_dir(cfg, slug):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,40}', slug or ''):
        raise ValueError('Uygulama kısa adı küçük harf, rakam ve tire olmalı (ör. mentorai).')
    return app_root(cfg)/slug


def apps(cfg):
    root = app_root(cfg)
    return sorted(d.name for d in root.iterdir() if (d/'app.json').is_file()) if root.is_dir() else []


def open_app(cfg, slug=None):
    """Return (app folder, config for this app). The app's own icon and config overrides apply."""
    if not slug:
        known = apps(cfg)
        slug = cfg.get('default_app') or (known[0] if len(known) == 1 else None)
        if not slug:
            raise ValueError('Hangi uygulama? --app ile seçin (' + (', '.join(known) or 'henüz yok: new-app') + ').')
    ws = app_dir(cfg, slug)
    if not (ws/'app.json').is_file():
        raise ValueError(f'Uygulama bulunamadı: {slug}. Önce: new-app {slug} --name "Ad"')
    meta = read(ws/'app.json')
    cfg = copy.deepcopy(cfg)
    for key, value in (meta.get('config') or {}).items():
        cfg[key] = {**cfg.get(key, {}), **value} if isinstance(value, dict) else value
    icon = ws/'assets'/'app-icon.png'
    if icon.is_file():
        cfg['end_card'] = {**cfg.get('end_card', {}), 'icon': str(icon)}
    cfg['app'] = {**meta, 'slug': slug, 'dir': str(ws)}
    return ws, cfg


def new_app(cfg, slug, name):
    ws = app_dir(cfg, slug)
    if (ws/'app.json').exists():
        raise ValueError('Bu uygulama zaten var: ' + str(ws))
    for folder in APP_FOLDERS:
        (ws/folder).mkdir(parents=True, exist_ok=True)
    product = read(ROOT/'examples'/'product.example.json')
    product['name'] = name
    write(ws/'product.json', product)
    shutil.copy2(ROOT/'examples'/'research.example.json', ws/'research.json')
    write(ws/'app.json', {'name': name, 'slug': slug, 'product': 'product.json', 'research': 'research.json',
                          'created': date.today().isoformat(), 'config': {}})
    print(f'{name} oluşturuldu: {ws}\nproduct.json ve research.json dosyalarını doldurun; '
          'ikon için assets/app-icon.png, referanslar için assets/refs/.')


def app_file(ws, cfg, given, key):
    """--product/--research, or the app's own file named in app.json."""
    if given:
        return Path(given)
    name = (cfg.get('app') or {}).get(key)
    if not name:
        raise ValueError(f'--{key} gerekli.')
    return ws/name


def analyze(source, ws):
    source = Path(source).resolve()
    if not source.is_dir():
        raise ValueError('Uygulama kaynak klasörü bulunamadı.')
    skip = {'.git', '.venv', 'venv', 'node_modules', 'build', 'dist', '.next',
            '.aws', '.ssh', '__pycache__', 'workspace'}
    extensions = {'.md', '.txt', '.json', '.py', '.ts', '.tsx', '.js', '.jsx',
                  '.dart', '.swift', '.kt', '.html', '.cs', '.vue'}
    files, excerpts, total = [], [], 0
    for folder, dirs, names in os.walk(source, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in skip and not d.startswith('.')
                         and not (Path(folder)/d).is_symlink())
        for name in sorted(names):
            p = Path(folder)/name
            if p.is_symlink() or name.startswith('.') or p.suffix.lower() not in extensions:
                continue
            if re.search(r'(secret|credential|token|password|lock|private.key)', name, re.I):
                continue
            files.append(str(p.relative_to(source)))
            if p.stat().st_size > 100_000 or total >= 100_000:
                continue
            text = p.read_text(encoding='utf-8', errors='replace')[:6000]
            # Basic redaction is defense in depth, not a guarantee of secret detection.
            text = re.sub(r'(?im)^.*(?:api[_-]?key|secret|password|bearer|access[_-]?token).*$','[REDACTED]', text)
            text = text[:100_000-total]
            total += len(text)
            excerpts.append({'file': str(p.relative_to(source)), 'text': text})
    packet = {'source': str(source), 'files': files, 'excerpts': excerpts,
              'note': 'Yerel envanterdir; ürün analizi değildir. Dışarı göndermeden gözden geçirin.'}
    write(ws/'analysis'/'source-context.json', packet)
    (ws/'analysis'/'research-brief.md').write_text('''# Analiz ve araştırma görevi
source-context.json dosyasından uygulamanın gerçek işlevlerini incele.
Hedef kitleyi, problemi, kanıtlanabilen faydaları ve demo akışlarını belirle.
Güncel rakipleri ve hedef platformun resmi reklam gereksinimlerini araştır.
Her bulgu için kaynak URL'si, kontrol tarihi ve içeriğe etkisini kaydet.
Ücretsiz, garantili, en iyi gibi doğrulanmayan iddialar üretme.
product.json ve research.json örneklerini gerçek bilgilerle doldur.
Bu dosyalar yereldir; analiz komutu internete veri göndermez.
''', encoding='utf-8')
    print(f'{len(files)} dosya listelendi; bağlam: {ws / "analysis"}')


def plan(product_path, research_path, start, days, ws):
    product, research = read(product_path), read(research_path)
    for key in ['name', 'audience', 'features', 'cta', 'url']:
        if not product.get(key):
            raise ValueError('Ürün bilgisi eksik: ' + key)
    if not isinstance(product['features'], list) or not all(isinstance(x,str) and x.strip() for x in product['features']):
        raise ValueError('features dolu metinlerden oluşan liste olmalı.')
    findings = research.get('findings', [])
    if not findings or not all(f.get('finding') and f.get('implication') and
                               str(f.get('url','')).startswith('https://') and f.get('checked_on') for f in findings):
        raise ValueError('Araştırmada finding, implication, https URL ve checked_on alanları gerekli.')
    start = date.fromisoformat(start)
    if not 1 <= days <= 90:
        raise ValueError('Takvim 1–90 gün olmalı.')
    if product.get('scripts'):
        return plan_scripts(product, findings, start, days, ws)
    jobs = []
    angles = ['Problem ve çözüm', 'Özellik demosu', 'Kullanım senaryosu']
    for i in range(days):
        day = (start + timedelta(days=i)).isoformat()
        feature = product['features'][i % len(product['features'])]
        finding = findings[i % len(findings)]
        angle = angles[i % len(angles)]
        prompt = (f"{product['name']} için Türkçe 15 saniyelik 9:16 uygulama reklamı. "
                  f"Hedef kitle: {product['audience']}. Açı: {angle}. "
                  f"Yalnızca doğrulanmış özellik: {feature}. "
                  f"Araştırmanın yaratıcı etkisi: {finding['implication']}. "
                  '0–3 sn dikkat çekici giriş, 3–11 sn tek faydanın gösterimi, 11–15 sn kapanış. '
                  'Doğal Türkçe seslendirme. Altyazı ve CTA görselini videoya ekleme; sonradan eklenecek. '
                  'Alt bölümde altyazı için boşluk bırak. Sahte kullanıcı yorumu veya ürün iddiası kullanma.')
        identity = hashlib.sha256((product['name']+day+prompt).encode()).hexdigest()[:8]
        jobs.append({'id': f'{day}-{identity}', 'date': day, 'timezone': 'Europe/Istanbul',
                     'status': 'planned', 'angle': angle, 'prompt': prompt,
                     'caption': f"{product['name']} ile {feature}.\n{product['cta']}: {product['url']}",
                     'cta': product['cta'], 'research': finding, 'remote_id': None})
    for j in jobs:
        path = ws/'jobs'/f"{j['id']}.json"
        if not path.exists():
            write(path, j)
    calendar = ws/'plans'/f'calendar-{start}.csv'
    with calendar.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['id', 'date', 'timezone', 'angle', 'caption', 'cta'])
        writer.writeheader()
        writer.writerows({k:j[k] for k in writer.fieldnames} for j in jobs)
    print(f'{len(jobs)} iş; takvim: {calendar}')


def resolve_asset(value, base=None):
    """Absolute paths as-is; relative ones from the app folder first, then the project (shared assets)."""
    path = Path(value)
    if path.is_absolute():
        return path
    if base and (Path(base)/path).exists():
        return Path(base)/path
    return ROOT / path


def shot_references(product, shot, base=None):
    """Product-wide sheets, then the shot's own, split by file type into <Picture>/<Video>/<Audio> order."""
    from media import media_duration
    refs = {'Picture': [], 'Video': [], 'Audio': []}
    roles = {'Picture': minimax.REFERENCE_ROLES, 'Video': minimax.VIDEO_ROLES, 'Audio': minimax.AUDIO_ROLES}
    for r in [*(product.get('look') or {}).get('references', []), *shot.get('references', [])]:
        kind = minimax.media_kind(r['file'])
        r = {'role': {'Picture': 'style', 'Video': 'motion', 'Audio': 'music'}[kind], **r}
        if r['role'] not in roles[kind]:
            raise ValueError(f"{r['file']}: {kind} için bilinmeyen rol {r['role']} (seçenekler: {', '.join(roles[kind])})")
        path = resolve_asset(r['file'], base)
        if not path.is_file():
            raise ValueError('Referans dosyası bulunamadı: ' + r['file'])
        if kind != 'Picture' and not 2 <= (media_duration(path) or 0) <= 15.5:
            raise ValueError(f"{r['file']}: video/ses referansı 2–15 sn olmalı (kırpıp assets/refs içine koyun).")
        refs[kind].append(r)
    # The ninth picture slot is kept for the continuity frame, the first audio slot for the narrator.
    for kind, limit in [('Picture', 8), ('Video', 3), ('Audio', 3)]:
        if len(refs[kind]) > limit:
            raise ValueError(f'En fazla {limit} {kind} referansı verilebilir.')
    return refs


def first_sentence(text):
    return re.split(r'(?<=[.!?])\s+', text.strip(), maxsplit=1)[0]


def clip_job(shot, *, job_id, parent, language, base=None):
    """Real footage (screen recording, product shot, UGC) used as-is in the montage; nothing is generated."""
    path, _, span = shot['clip'].partition('@')
    spec = clip_spec(f'{resolve_asset(path, base)}@{span}')
    duration = (spec['end'] or probe_duration(spec['path'])) - (spec['start'] or 0)
    return {'id': job_id, 'role': 'shot', 'source': 'clip', 'parent': parent, 'status': 'raw_ready',
            'language': language, 'raw_video': str(Path(spec['path']).resolve()), 'clip': shot['clip'],
            'trim': [spec['start'], spec['end']], 'transition': shot.get('transition'),
            'voiceover': shot.get('voiceover', ''), 'visual_direction': shot.get('visual') or 'gerçek görüntü',
            'camera': None, 'duration_seconds': round(duration, 2), 'references': [], 'remote_id': None}


def probe_duration(path):
    from media import probe
    return probe(path)['duration']


def shot_job(product, shot, *, job_id, parent, index, total, language, continuity_from=None, base=None):
    if shot.get('clip'):
        return clip_job(shot, job_id=job_id, parent=parent, language=language, base=base)
    refs = shot_references(product, shot, base)
    voice = next((r['file'] for r in refs['Audio'] if r['role'] == 'voice'), None) or \
        (product.get('look') or {}).get('voice_reference')
    music = [r for r in refs['Audio'] if r['role'] != 'voice']
    # Each clip gets its own generated narrator; a voice sample keeps the timbre the same across shots.
    voice_ref = bool(voice) or bool(continuity_from)
    prompt = minimax.build_prompt(product, shot, index=index, total=total, language=language,
                                  references=refs['Picture'], continuity=bool(continuity_from),
                                  voice_reference=voice_ref, videos=refs['Video'], audios=music)
    return {'id': job_id, 'role': 'shot', 'parent': parent, 'status': 'planned', 'language': language,
            'prompt': prompt, 'voiceover': shot.get('voiceover', ''), 'visual_direction': shot['visual'],
            'camera': shot.get('camera'), 'duration_seconds': shot.get('duration', 15),
            'references': [r['file'] for r in refs['Picture']],
            'video_references': [r['file'] for r in refs['Video']],
            # Voice first: the prompt always calls it <Audio 1>.
            'audio_references': ([voice] if voice else []) + [r['file'] for r in music],
            'continuity_from': continuity_from, 'voice_from_previous': bool(continuity_from) and not voice,
            'seed': shot.get('seed'), 'trim': shot.get('trim'), 'transition': shot.get('transition'),
            'remote_id': None, 'model': product.get('video_model')}


def lint_job(job, product):
    if not job.get('prompt'):
        return []  # Montage jobs and real-footage clips have no prompt of their own.
    images = len(job.get('references') or []) + (1 if job.get('continuity_from') else 0)
    audios = len(job.get('audio_references') or []) + (1 if job.get('voice_from_previous') else 0)
    return minimax.lint_prompt(job['prompt'], product.get('name'), images, audios,
                               len(job.get('video_references') or []))


def describe_refs(job):
    if job.get('source') == 'clip':
        return ' · gerçek görüntü: ' + job['clip']
    refs = [*job.get('references', []), *job.get('video_references', []), *job.get('audio_references', [])]
    return (' · ref: ' + ', '.join(Path(f).name for f in refs)) if refs else ''


def plan_scripts(product, findings, start, days, ws):
    language = product.get('language', 'tr')
    if len(product['scripts']) < days:
        raise ValueError(f"{days} gün için en az {days} senaryo gerekli.")
    links = '\n'.join(f'{label}: {product[key]}' for label, key in
                      [('Android', 'url'), ('iOS', 'ios_url')] if product.get(key))
    jobs, issues = [], []
    existing = {(j.get('date'), j.get('angle')) for j in map(read, (ws/'jobs').glob('*.json'))
                if j.get('role') != 'shot'}
    lines = [f"# {product['name']} — {days}-day ad plan ({language})", '',
             'Conceptual vertical ads (MiniMax H3). Review every export before publishing.', '']
    for i in range(days):
        s = product['scripts'][i]
        for key in ['angle', 'caption'] + ([] if s.get('shots') else ['hook', 'voiceover', 'visual']):
            if not s.get(key):
                raise ValueError(f'Senaryo {i+1} eksik: {key}')
        if not s.get('shots') and not s['voiceover'].startswith(s['hook']):
            raise ValueError(f'Senaryo {i+1}: seslendirme hook ile başlamalı.')
        issues += minimax.lint_script(s, product, i+1)
        day = (start + timedelta(days=i)).isoformat()
        if (day, s['angle']) in existing:
            print(f"{day} — {s['angle']}: iş zaten var, korunuyor.")
            continue
        base = f"{day}-{hashlib.sha256((product['name'] + day + json.dumps(s, sort_keys=True)).encode()).hexdigest()[:8]}"
        common = {'date': day, 'timezone': 'Europe/Istanbul', 'status': 'planned', 'language': language,
                  'angle': s['angle'], 'feature': s.get('feature'),
                  'caption': s['caption'] + ('\n' + links if links else ''),
                  'cta': s.get('cta', product['cta']), 'app_name': product['name'],
                  'emphasis': s.get('emphasis', []), 'music': s.get('music'),
                  'research': findings[i % len(findings)], 'remote_id': None,
                  'model': product.get('video_model'), 'review_required': True}
        if not s.get('shots'):
            job = shot_job(product, {**s, 'duration': s.get('duration', 15)}, job_id=base, parent=None,
                           index=1, total=1, language=language, base=ws)
            if s.get('clip'):
                raise ValueError(f'Senaryo {i+1}: gerçek görüntü (clip) yalnızca çok çekimli reklamda kullanılır.')
            for key in ['role', 'parent', 'trim', 'transition', 'continuity_from', 'voice_from_previous']:
                job.pop(key)
            job.update(common, hook=s['hook'], hook_text=s.get('hook_text'))
            jobs.append(job)
            lines += [f"## {day} — {s['angle']}", '', f"**Hook:** {s['hook']}", '',
                      f"**Voiceover:** {s['voiceover']}", '', f"**Visual:** {s['visual']}{describe_refs(job)}", '',
                      f"**Caption:** {s['caption']}", '', f"**CTA:** {job['cta']} · Job: `{job['id']}`", '']
            continue
        # Multi-shot ad: alternative opening hooks share the same body shots (cheap A/B tests).
        hooks = s.get('hooks') or [s['shots'][0]]
        body = s['shots'] if s.get('hooks') else s['shots'][1:]
        total = 1 + len(body)
        hook_jobs = [shot_job(product, h, job_id=f'{base}-h{chr(97+k)}', parent=base, index=1, total=total,
                              language=language, base=ws) for k, h in enumerate(hooks)]
        # Continuity points at the last generated shot: a screen recording is no visual anchor.
        generated = [j for j in hook_jobs if j.get('source') != 'clip']
        body_jobs, previous = [], generated[0]['id'] if generated else None
        for n, shot in enumerate(body, 2):
            job = shot_job(product, shot, job_id=f'{base}-s{n}', parent=base, index=n, total=total,
                           language=language,
                           continuity_from=previous if shot.get('continuity', True) and previous else None,
                           base=ws)
            body_jobs.append(job)
            if job.get('source') != 'clip':
                previous = job['id']
        jobs += hook_jobs + body_jobs
        lines += [f"## {day} — {s['angle']}", '']
        for k, hook_job in enumerate(hook_jobs):
            variant = chr(65+k) if len(hooks) > 1 else None
            shots = [hook_job] + body_jobs
            voiceover = ' '.join(x['voiceover'] for x in shots if x['voiceover'])
            parent = {'id': f'{base}-{variant}' if variant else base, 'role': 'edit', **common,
                      'variant': variant, 'hook': hooks[k].get('hook') or first_sentence(hooks[k].get('voiceover', '')),
                      'hook_text': hooks[k].get('hook_text') or s.get('hook_text'), 'voiceover': voiceover,
                      'shots': [x['id'] for x in shots],
                      'duration_seconds': sum(x['duration_seconds'] for x in shots)}
            jobs.append(parent)
            lines += [f"**Variant {variant or '-'}** · Job: `{parent['id']}` · hook: {parent['hook']}"
                      + (f" · on-screen: “{parent['hook_text']}”" if parent['hook_text'] else ''), '']
        for x in hook_jobs + body_jobs:
            lines += [f"- `{x['id']}` {x['duration_seconds']} s {x.get('camera') or ''}: {x['visual_direction']}"
                      + describe_refs(x) + (f" — VO: {x['voiceover']}" if x['voiceover'] else '')]
        lines += ['', f"**Caption:** {s['caption']}", '', f"**CTA:** {common['cta']}", '']
    for job in jobs:
        issues += [(level, f"{job['id']}: {msg}") for level, msg in lint_job(job, product)]
    errors = [msg for level, msg in issues if level == 'error']
    for level, msg in issues:
        if level == 'warning':
            print('UYARI: ' + msg)
    if errors:
        raise ValueError('Prompt denetimi başarısız:\n' + '\n'.join(errors))
    for j in jobs:
        path = ws/'jobs'/f"{j['id']}.json"
        if not path.exists():
            write(path, j)
    calendar = ws/'plans'/f'calendar-{start}-{language}.csv'
    calendar.parent.mkdir(parents=True, exist_ok=True)
    with calendar.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['id', 'date', 'timezone', 'angle', 'hook', 'caption', 'cta'])
        writer.writeheader()
        writer.writerows({k:j[k] for k in writer.fieldnames} for j in jobs if j.get('role') != 'shot')
    (ws/'plans'/f'plan-{start}-{language}.md').write_text('\n'.join(lines), encoding='utf-8')
    print(f'{len(jobs)} iş; takvim: {calendar}')


def job_path(ws, identity):
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', identity):
        raise ValueError('Geçersiz iş kimliği.')
    return ws/'jobs'/f'{identity}.json'


def acquire(value, ws, identity):
    from media import probe
    target = ws/'raw'/f'{identity}.mp4'
    tmp = target.with_suffix('.part.mp4')
    try:
        if str(value).startswith('https://'):
            with urllib.request.urlopen(value, timeout=120) as response, tmp.open('wb') as f:
                if not response.url.startswith('https://'):
                    raise ValueError('Video indirmesi HTTPS kullanmalı.')
                count = 0
                while chunk := response.read(1024*1024):
                    count += len(chunk)
                    if count > 2*1024**3:
                        raise ValueError('Video 2 GB sınırını aşıyor.')
                    f.write(chunk)
        else:
            source = Path(value).resolve()
            if not source.is_file():
                raise ValueError('MCP yerel video yolu bulunamadı: ' + str(source))
            shutil.copy2(source, tmp)
        probe(tmp)
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)
    try:
        sheet_path(ws, identity).parent.mkdir(parents=True, exist_ok=True)
        __import__('media').contact_sheet(target, sheet_path(ws, identity))
    except Exception as exc:  # A missing sheet never blocks a paid download.
        print(f'{identity}: kare tablosu oluşturulamadı ({exc})')
    return str(target)


def sheet_path(ws, identity):
    return ws/'review'/identity/'sheet.png'


def make_sheets(ws):
    """Contact sheets for every downloaded clip that has none yet."""
    import revisions
    from media import contact_sheet
    made = 0
    for _, job in revisions.known(ws).values():
        raw = job.get('raw_video')
        if raw and Path(raw).is_file() and not sheet_path(ws, job['id']).exists():
            contact_sheet(raw, sheet_path(ws, job['id']))
            made += 1
    print(f'{made} kare tablosu oluşturuldu: {ws/"review"}')


def review(ws, identity, verdict, note=None):
    import revisions
    jobs = revisions.known(ws)
    if identity not in jobs:
        raise ValueError('İş bulunamadı: ' + identity)
    path, job = jobs[identity]
    job['review'] = {'verdict': {'onay': 'approved', 'red': 'rejected'}[verdict], 'note': note or '',
                     'at': datetime.now().isoformat(timespec='seconds')}
    write(path, job)
    print(f"{identity}: {'onaylandı' if verdict == 'onay' else 'reddedildi'}"
          + (f' — {note}' if note else '') + ('' if verdict == 'onay' else
          f'. Yeniden denemek için: revize {identity} --not "..."'))


class Pending(Exception):
    """The job waits for another job (a shot it continues from, or a montage's shots)."""


def upload(file, cfg, ws):
    """Upload a local reference once (content-addressed cache) and return the server asset id."""
    from mcp_bridge import call, find_key, lookup
    file = Path(file)
    data = file.read_bytes()
    cache_path = ws/'refs'/'assets.json'
    cache = read(cache_path) if cache_path.exists() else {}
    digest = hashlib.sha256(data).hexdigest()
    if digest in cache:
        return cache[digest]
    mc = cfg['mcp']
    suffix = file.suffix.lower()
    kind = 'audio' if suffix in ('.mp3', '.wav', '.m4a', '.aac') else 'video' if suffix in ('.mp4', '.mov') else 'image'
    result = call(mc, mc.get('upload_tool', 'upload_asset'),
                  {'base64_data': base64.b64encode(data).decode(), 'filename': file.name, 'media_type': kind})
    asset = lookup(result, mc.get('upload_id_path', 'asset_id')) or find_key(result, 'asset_id')
    if not asset:
        raise RuntimeError('Yükleme yanıtında asset_id yok: ' + str(result)[:300])
    cache[digest] = asset
    write(cache_path, cache)
    return asset


def continuity_refs(previous, ws):
    """Last frame (look/pose) and opening audio (narrator timbre) of the shot being continued."""
    import subprocess
    from media import ffmpeg
    folder = ws/'refs'
    folder.mkdir(parents=True, exist_ok=True)
    frame, voice = folder/f"{previous['id']}-last.png", folder/f"{previous['id']}-voice.mp3"
    if not frame.exists():
        subprocess.run([ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-sseof', '-0.25',
                        '-i', previous['raw_video'], '-frames:v', '1', str(frame)], check=True)
    if not voice.exists():
        subprocess.run([ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-i', previous['raw_video'],
                        '-t', '12', '-vn', '-c:a', 'libmp3lame', '-b:a', '192k', str(voice)], check=True)
    return frame, voice


def media_references(job, cfg, ws):
    """Asset ids in prompt order: <Picture 1..n> + continuity frame, <Video 1..n>, <Audio 1> narrator first."""
    images = [resolve_asset(f, ws) for f in job.get('references') or []]
    videos = [resolve_asset(f, ws) for f in job.get('video_references') or []]
    audios = [resolve_asset(f, ws) for f in job.get('audio_references') or []]
    if job.get('continuity_from'):
        previous = read(job_path(ws, job['continuity_from']))
        if previous['status'] not in ('raw_ready', 'done') or not previous.get('raw_video'):
            raise Pending(f"{job['id']}: önce {previous['id']} çekiminin videosu gerekli (süreklilik).")
        frame, voice = continuity_refs(previous, ws)
        images.append(frame)
        if job.get('voice_from_previous'):
            audios.insert(0, voice)
    return ([upload(f, cfg, ws) for f in images], [upload(f, cfg, ws) for f in videos],
            [upload(f, cfg, ws) for f in audios])


def generate(args, cfg, ws):
    from mcp_bridge import call, expand, lookup
    path = job_path(ws, args.id)
    job = read(path)
    mc = cfg['mcp']
    if job.get('role') == 'edit':
        raise ValueError('Bu bir montaj işi: çekimleri üretilir, kendisi render ile birleştirilir.')
    if job['status'] in ['raw_ready', 'done']:
        print('Video zaten mevcut: ' + job['status'])
        return
    if args.poll:
        if not job.get('remote_id') or not mc.get('status_tool'):
            raise ValueError('Sorgulama için remote_id ve status_tool gerekli.')
        tool, template = mc['status_tool'], mc['status_arguments']
    else:
        if job['status'] != 'planned':
            raise ValueError('Önceki isteğin sonucu belirsiz/bekleniyor. --poll veya attach kullanın; otomatik tekrar gönderilmez.')
        tool, template = mc.get('generate_tool'), mc['generate_arguments']
        if not tool:
            raise ValueError('Önce config.json içinde generate_tool ayarlayın.')
        if cfg.get('model_policy') == 'minimax_h3' and tool != 'generate_omni_video':
            raise ValueError('Bu kampanyada yalnızca MiniMax generate_omni_video kullanılabilir.')
    arguments = expand(template, job)
    if not args.poll:
        images, videos, audios = media_references(job, cfg, ws)
        # Per-shot values override the config template (duration, references, a fixed seed).
        for key, value in [('images', images), ('videos', videos), ('audios', audios),
                           ('ref_image_size', images and 'max'),
                           ('duration', job.get('duration_seconds')), ('seed', job.get('seed'))]:
            if value not in (None, [], '') and key in template:
                arguments[key] = value
        job['status'] = 'submitting'
        write(path, job)
    try:
        result = call(mc, tool, arguments)
        # Persist before download, so a failed download never repeats a paid generation.
        job['mcp_result'] = result
        remote = lookup(result, mc.get('remote_id_path'))
        if remote is not None:
            job['remote_id'] = remote
        job['status'] = 'waiting'
        write(path, job)
        remote_status = lookup(result, 'job.status')
        if remote_status in ('failed', 'error', 'cancelled'):
            raise RuntimeError('Uzak video işi tamamlanamadı: ' + str(result))
        artifact = lookup(result, mc.get('result_path'))
        if artifact:
            if mc.get('transport') == 'http' and str(artifact).startswith('/'):
                artifact = urljoin(mc['url'], artifact)
                job['artifact_url'] = artifact
            job['raw_video'] = acquire(artifact, ws, job['id'])
            job['status'] = 'raw_ready'
        job.pop('error', None)
        write(path, job)
    except Exception as exc:
        job['error'] = str(exc)
        write(path, job)
        raise
    print(job['status'])


def shots_ready(job, ws):
    shots = [read(job_path(ws, s)) for s in job['shots']]
    return shots if all(s['status'] in ('raw_ready', 'done') and s.get('raw_video') for s in shots) else None


def assemble_job(job, path, cfg, ws):
    from media import assemble
    shots = shots_ready(job, ws)
    if not shots:
        raise Pending(job['id'] + ': montaj için çekimler henüz hazır değil.')
    clips = [{'path': s['raw_video'], 'start': (s.get('trim') or [None, None])[0],
              'end': (s.get('trim') or [None, None])[1], 'transition': s.get('transition')} for s in shots]
    result = assemble(clips, ws/'raw'/f"{job['id']}.mp4", cfg)
    job.update(raw_video=result['path'], assembled_duration=result['duration'], status='raw_ready')
    write(path, job)


def render_job(args, cfg, ws):
    from media import finish
    path = job_path(ws, args.id)
    job = read(path)
    if job['status'] == 'done':
        print(job['export'])
        return
    if job.get('role') == 'shot':
        raise ValueError('Çekimler tek başına render edilmez; montaj işini render edin: ' + str(job.get('parent')))
    if job.get('role') == 'edit' and job['status'] != 'raw_ready':
        assemble_job(job, path, cfg, ws)
    if job['status'] != 'raw_ready':
        raise ValueError('İşin videosu hazır değil; generate veya attach kullanın.')
    output = ws/'exports'/job['id']
    if output.exists():
        raise ValueError('Çıktı zaten var; kesilen işlemin çıktısını kontrol edin: ' + str(output))
    finish(job['raw_video'], output, cfg, args.srt, args.no_subtitles, job.get('cta'),
           job.get('language'), job.get('voiceover'), hook_text=job.get('hook_text'),
           emphasis=job.get('emphasis') or [], app_name=job.get('app_name'),
           music=job.get('music') and resolve_asset(job['music'], ws))
    (output/'caption.txt').write_text(job['caption'], encoding='utf-8')
    write(output/'job.json', job)
    job.update(status='done', export=str(output))
    write(path, job)
    print(output)


def complete(job):
    # A shot is finished once its footage is downloaded; its montage renders it.
    return job['status'] == 'done' or (job.get('role') == 'shot' and job['status'] == 'raw_ready')


def run_queue(args, cfg, ws):
    from mcp_bridge import lookup
    failures = []
    # Jobs a cleanup retired stay on disk for history but are never worked on.
    jobs = [p for p in sorted((ws/'jobs').glob('*.json'))
            if not complete(read(p)) and read(p).get('status') not in RETIRED]
    # Shots first, so their montage can be assembled in the same pass.
    jobs.sort(key=lambda p: read(p).get('role') == 'edit')
    if getattr(args, 'dry_run', False):
        actions = {'planned': 'üretime gönderilir', 'waiting': 'sunucuda sorgulanır', 'raw_ready': 'render edilir',
                   'submitting': 'sonucu belirsiz, elle kontrol gerekir'}
        for path in jobs[:args.limit]:
            job = read(path)
            action = ('montaj: çekimler hazırsa birleştirilir' if job.get('role') == 'edit' and job['status'] == 'planned'
                      else actions.get(job['status'], job['status']))
            note = f" — {job['revision_note']}" if job.get('revision_note') else ''
            print(f"{job['id']}: {action}{note}")
        if not jobs:
            print('Kuyrukta iş yok.')
        return
    for path in jobs[:args.limit]:
        job = read(path)
        identity = job['id']
        try:
            if job.get('role') == 'edit':
                if job['status'] != 'raw_ready' and not shots_ready(job, ws):
                    print(identity + ': montaj çekimleri bekliyor.')
                    continue
                srt = ws/'raw'/f'{identity}.srt'
                render_job(argparse.Namespace(id=identity, srt=str(srt) if srt.exists() else None,
                                               no_subtitles=False), cfg, ws)
                continue
            cached = job.get('artifact_url') or lookup(job.get('mcp_result', {}), cfg['mcp'].get('result_path'))
            if cached and cfg['mcp'].get('transport') == 'http' and str(cached).startswith('/'):
                cached = urljoin(cfg['mcp']['url'], cached)
            if cached and job['status'] != 'raw_ready':
                job['raw_video'] = acquire(cached, ws, identity)
                job['status'] = 'raw_ready'
                write(path, job)
            if job['status'] == 'planned':
                generate(argparse.Namespace(id=identity, poll=False), cfg, ws)
            elif job['status'] == 'waiting' and job.get('remote_id'):
                generate(argparse.Namespace(id=identity, poll=True), cfg, ws)
            elif job['status'] == 'submitting':
                raise ValueError('İsteğin sonucu belirsiz; MCP tarafında kontrol edip attach kullanın.')
            job = read(path)
            if job['status'] == 'raw_ready' and job.get('role') == 'shot':
                print(identity + ': çekim hazır.')
            elif job['status'] == 'raw_ready':
                srt = ws/'raw'/f'{identity}.srt'
                render_job(argparse.Namespace(id=identity, srt=str(srt) if srt.exists() else None,
                                               no_subtitles=False), cfg, ws)
            else:
                print(identity + ': üretim bekleniyor; run tekrar çalıştırılabilir.')
        except Pending as exc:
            print(exc)
        except Exception as exc:
            failures.append(identity + ': ' + str(exc))
    if failures:
        raise RuntimeError('\n'.join(failures))


def clip_spec(value):
    # 'clip.mp4@1.5-9' trims; '@' keeps Windows drive letters (C:) unambiguous.
    path, _, span = value.partition('@')
    if not Path(path).is_file():
        raise ValueError('Klip bulunamadı: ' + path)
    start, _, end = span.partition('-')
    return {'path': path, 'start': float(start) if start else None, 'end': float(end) if end else None}


def lint(product_path, ws):
    issues = []
    product = read(product_path) if product_path else {}
    for i, s in enumerate(product.get('scripts') or [], 1):
        issues += minimax.lint_script(s, product, i)
    for p in sorted((ws/'jobs').glob('*.json')):
        job = read(p)
        if job['status'] == 'planned' and job.get('prompt'):
            issues += [(level, f"{job['id']}: {msg}") for level, msg in lint_job(job, product or {'name': job.get('app_name')})]
    for level, msg in issues:
        print(('HATA ' if level == 'error' else 'UYARI ') + msg)
    if any(level == 'error' for level, _ in issues):
        raise ValueError('Denetim hatalı; promptları düzeltin.')
    print('Denetim tamam.' if not issues else 'Denetim tamam (uyarılarla).')


def status(ws):
    for p in sorted((ws/'jobs').glob('*.json')):
        job = read(p)
        role = {'shot': f"çekim → {job.get('parent')}", 'edit': f"montaj ({len(job.get('shots', []))} çekim)"}
        print(job['id'], job['status'], role.get(job.get('role'), ''))


def run_all(args, targets):
    """Run each app's queue in turn; with --app all the apps share the one video server fairly."""
    if args.limit < 1 or args.interval < 1 or args.timeout < 1:
        raise ValueError('Limit, interval ve timeout pozitif olmalı.')
    deadline = time.monotonic() + args.timeout
    while True:
        failures = []
        for ws, cfg in targets:
            try:
                with lock(ws):
                    run_queue(args, cfg, ws)
            except Exception as exc:
                failures.append(f"[{cfg['app']['slug']}] {exc}")
        if failures:
            raise RuntimeError('\n'.join(failures))
        pending = any(not complete(j) and j.get('status') not in RETIRED
                      for ws, _ in targets for j in map(read, (ws/'jobs').glob('*.json')))
        if not args.wait or not pending:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError('Bekleme süresi doldu; işler korunuyor. run ile devam edebilirsiniz.')
        time.sleep(min(args.interval, max(0, deadline-time.monotonic())))


def main():
    parser = argparse.ArgumentParser(description='OtoReklam üretim hattı')
    parser.add_argument('--config', default=str(ROOT/'config.json'))
    parser.add_argument('--app', help='Uygulama kısa adı (workspace/apps/<ad>); run/status için "all" da olur')
    sub = parser.add_subparsers(dest='cmd', required=True)
    for name in ['init', 'doctor', 'mcp-tools', 'status', 'apps']:
        sub.add_parser(name)
    a = sub.add_parser('new-app'); a.add_argument('slug'); a.add_argument('--name', required=True)
    sub.add_parser('pano', help='Yayın panosu (pano.html): video, açıklama, hashtag, yayın saati')
    sub.add_parser('teslim', help="Her günün seçili videosunu ve açıklamasını teslim klasörüne koyar")
    a = sub.add_parser('sec', help='Bir günün yayınlanacak videosunu seçer'); a.add_argument('id')
    a = sub.add_parser('sonuc', help='TikTok/Meta CSV raporunu okur, reklamlarla eşleştirir, öneri yazar')
    a.add_argument('csv')
    sub.add_parser('kareler', help='İndirilmiş kliplerin kare tablolarını oluşturur (review/<iş>/sheet.png)')
    a = sub.add_parser('incele', help='Bir klibi onaylar veya reddeder; karar iş dosyasına ve panoya yazılır')
    a.add_argument('id'); a.add_argument('karar', choices=['onay', 'red']); a.add_argument('--not', dest='note')
    a = sub.add_parser('revize', help='Bir çekimi yeniden dener; eskisi korunur')
    a.add_argument('id'); a.add_argument('--not', dest='note', help='Neden yenilendiği (iş dosyasına yazılır)')
    a.add_argument('--ek', help='Prompta eklenecek tek satırlık talimat, ör. "Keep the lips in sync."')
    a.add_argument('--zincir', action='store_true', help='Bu çekimden devam eden çekimleri de yeniler')
    a = sub.add_parser('bol', help='Bir çekimi iki devam eden parçaya böler, ör. 8+8')
    a.add_argument('id'); a.add_argument('sureler', help='ör. 8+8 veya 7+8')
    a.add_argument('--not', dest='note'); a.add_argument('--zincir', action='store_true')
    a.add_argument('--gorsel2', help='2. parçada ne olacağı (varsayılan: promptun zaman çizelgesinden)')
    a = sub.add_parser('analyze'); a.add_argument('source')
    a = sub.add_parser('plan')
    a.add_argument('--product'); a.add_argument('--research')
    a.add_argument('--start', default=datetime.now(timezone(timedelta(hours=3))).date().isoformat())
    a.add_argument('--days', type=int, default=7)
    a = sub.add_parser('generate'); a.add_argument('id'); a.add_argument('--poll', action='store_true')
    a = sub.add_parser('attach'); a.add_argument('id'); a.add_argument('video')
    a = sub.add_parser('run'); a.add_argument('--limit', type=int, default=3)
    a.add_argument('--dry-run', action='store_true', help='Yalnızca hangi işlerin işleneceğini gösterir')
    a.add_argument('--wait', action='store_true')
    a.add_argument('--interval', type=int, default=30)
    a.add_argument('--timeout', type=int, default=3600)
    a = sub.add_parser('strategy')
    a.add_argument('--product'); a.add_argument('--research')
    a.add_argument('--start', default=datetime.now(timezone(timedelta(hours=3))).date().isoformat())
    a.add_argument('--days', type=int, default=7)
    a = sub.add_parser('lint'); a.add_argument('--product')
    a = sub.add_parser('remotion', help='Remotion ile video/görsel üretir (AdVideo, TemplatePromo, PostStill, Carousel)')
    a.add_argument('spec', help='JSON: {"composition", "props", "output"}; örnekler examples/remotion/')
    a.add_argument('--output', help='Spec içindeki çıktı yolunun yerine')
    for name in ['render', 'process', 'edit']:
        a = sub.add_parser(name)
        if name == 'edit':
            a.add_argument('videos', nargs='+', help='Klipler sırayla; kırpma için klip.mp4@1.5-9')
            a.add_argument('--transition', choices=__import__('media').TRANSITIONS)
            a.add_argument('--transition-seconds', type=float)
        else:
            a.add_argument('id' if name == 'render' else 'video')
        group = a.add_mutually_exclusive_group()
        group.add_argument('--srt'); group.add_argument('--no-subtitles', action='store_true')
        if name != 'render':
            a.add_argument('--output', required=True); a.add_argument('--cta')
            a.add_argument('--caption', default='')
            a.add_argument('--language', help='Konuşma/altyazı dili, ör. en veya tr')
            a.add_argument('--script', help='Bilinen seslendirme metni; altyazı yazımı buradan alınır')
            a.add_argument('--hook-text', help='İlk saniyelerde üstte görünen kısa metin kancası')
            a.add_argument('--app-name', help='Bitiş kartında uygulama adı')
            a.add_argument('--music', help='Sesin altında otomatik kısılan fon müziği dosyası')
    args = parser.parse_args()
    if args.cmd == 'init' and not Path(args.config).exists():
        shutil.copy2(ROOT/'config.example.json', args.config)
    cfg = config(args.config)
    if args.cmd == 'init':
        initialize(cfg)
        return
    if args.cmd == 'new-app':
        return new_app(cfg, args.slug, args.name)
    if args.cmd == 'apps':
        for slug in apps(cfg):
            ws = app_dir(cfg, slug)
            jobs = [read(p) for p in (ws/'jobs').glob('*.json')]
            done = sum(j['status'] == 'done' for j in jobs)
            print(f"{slug:16} {read(ws/'app.json')['name']:20} {len(jobs)} iş, {done} tamam")
        return
    if args.cmd in ('run', 'status') and args.app == 'all':
        targets = [open_app(cfg, slug) for slug in apps(cfg)]
    elif args.cmd in ('doctor', 'mcp-tools') or (args.cmd in ('process', 'edit', 'remotion') and not args.app):
        targets = [(Path(cfg['workspace']), cfg)]  # No app needed; process/edit/remotion take --app for its icon.
    else:
        targets = [open_app(cfg, args.app)]
    if args.cmd == 'run':
        return run_all(args, targets)
    if args.cmd == 'status':
        for ws, cfg in targets:
            print(f"[{cfg['app']['slug']}]")
            status(ws)
        return
    ws, cfg = targets[0]
    if args.cmd in ('plan', 'strategy', 'lint'):
        args.product = app_file(ws, cfg, args.product, 'product') if args.product or cfg.get('app') else None
    if args.cmd in ('plan', 'strategy'):
        args.research = app_file(ws, cfg, args.research, 'research')
    if args.cmd in ('revize', 'bol'):
        import revisions
        brand = (cfg.get('app') or {}).get('name')
        with lock(ws):
            if args.cmd == 'revize':
                revisions.revise(ws, args.id, brand, args.note, args.ek, args.zincir)
            else:
                durations = [int(x) for x in args.sureler.split('+')]
                revisions.split(ws, args.id, durations, brand, args.note, args.zincir, args.gorsel2)
        return
    if args.cmd == 'sonuc':
        __import__('results').import_results(ws, args.csv, cfg)
        __import__('delivery').board(ws, cfg)
        return
    if args.cmd in ('kareler', 'incele'):
        if args.cmd == 'kareler':
            make_sheets(ws)
        else:
            review(ws, args.id, args.karar, args.note)
        __import__('delivery').board(ws, cfg)
        return
    if args.cmd in ('pano', 'teslim', 'sec'):
        import delivery
        if args.cmd == 'sec':
            delivery.select(ws, args.id)
        elif args.cmd == 'teslim':
            delivery.deliver(ws, cfg)
        delivery.board(ws, cfg)  # The board always reflects the latest selection and delivery.
        return
    if args.cmd == 'doctor':
        from media import ffmpeg
        import subprocess
        import importlib.metadata
        for package in ['imageio-ffmpeg', 'faster-whisper', 'mcp']:
            print(package + ': ' + importlib.metadata.version(package))
        p = subprocess.run([ffmpeg(), '-hide_banner', '-filters'], capture_output=True, text=True)
        if p.returncode or ' ass ' not in p.stdout:
            raise RuntimeError('FFmpeg ASS filtresi yok.')
        import faster_whisper
        print('FFmpeg + ASS hazır: ' + ffmpeg())
        print('Whisper modeli ilk transkripsiyonda indirilir. MCP: ' + ('ayarlı' if cfg['mcp'].get('generate_tool') else 'bağlantı bekliyor'))
    elif args.cmd == 'analyze':
        analyze(args.source, ws)
    elif args.cmd == 'mcp-tools':
        from mcp_bridge import call
        result = call(cfg['mcp'])
        write(ws/'mcp-tools.json', result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.cmd == 'strategy':
        import strategy
        strategy.build(read(args.product), read(args.research), args.start, args.days, ws)
    elif args.cmd == 'lint':
        lint(args.product, ws)
    elif args.cmd == 'remotion':
        import render
        for path in render.render_spec(args.spec, cfg, args.output):
            print(path)
    elif args.cmd in ('process', 'edit'):
        from media import assemble, finish
        extras = dict(hook_text=args.hook_text, music=args.music,
                      app_name=args.app_name or (cfg.get('app') or {}).get('name'))
        if args.cmd == 'edit':
            if args.transition:
                cfg['edit'] = {**cfg.get('edit', {}), 'transition': args.transition}
            if args.transition_seconds:
                cfg['edit'] = {**cfg.get('edit', {}), 'transition_seconds': args.transition_seconds}
            target = Path(args.output).resolve()
            master = target.parent/(target.name + '.master.mp4')
            assemble([clip_spec(v) for v in args.videos], master, cfg)
            try:
                output = finish(master, target, cfg, args.srt, args.no_subtitles, args.cta,
                                args.language, args.script, **extras)
            finally:
                master.unlink(missing_ok=True)
        else:
            output = finish(args.video, args.output, cfg, args.srt, args.no_subtitles, args.cta,
                            args.language, args.script, **extras)
        (output/'caption.txt').write_text(args.caption, encoding='utf-8')
        print(output)
    else:
        with lock(ws):
            if args.cmd == 'plan':
                plan(args.product, args.research, args.start, args.days, ws)
            elif args.cmd == 'generate':
                generate(args, cfg, ws)
            elif args.cmd == 'render':
                render_job(args, cfg, ws)
            elif args.cmd == 'attach':
                path = job_path(ws, args.id)
                job = read(path)
                if job['status'] == 'done':
                    raise ValueError('Tamamlanmış işe video eklenemez.')
                job['raw_video'] = acquire(args.video, ws, job['id'])
                job['status'] = 'raw_ready'
                write(path, job)
                print('raw_ready')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('HATA: ' + str(exc), file=sys.stderr)
        sys.exit(1)
