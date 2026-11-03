"""Bring ad results back into the plan: read a TikTok/Meta export, match rows to ads, suggest actions.

Matching: a row belongs to a job when its ad name contains the job id; otherwise when it contains
the ad's date (2026-11-02, 11-02, 02.11 or 0211) and, for A/B days, the variant letter. Rows that
match nothing are listed, never guessed. Thresholds are the strategy's starting heuristics; an
app can override them in app.json → "result_thresholds".
"""
import csv
import re
from datetime import datetime
from pathlib import Path

THRESHOLDS = {'hook_rate': .25, 'hold_rate': .15, 'ctr': .008, 'min_impressions': 1000}
# Column names differ per platform and language; each metric takes the first header that matches.
COLUMNS = {
    'name': ['ad name', 'reklam adı', 'reklam adi', 'ad', 'creative name', 'name'],
    'impressions': ['impressions', 'gösterimler', 'gosterimler', 'gösterim'],
    'views': ['3-second video plays', '3 second video plays', 'video plays at 3 seconds', '2-second video views',
              '2 second video views', 'video views at 2s', '3 saniyelik video oynatmaları', 'video views'],
    'holds': ['thruplays', 'thruplay', '15-second video views', '6-second video views', '6 second video views',
              'video views at 6s', 'video plays at 50%', 'video views at 50%'],
    'clicks': ['link clicks', 'clicks (destination)', 'bağlantı tıklamaları', 'clicks (all)', 'clicks', 'tıklamalar'],
    'spend': ['amount spent (usd)', 'amount spent', 'cost', 'spend', 'harcanan tutar', 'maliyet'],
    'installs': ['app installs', 'mobile app installs', 'installs', 'uygulama yüklemeleri', 'conversions'],
}


def number(value):
    """'1,234' / '1.234' / '1.234,5' / '12.5%' / '$3.20' → float (None when empty)."""
    text = re.sub(r'[^\d,.\-]', '', str(value or ''))
    if not text or text in '-.,':
        return None
    if ',' in text and '.' in text:
        text = text.replace('.', '').replace(',', '.') if text.rfind(',') > text.rfind('.') else text.replace(',', '')
    elif ',' in text:
        head, _, tail = text.rpartition(',')
        text = text.replace(',', '') if len(tail) == 3 and head else text.replace(',', '.')
    elif text.count('.') > 1 or (re.fullmatch(r'\d{1,3}\.\d{3}', text)):
        text = text.replace('.', '')
    return float(text)


def header_map(headers):
    clean = {h: re.sub(r'\s+', ' ', h.strip().lower()) for h in headers}
    found = {}
    for metric, names in COLUMNS.items():
        for name in names:
            match = next((h for h, c in clean.items() if c == name), None)
            if match:
                found[metric] = match
                break
    if 'name' not in found or 'impressions' not in found:
        raise ValueError('CSV içinde reklam adı ve gösterim sütunu bulunamadı. Sütunlar: ' + ', '.join(headers))
    return found


def read_rows(path):
    raw = Path(path).read_bytes()
    text = raw.decode('utf-8-sig') if raw[:3] == b'\xef\xbb\xbf' else raw.decode('utf-8', errors='replace')
    if '\x00' in text:
        text = raw.decode('utf-16')
    dialect = csv.Sniffer().sniff(text[:4096], delimiters=',;\t')
    rows = list(csv.DictReader(text.splitlines(), dialect=dialect))
    columns = header_map(rows[0].keys() if rows else [])
    out = []
    for row in rows:
        name = (row.get(columns['name']) or '').strip()
        if not name or name.lower().startswith(('total', 'toplam')):
            continue
        out.append({'name': name, **{m: number(row.get(c)) for m, c in columns.items() if m != 'name'}})
    return out


def date_keys(day):
    y, m, d = day.split('-')
    # Rows matching two plan days (0311 = 3 Nov or 11 Mar) stay unmatched; see match().
    return [day, f'{m}-{d}', f'{d}.{m}', f'{m}{d}', f'{d}{m}', f'{d}{m}{y[2:]}']


def match(rows, ads):
    """Assign each row to an ad job; returns (matches {job id: [rows]}, unmatched names)."""
    matches, unmatched = {}, []
    by_length = sorted(ads, key=lambda j: -len(j['id']))
    for row in rows:
        name = row['name']
        job = next((j for j in by_length if j['id'] in name), None)
        if not job:
            day_ads = [j for j in ads if any(k in name for k in date_keys(j['date']))]
            variant = re.search(r'(?:^|[\s_\-|/(])([AB])(?:$|[\s_\-|/)])', name)
            if variant:
                day_ads = [j for j in day_ads if j.get('variant') == variant[1]] or day_ads
            chosen = {j['date'] for j in day_ads}
            if len(chosen) == 1:
                selected = [j for j in day_ads if str(j.get('selected_for_publication')).lower() == 'true']
                job = (selected or day_ads)[0] if len(day_ads) == 1 or selected or variant else None
        if job:
            matches.setdefault(job['id'], []).append(row)
        else:
            unmatched.append(name)
    return matches, unmatched


def combine(rows):
    total = {k: sum(r[k] for r in rows if r.get(k) is not None) if any(r.get(k) is not None for r in rows) else None
             for k in ['impressions', 'views', 'holds', 'clicks', 'spend', 'installs']}
    imp, views = total['impressions'] or 0, total['views']
    total['hook_rate'] = views / imp if imp and views is not None else None
    total['hold_rate'] = total['holds'] / views if views and total['holds'] is not None else None
    total['ctr'] = total['clicks'] / imp if imp and total['clicks'] is not None else None
    total['cpi'] = total['spend'] / total['installs'] if total['installs'] and total['spend'] is not None else None
    return total


def advice(metrics, limits):
    """Next creative action, using the plan's test rules."""
    if (metrics['impressions'] or 0) < limits['min_impressions']:
        return 'wait', f"Henüz erken: {int(metrics['impressions'] or 0)} gösterim (en az {limits['min_impressions']})."
    if metrics['hook_rate'] is not None and metrics['hook_rate'] < limits['hook_rate']:
        return 'hook', 'Hook zayıf: açılış çekimini yenileyin (revize HOOK_ID), gövde kalsın.'
    if metrics['hold_rate'] is not None and metrics['hold_rate'] < limits['hold_rate']:
        return 'hold', 'İzleyici ortada düşüyor: gövdeyi kısaltın veya 15 sn sürümü deneyin.'
    if metrics['ctr'] is not None and metrics['ctr'] < limits['ctr']:
        return 'cta', 'İzleniyor ama tıklanmıyor: CTA cümlesini veya bitiş kartını değiştirin.'
    return 'scale', 'İyi gidiyor: bütçeyi artırın ve bu konsepte 2 yeni hook yazın.'


def percent(value):
    return '—' if value is None else f'{value * 100:.1f}%'


def import_results(ws, csv_path, cfg=None):
    import delivery
    import pipeline
    limits = {**THRESHOLDS, **((cfg or {}).get('app') or {}).get('result_thresholds', {})}
    rows = read_rows(csv_path)
    ads = delivery.ad_jobs(ws)
    matches, unmatched = match(rows, ads)
    stamp = datetime.now().isoformat(timespec='seconds')
    report = []
    for ad in sorted(ads, key=lambda j: j['id']):
        if ad['id'] not in matches:
            continue
        metrics = combine(matches[ad['id']])
        kind, text = advice(metrics, limits)
        entry = {'source': Path(csv_path).name, 'imported': stamp, 'rows': len(matches[ad['id']]),
                 **{k: v for k, v in metrics.items()}, 'advice': kind, 'advice_text': text}
        data = pipeline.read(ad['_file'])
        data['results'] = [r for r in data.get('results', []) if r.get('source') != entry['source']] + [entry]
        pipeline.write(ad['_file'], data)
        report.append((ad, entry))
        print(f"{ad['date']} {ad['id']}: gösterim {int(metrics['impressions'] or 0)}, hook {percent(metrics['hook_rate'])}, "
              f"tutma {percent(metrics['hold_rate'])}, CTR {percent(metrics['ctr'])}"
              + (f", yükleme başı {metrics['cpi']:.2f}" if metrics['cpi'] is not None else '') + f" → {text}")
    if unmatched:
        print('Eşleşmeyen satırlar (reklam adına iş kimliğini veya tarihi yazın): ' + '; '.join(unmatched))
    pipeline.write(ws/'analysis'/f'results-{datetime.now():%Y%m%d-%H%M%S}.json',
                   {'source': str(csv_path), 'imported': stamp, 'limits': limits, 'unmatched': unmatched,
                    'ads': [{'id': ad['id'], 'date': ad['date'], **entry} for ad, entry in report]})
    return report, unmatched
