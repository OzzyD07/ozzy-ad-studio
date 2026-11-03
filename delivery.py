"""Publishing side of an app: pick one video per day, build the delivery folder and the HTML board.

The delivery folder holds what gets posted (NN_date/video.mp4 + aciklama.txt). The board
(pano.html) shows every planned day with its video, caption, hashtags and publish slot, and is
regenerated from the job files, so it never drifts from what is actually on disk.
"""
import hashlib
import html
import json
import os
import re
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent
HIDDEN = {'removed_by_cleanup', 'superseded'}
IN_PROGRESS = {'submitting', 'waiting', 'raw_ready'}
DAYS_TR = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz']
MONTHS_TR = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara']


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, data):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def truthy(value):
    # Older jobs stored the flag as the string "True".
    return value is True or str(value).lower() == 'true'


# --- Time zones -------------------------------------------------------------------------------
# Windows Python ships without a time-zone database; the tzdata package fixes that. Without it,
# these rules cover the usual targets: (standard UTC offset in hours, daylight-saving rule).
FALLBACK_ZONES = {
    'UTC': (0, None), 'Europe/Istanbul': (3, None),
    'Europe/London': (0, 'eu'), 'Europe/Dublin': (0, 'eu'), 'Europe/Lisbon': (0, 'eu'),
    'Europe/Berlin': (1, 'eu'), 'Europe/Paris': (1, 'eu'), 'Europe/Madrid': (1, 'eu'),
    'Europe/Rome': (1, 'eu'), 'Europe/Amsterdam': (1, 'eu'),
    'America/New_York': (-5, 'us'), 'America/Chicago': (-6, 'us'), 'America/Denver': (-7, 'us'),
    'America/Los_Angeles': (-8, 'us'), 'America/Toronto': (-5, 'us'),
}


def nth_sunday(year, month, n):
    first = date(year, month, 1)
    first_sunday = first + timedelta(days=(6 - first.weekday()) % 7)
    if n > 0:
        return first_sunday + timedelta(weeks=n - 1)
    last = date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - 6) % 7)


def utc_offset(zone, local):
    """UTC offset of a wall-clock time in a fallback zone."""
    base, rule = FALLBACK_ZONES[zone]
    if rule == 'us':  # 2nd Sunday of March 02:00 → 1st Sunday of November 02:00, local time.
        start = datetime.combine(nth_sunday(local.year, 3, 2), datetime.min.time()) + timedelta(hours=2)
        end = datetime.combine(nth_sunday(local.year, 11, 1), datetime.min.time()) + timedelta(hours=2)
        return timedelta(hours=base + (start <= local < end))
    if rule == 'eu':  # last Sunday of March → last Sunday of October, 01:00 UTC.
        utc = local - timedelta(hours=base)
        start = datetime.combine(nth_sunday(local.year, 3, -1), datetime.min.time()) + timedelta(hours=1)
        end = datetime.combine(nth_sunday(local.year, 10, -1), datetime.min.time()) + timedelta(hours=1)
        return timedelta(hours=base + (start <= utc < end))
    return timedelta(hours=base)


def convert(day, clock, source, target):
    """Wall-clock time `clock` on `day` in `source` → naive datetime in `target`."""
    local = datetime.combine(date.fromisoformat(day), datetime.strptime(clock, '%H:%M').time())
    try:
        from zoneinfo import ZoneInfo
        return local.replace(tzinfo=ZoneInfo(source)).astimezone(ZoneInfo(target)).replace(tzinfo=None)
    except Exception:
        if source not in FALLBACK_ZONES or target not in FALLBACK_ZONES:
            raise ValueError(f'Saat dilimi bilinmiyor: {source} / {target} (pip install tzdata ile tüm dilimler gelir).')
        utc = local - utc_offset(source, local)
        guess = utc + utc_offset(target, utc + timedelta(hours=FALLBACK_ZONES[target][0]))
        return guess


def slot(day, cfg, name=None):
    """(target-market label, local publish datetime) or None when the app has no publish rule.
    A named slot (two posts a day) uses its own time from the calendar settings, in the same time zone."""
    import takvim
    rule = (cfg.get('app') or {}).get('publish') or {}
    clock = (takvim.slot_time(name, cfg) if name else None) or rule.get('time')
    if not clock:
        return None
    source = rule.get('timezone', 'Europe/Istanbul')
    target = rule.get('local_timezone', 'Europe/Istanbul')
    return f"{clock} {rule.get('label', source)}", convert(day, clock, source, target)


def tr_date(value, with_time=False):
    text = f'{value.day} {MONTHS_TR[value.month - 1]} {DAYS_TR[value.weekday()]}'
    return text + (f' {value:%H.%M}' if with_time else '')


# --- Jobs and selection -----------------------------------------------------------------------
def job_files(ws):
    """Ad jobs of the plan and of later revision waves (shots are parts, not ads)."""
    files = sorted((ws/'jobs').glob('*.json')) + sorted((ws/'revisions').glob('*/jobs/*.json'))
    return [f for f in files if not f.name.endswith('.tmp')]


def ad_jobs(ws):
    jobs = []
    for f in job_files(ws):
        job = read(f)
        if job.get('role') == 'shot' or job.get('status') in HIDDEN or not job.get('date'):
            continue
        jobs.append({**job, '_file': str(f)})
    return jobs


def media_of(job):
    """Finished files that get posted: [video.mp4], [post.png] or the carousel's [01.png, 02.png, …]."""
    export = job.get('export')
    if not export:
        return []
    path = Path(export)
    if path.is_file():
        return [path]
    if not path.is_dir():
        return []
    for name in ('video.mp4', 'post.png'):
        if (path/name).is_file():
            return [path/name]
    slides = sorted(path.glob('[0-9][0-9].png'))
    return slides or sorted(path.glob('*.mp4'))[:1]


def video_of(job):
    """The finished video of a job, if it exists on disk."""
    found = [m for m in media_of(job) if m.suffix == '.mp4']
    return found[0] if found else None


def slot_key(job):
    return job['date'] + (f" {job['slot']}" if job.get('slot') else '')


def days(ws, cfg=None):
    """'date[ slot]' → {'date', 'slot', 'options': [...], 'selected': job or None}, in publishing order."""
    import takvim
    order = [s['name'] for s in takvim.settings(cfg)['slots']]
    grouped = {}
    for job in ad_jobs(ws):
        grouped.setdefault(slot_key(job), []).append(job)
    rank = lambda key: (key.split(' ')[0], order.index(key.split(' ', 1)[1]) if ' ' in key and key.split(' ', 1)[1] in order else 99, key)
    result = {}
    for key in sorted(grouped, key=rank):
        options = sorted(grouped[key], key=lambda j: (j.get('variant') or '', j['id']))
        chosen = [j for j in options if truthy(j.get('selected_for_publication')) and media_of(j)]
        result[key] = {'date': options[0]['date'], 'slot': options[0].get('slot'), 'options': options,
                       'selected': chosen[-1] if chosen else None}
    return result


def select(ws, identity):
    """Mark one finished ad as the day's publication; the day's other ads are unmarked."""
    target = next((j for j in ad_jobs(ws) if j['id'] == identity), None)
    if not target:
        raise ValueError('Reklam işi bulunamadı (çekimler seçilemez, montaj işini seçin): ' + identity)
    if not media_of(target):
        raise ValueError(f'{identity}: bitmiş çıktı yok; önce render edin.')
    for job in ad_jobs(ws):
        if slot_key(job) == slot_key(target):
            data = read(job['_file'])
            data['selected_for_publication'] = job['id'] == identity
            write(job['_file'], data)
    print(f"{slot_key(target)}: {identity} yayın için seçildi.")


def caption_text(job, product):
    """Caption + hashtags + store links, exactly as it is pasted into the platform."""
    text = (job.get('caption') or '').strip()
    links = [f'{label}: {product[key]}' for label, key in [('Android', 'url'), ('iOS', 'ios_url')]
             if product.get(key) and product[key] not in text]
    return '\n'.join([text, *links]).strip()


# Platform copy. Caption links are not clickable on TikTok or Instagram, so they point to the bio;
# YouTube descriptions keep the store links. TikTok ad text allows 100 characters and no hashtags.
PLATFORMS = {
    'tiktok': ('TikTok', 4000),
    'instagram': ('Instagram Reels', 2200),
    'youtube': ('YouTube Shorts', 5000),
    'ad': ('Reklam metni', 100),
}


IMAGE_LABELS = {'tiktok': 'TikTok foto', 'instagram': 'Instagram gönderi'}


def caption_parts(job):
    text = (job.get('caption') or '').strip()
    lines = [l for l in text.split('\n') if not re.match(r'^(Android|iOS):\s*https?://', l.strip())]
    body = '\n'.join(lines)
    tags = re.findall(r'#\w+', body)
    plain = re.sub(r'\s*#\w+', '', body).strip()
    return plain, tags


def platform_captions(job, product):
    """{platform: (label, text, warnings)}; a job's own `captions` override any generated text."""
    plain, tags = caption_parts(job)
    hashtags = ' '.join(tags)
    links = '\n'.join(f'{label}: {product[key]}' for label, key in [('Android', 'url'), ('iOS', 'ios_url')]
                      if product.get(key))
    title = re.split(r'(?<=[.!?])\s+', plain)[0] if plain else (job.get('angle') or '')
    title = (title if len(title) <= 90 else title[:87].rstrip() + '...') + ' #Shorts'
    ad_text = plain if len(plain) <= 100 else re.split(r'(?<=[.!?])\s+', plain)[0][:100]
    texts = {
        'tiktok': f'{plain} {hashtags}\n\nApp link in bio.'.strip(),
        'instagram': f'{plain}\n\nApp link in bio.\n\n{hashtags}'.strip(),
        'youtube': f'{title}\n\n{plain}\n\n{links}\n\n{hashtags} #Shorts'.strip(),
        'ad': ad_text,
        **(job.get('captions') or {}),
    }
    out = {}
    image = job.get('format') in ('image_post', 'carousel')
    for key, (label, limit) in PLATFORMS.items():
        if image and key == 'youtube':
            continue  # Shorts is video-only; posts and carousels go to the Instagram feed and TikTok photo mode.
        if image:
            label = IMAGE_LABELS.get(key, label)
        text = texts[key]
        warnings = [f'{len(text)} karakter; sınır {limit}.'] if len(text) > limit else []
        if key == 'instagram' and len(tags) > 30:
            warnings.append('Instagram en fazla 30 hashtag kabul eder.')
        if key == 'ad' and '#' in text:
            warnings.append('Reklam metninde hashtag kullanmayın.')
        out[key] = (label, text, warnings)
    return out


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def delivery_dir(cfg):
    app = cfg.get('app') or {}
    value = app.get('delivery_dir') or f"YAYINA-HAZIR/{app.get('slug', 'app')}"
    path = Path(value)
    return path if path.is_absolute() else ROOT/path


def product_of(ws, cfg):
    name = (cfg.get('app') or {}).get('product')
    return read(ws/name) if name and (ws/name).is_file() else {}


def deliver(ws, cfg):
    """Copy each slot's selected media (video, post or carousel slides) and its caption into NN_date[_slot]
    folders. Never deletes."""
    target = delivery_dir(cfg)
    target.mkdir(parents=True, exist_ok=True)
    product = product_of(ws, cfg)
    plan = days(ws, cfg)
    manifest, missing = [], []
    for n, (day, info) in enumerate(plan.items(), 1):
        job = info['selected']
        if not job:
            missing.append(day)
            continue
        folder = target/(f"{n:02}_{info['date']}" + (f"_{info['slot']}" if info['slot'] else ''))
        folder.mkdir(exist_ok=True)
        files = []
        for source in media_of(job):
            # Carousel slides keep their order names; a single video/post gets the usual name.
            dest = folder/source.name
            if source.resolve() != dest.resolve() and (not dest.exists() or digest(source) != digest(dest)):
                tmp = dest.with_name(dest.name + '.part')
                shutil.copy2(source, tmp)
                tmp.replace(dest)
                print(f'{day}: {source.name} kopyalandı ({job["id"]})')
            files.append(dest)
        video = files[0]
        caption = folder/'aciklama.txt'
        text = caption_text(job, product)
        if not caption.exists() or caption.read_text(encoding='utf-8') != text:
            caption.write_text(text, encoding='utf-8')
        for key, (label, copy, warnings) in platform_captions(job, product).items():
            path = folder/f'aciklama-{key}.txt'
            if not path.exists() or path.read_text(encoding='utf-8') != copy:
                path.write_text(copy, encoding='utf-8')
            for w in warnings:
                print(f'UYARI {day} {label}: {w}')
        when = slot(info['date'], cfg, info['slot'])
        manifest.append({'date': info['date'], 'slot': info['slot'], 'format': job.get('format', 'ai_video'),
                         'id': job['id'], 'variant': job.get('variant'), 'folder': folder.name,
                         'files': [f.name for f in files], 'sha256': digest(video),
                         'publish_local': when[1].isoformat(timespec='minutes') if when else None})
    stale = sorted(d.name for d in target.iterdir() if d.is_dir() and d.name not in {m['folder'] for m in manifest})
    write(target/'teslim.json', {'app': (cfg.get('app') or {}).get('slug'), 'items': manifest,
                                 'updated': datetime.now().isoformat(timespec='seconds')})
    print(f'{len(manifest)} gün teslim klasöründe: {target}')
    if missing:
        print('Seçili/bitmiş video olmayan günler: ' + ', '.join(missing))
    if stale:
        print('Planda karşılığı olmayan eski klasörler (silinmedi): ' + ', '.join(stale))
    return manifest


# --- Board ------------------------------------------------------------------------------------
FORMAT_LABELS = {'ai_video': 'AI video', 'template_video': 'Şablon video', 'image_post': 'Görsel post',
                 'carousel': 'Carousel'}


def media_html(files, base):
    """Video player, a single post image, or the carousel's slides side by side."""
    if not files:
        return '<div class="novideo">Çıktı henüz yok</div>'
    if files[0].suffix == '.mp4':
        return f'<video controls preload="metadata" playsinline src="{href(files[0], base)}"></video>'
    if len(files) == 1:
        return f'<a href="{href(files[0], base)}"><img class="post" loading="lazy" src="{href(files[0], base)}" alt="post"></a>'
    return ('<div class="slides">' + ''.join(
        f'<a href="{href(f, base)}"><img loading="lazy" src="{href(f, base)}" alt="slayt {k}"></a>'
        for k, f in enumerate(files, 1)) + '</div>')


def day_state(info):
    if info['selected']:
        return 'ready', 'Yayına hazır'
    if any(media_of(j) for j in info['options']):
        return 'choose', 'Seçim bekliyor'
    if any(j.get('status') in IN_PROGRESS for j in info['options']):
        return 'producing', 'Üretimde'
    return 'planned', 'Planlandı'


def href(path, base):
    rel = os.path.relpath(path, base).replace(os.sep, '/')
    return quote(rel, safe='/._-')


def hashtag_html(text):
    return re.sub(r'(#[\w]+)', r'<span class="tag">\1</span>', html.escape(text))


VERDICTS = {'approved': ('✓ onaylandı', 'ok'), 'rejected': ('✗ reddedildi', 'bad')}


def review_section(ws, slug, base):
    """Downloaded clips with their contact sheets: the ones still waiting for a verdict come first."""
    import revisions
    pending, done = [], []
    for _, job in sorted(revisions.known(ws).items()):
        job = job[1]
        raw = job.get('raw_video')
        if not job.get('prompt') or job.get('status') in HIDDEN or not raw or not Path(raw).is_file():
            continue
        sheet = ws/'review'/job['id']/'sheet.png'
        verdict = (job.get('review') or {}).get('verdict')
        label, cls = VERDICTS.get(verdict, ('inceleme bekliyor', 'wait'))
        note = (job.get('review') or {}).get('note') or job.get('revision_note') or ''
        run = rf'.\run.ps1 --app {slug} incele {job["id"]}'
        commands = ''.join(
            f'<button class="link" data-copy="{html.escape(f"{run} {k}{extra}")}">{t}</button> '
            for k, t, extra in [('onay', 'onay komutu', ''), ('red', 'red komutu', ' --not "..."')])
        item = (f'<figure class="sheet">'
                + (f'<a href="{href(raw, base)}"><img loading="lazy" src="{href(sheet, base)}" alt="{html.escape(job["id"])} kareleri"></a>'
                   if sheet.exists() else f'<a class="nosheet" href="{href(raw, base)}">Kare tablosu yok (kareler komutu)</a>')
                + f'<figcaption><code>{html.escape(job["id"])}</code> <span class="verdict {cls}">{label}</span>'
                + (f'<br><span class="muted">{html.escape(note)}</span>' if note else '')
                + f'<br>{commands}</figcaption></figure>')
        (done if verdict else pending).append(item)
    if not pending and not done:
        return ''
    return (f'<section class="review"><h2>İnceleme bekleyen klipler ({len(pending)})</h2>'
            '<p class="muted">Logo, yazı, ekran, cihaz ve şişe arayın. Karelere tıklayınca ham video açılır.</p>'
            f'<div class="sheets">{"".join(pending) or "<p>Bekleyen klip yok.</p>"}</div>'
            + (f'<details><summary>İncelenmiş ({len(done)})</summary><div class="sheets">{"".join(done)}</div></details>'
               if done else '') + '</section>')


def result_html(job):
    if not job.get('results'):
        return ''
    from results import percent
    r = job['results'][-1]
    cpi = f" · yükleme başı {r['cpi']:.2f}" if r.get('cpi') is not None else ''
    shown = f'{int(r.get("impressions") or 0):,}'.replace(',', '.')
    return (f'<div class="result {html.escape(r["advice"])}"><strong>Sonuç</strong> ({html.escape(r["source"])}): '
            f'{shown} gösterim · hook {percent(r.get("hook_rate"))} · tutma {percent(r.get("hold_rate"))} · '
            f'CTR {percent(r.get("ctr"))}{cpi}<br>{html.escape(r["advice_text"])}</div>')


def captions_html(job, product, caption):
    """Tabbed copy: the store-link caption plus one text per platform."""
    variants = [('all', 'Genel', caption, [])] + [(k, *v) for k, v in platform_captions(job, product).items()]
    tabs = ''.join(f'<button class="tab{" on" if i == 0 else ""}" data-tab="{k}">{html.escape(label)}</button>'
                   for i, (k, label, _, _) in enumerate(variants))
    panes = ''.join(
        f'<div class="pane" data-pane="{k}"{"" if i == 0 else " hidden"}><pre>{hashtag_html(text)}</pre>'
        + ''.join(f'<p class="warn">{html.escape(w)}</p>' for w in warnings)
        + f'<button class="copy" data-copy="{html.escape(text)}">{html.escape(label)} metnini kopyala</button></div>'
        for i, (k, label, text, warnings) in enumerate(variants))
    return f'<div class="caption"><div class="tabs">{tabs}</div>{panes}</div>'


def board(ws, cfg, out=None):
    app = cfg.get('app') or {}
    out = Path(out or ws/'pano.html')
    product = product_of(ws, cfg)
    plan = days(ws, cfg)
    slug = app.get('slug', 'app')
    cards, counts = [], {'ready': 0, 'choose': 0, 'producing': 0, 'planned': 0}
    for n, (day, info) in enumerate(plan.items(), 1):
        state, label = day_state(info)
        counts[state] += 1
        job = info['selected'] or next((j for j in info['options'] if media_of(j)), info['options'][0])
        files = media_of(job)
        when = slot(info['date'], cfg, info['slot'])
        caption = caption_text(job, product)
        target_day = date.fromisoformat(info['date'])
        options = []
        for o in info['options']:
            mark = '★ seçili' if o is info['selected'] else ('hazır' if media_of(o) else o.get('status', ''))
            if (o.get('review') or {}).get('verdict'):
                mark += ' · ' + VERDICTS[o['review']['verdict']][0]
            command = f".\\run.ps1 --app {slug} sec {o['id']}"
            options.append(
                f'<li><code>{html.escape(o["id"])}</code> <span class="muted">{html.escape(mark)}</span>'
                + (f' <button class="link" data-copy="{html.escape(command)}">seç komutu</button>'
                   if media_of(o) and o is not info['selected'] else '') + '</li>')
        media = media_html(files, out.parent)
        kind = FORMAT_LABELS.get(job.get('format', 'ai_video'), '')
        cards.append(f'''
<article class="card" data-state="{state}" data-day="{day}">
  {media}
  <div class="body">
    <div class="top">
      <span class="num">{n:02}</span>
      <span class="badge {state}">{label}</span>
      <span class="kind">{html.escape(kind)}{f" · {html.escape(info['slot'])}" if info['slot'] else ''}</span>
    </div>
    <h2>{html.escape(job.get('angle') or job['id'])}</h2>
    <p class="when"><strong>{tr_date(target_day)}</strong> hedef gün{f" · {html.escape(when[0])}" if when else ""}
      {f'<br>Türkiye: <strong>{tr_date(when[1], True)}</strong>' if when else ''}</p>
    {f'<p class="hook">Ekran metni: “{html.escape(job["hook_text"])}”</p>' if job.get('hook_text') else ''}
    {captions_html(job, product, caption)}
    <p class="meta">CTA: {html.escape(job.get('cta') or '-')}{f" · Varyant {html.escape(job['variant'])}" if job.get('variant') else ''}</p>
    {result_html(job)}
    <details><summary>Seçenekler ({len(info['options'])})</summary><ul>{''.join(options)}</ul></details>
    <div class="checks">
      <label><input type="checkbox" data-key="scheduled"> Zamanlandı</label>
      <label><input type="checkbox" data-key="published"> Yayınlandı</label>
    </div>
    <textarea data-key="note" rows="2" placeholder="Not (bu tarayıcıda saklanır)"></textarea>
  </div>
</article>''')
    generated = datetime.now().strftime('%d.%m.%Y %H.%M')
    total = len(plan)
    page = PAGE.format(
        title=html.escape(f"{app.get('name', slug)} yayın panosu"), name=html.escape(app.get('name', slug)),
        generated=generated, total=total, ready=counts['ready'], choose=counts['choose'],
        producing=counts['producing'], planned=counts['planned'], slug=html.escape(slug),
        delivery=html.escape(str(delivery_dir(cfg))), cards=''.join(cards) or '<p>Planlı reklam yok.</p>',
        review=review_section(ws, slug, out.parent))
    out.write_text(page, encoding='utf-8')
    print(f'Pano: {out}')
    return out


PAGE = '''<!doctype html>
<html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ --bg:#f6f5f2; --card:#fff; --ink:#1d1d1f; --muted:#6b6b70; --line:#e4e2dd; --accent:#3d5afe;
  --ready:#1b873f; --choose:#b26a00; --producing:#3d5afe; --planned:#8a8a8f; --tag:#3d5afe; --code:#f0efeb; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#141416; --card:#1f1f23; --ink:#f2f2f4;
  --muted:#a0a0a8; --line:#2f2f35; --accent:#8c9eff; --ready:#4cc777; --choose:#f0a33a; --producing:#8c9eff;
  --planned:#8a8a93; --tag:#8c9eff; --code:#2a2a30; }} }}
:root[data-theme="dark"] {{ --bg:#141416; --card:#1f1f23; --ink:#f2f2f4; --muted:#a0a0a8; --line:#2f2f35;
  --accent:#8c9eff; --ready:#4cc777; --choose:#f0a33a; --producing:#8c9eff; --planned:#8a8a93; --tag:#8c9eff; --code:#2a2a30; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif; }}
header {{ padding:24px 16px 8px; max-width:1400px; margin:auto; }}
h1 {{ margin:0 0 4px; font-size:24px; }}
.muted {{ color:var(--muted); }}
.stats {{ display:flex; flex-wrap:wrap; gap:8px; margin:16px 0 8px; }}
.stats button {{ border:1px solid var(--line); background:var(--card); color:var(--ink); border-radius:999px;
  padding:6px 14px; font:inherit; cursor:pointer; }}
.stats button.on {{ border-color:var(--accent); box-shadow:inset 0 0 0 1px var(--accent); }}
main {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); gap:16px; padding:8px 16px 40px;
  max-width:1400px; margin:auto; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; overflow:hidden; display:flex;
  flex-direction:column; }}
.card.done {{ opacity:.6; }}
video, .novideo {{ width:100%; aspect-ratio:9/16; max-height:440px; background:#000; display:block; object-fit:contain; }}
.novideo {{ display:flex; align-items:center; justify-content:center; color:#aaa; }}
img.post {{ width:100%; max-height:440px; object-fit:contain; background:#000; display:block; }}
.slides {{ display:flex; gap:4px; overflow-x:auto; background:#000; max-height:440px; scroll-snap-type:x mandatory; }}
.slides img {{ height:440px; max-height:440px; flex:0 0 auto; scroll-snap-align:start; }}
.kind {{ font-size:12px; color:#888; margin-left:auto; }}
.body {{ padding:14px; display:flex; flex-direction:column; gap:8px; }}
.top {{ display:flex; justify-content:space-between; align-items:center; }}
.num {{ font-weight:700; color:var(--muted); }}
.badge {{ font-size:12px; font-weight:600; padding:3px 10px; border-radius:999px; color:#fff; }}
.badge.ready {{ background:var(--ready); }} .badge.choose {{ background:var(--choose); }}
.badge.producing {{ background:var(--producing); }} .badge.planned {{ background:var(--planned); }}
h2 {{ margin:0; font-size:17px; }}
.when, .hook, .meta {{ margin:0; font-size:14px; }}
.hook {{ color:var(--muted); }}
.caption pre {{ white-space:pre-wrap; word-break:break-word; background:var(--code); border-radius:10px; padding:10px;
  margin:0 0 6px; font:13px/1.45 ui-monospace,Consolas,monospace; }}
.tag {{ color:var(--tag); font-weight:600; }}
button.copy {{ width:100%; border:0; background:var(--accent); color:#fff; border-radius:10px; padding:9px; font:inherit;
  font-weight:600; cursor:pointer; }}
button.link {{ border:0; background:none; color:var(--accent); cursor:pointer; padding:0; font:inherit; font-size:13px; }}
details ul {{ margin:6px 0 0; padding-left:18px; font-size:13px; }}
code {{ font-size:12px; background:var(--code); padding:1px 5px; border-radius:5px; }}
.checks {{ display:flex; gap:16px; font-size:14px; }}
textarea {{ width:100%; border:1px solid var(--line); border-radius:8px; background:var(--bg); color:var(--ink);
  padding:8px; font:inherit; font-size:14px; resize:vertical; }}
.review {{ max-width:1400px; margin:8px auto 0; padding:0 16px; }}
.review h2 {{ font-size:18px; margin:12px 0 2px; }}
.sheets {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:12px; margin:10px 0; }}
.sheet {{ margin:0; background:var(--card); border:1px solid var(--line); border-radius:12px; padding:8px; font-size:13px; }}
.sheet img {{ width:100%; border-radius:8px; display:block; }}
.nosheet {{ display:block; padding:30px 8px; text-align:center; color:var(--muted); }}
.verdict {{ font-weight:600; }} .verdict.ok {{ color:var(--ready); }} .verdict.bad {{ color:#d93025; }}
.verdict.wait {{ color:var(--choose); }}
.result {{ font-size:13px; border-radius:10px; padding:8px 10px; background:var(--code); border-left:4px solid var(--planned); }}
.result.scale {{ border-color:var(--ready); }} .result.hook, .result.hold {{ border-color:#d93025; }}
.result.cta {{ border-color:var(--choose); }}
.tabs {{ display:flex; flex-wrap:wrap; gap:4px; margin-bottom:6px; }}
.tab {{ border:1px solid var(--line); background:none; color:var(--muted); border-radius:999px; padding:2px 10px;
  font:inherit; font-size:12px; cursor:pointer; }}
.tab.on {{ color:var(--ink); border-color:var(--accent); }}
.warn {{ color:#d93025; font-size:12px; margin:0 0 6px; }}
.toast {{ position:fixed; bottom:20px; left:50%; transform:translateX(-50%); background:var(--ink); color:var(--bg);
  padding:8px 16px; border-radius:999px; opacity:0; transition:opacity .2s; pointer-events:none; }}
.toast.show {{ opacity:1; }}
</style></head>
<body>
<header>
  <h1>{name} yayın panosu</h1>
  <div class="muted">{total} gönderi · oluşturuldu {generated} · teslim klasörü: {delivery}</div>
  <div class="stats" role="group" aria-label="Filtre">
    <button class="on" data-filter="all">Tümü {total}</button>
    <button data-filter="ready">Yayına hazır {ready}</button>
    <button data-filter="choose">Seçim bekliyor {choose}</button>
    <button data-filter="producing">Üretimde {producing}</button>
    <button data-filter="planned">Planlandı {planned}</button>
    <button data-filter="todo">Yayınlanmayanlar</button>
  </div>
  <div class="muted">Kutucuklar ve notlar yalnızca bu tarayıcıda saklanır. Pano yenilemek için: <code>.\\run.ps1 --app {slug} pano</code></div>
</header>
{review}
<main>{cards}</main>
<div class="toast" id="toast">Kopyalandı</div>
<script>
const app = "{slug}";
const store = {{
  get(k) {{ try {{ return localStorage.getItem(k); }} catch (e) {{ return null; }} }},
  set(k, v) {{ try {{ localStorage.setItem(k, v); }} catch (e) {{}} }}
}};
function toast(text) {{ const t = document.getElementById('toast'); t.textContent = text; t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 1400); }}
async function copy(text) {{
  try {{ await navigator.clipboard.writeText(text); }}
  catch (e) {{ const a = document.createElement('textarea'); a.value = text; document.body.appendChild(a); a.select();
    document.execCommand('copy'); a.remove(); }}
  toast('Kopyalandı');
}}
document.querySelectorAll('[data-copy]').forEach(b => b.addEventListener('click', () => copy(b.dataset.copy)));
document.querySelectorAll('.card').forEach(card => {{
  const key = k => `pano:${{app}}:${{card.dataset.day}}:${{k}}`;
  const sync = () => card.classList.toggle('done', card.querySelector('[data-key=published]').checked);
  card.querySelectorAll('input[data-key]').forEach(i => {{
    i.checked = store.get(key(i.dataset.key)) === '1';
    i.addEventListener('change', () => {{ store.set(key(i.dataset.key), i.checked ? '1' : '0'); sync(); }});
  }});
  const note = card.querySelector('textarea');
  note.value = store.get(key('note')) || '';
  note.addEventListener('input', () => store.set(key('note'), note.value));
  sync();
}});
document.querySelectorAll('.caption').forEach(box => box.querySelectorAll('.tab').forEach(tab =>
  tab.addEventListener('click', () => {{
    box.querySelectorAll('.tab').forEach(t => t.classList.toggle('on', t === tab));
    box.querySelectorAll('.pane').forEach(p => p.hidden = p.dataset.pane !== tab.dataset.tab);
  }})));
document.querySelectorAll('[data-filter]').forEach(b => b.addEventListener('click', () => {{
  document.querySelectorAll('[data-filter]').forEach(x => x.classList.toggle('on', x === b));
  document.querySelectorAll('.card').forEach(c => {{
    const f = b.dataset.filter;
    const published = c.querySelector('[data-key=published]').checked;
    c.style.display = f === 'all' || c.dataset.state === f || (f === 'todo' && !published) ? '' : 'none';
  }});
}}));
</script>
</body></html>
'''
