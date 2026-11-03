"""Two posts a day (Faz 6): publishing slots, format mix and the GPU budget of a plan.

Settings (config.json or the app's app.json → "config"):
    "calendar": {
      "per_day": 2,
      "slots": [{"name": "sabah", "time": "09:00", "formats": ["image_post", "carousel", "template_video"]},
                {"name": "aksam", "time": "19:00", "formats": ["ai_video", "template_video"]}],
      "budget": {"ai_videos_per_week": 4, "images_per_day": 6},
      "gpu": {"minutes_per_video_shot": 6, "minutes_per_image": 0.5, "units_per_hour": 10}
    }
Slot times are in the app's publish time zone (app.json → publish.timezone), like the old single slot.
"""
import copy
from datetime import date, timedelta

DEFAULT = {
    'per_day': 2,
    'slots': [{'name': 'sabah', 'time': '09:00', 'formats': ['image_post', 'carousel', 'template_video']},
              {'name': 'aksam', 'time': '19:00', 'formats': ['ai_video', 'template_video']}],
    'budget': {'ai_videos_per_week': 4, 'images_per_day': 6},
    # Estimates, to be tuned from real runs: a Qwen draft took 14 s on Colab G4 and Colab showed ≈10 units/h.
    # A max-quality MiniMax shot has not been timed yet; 6 min is a placeholder.
    'gpu': {'minutes_per_video_shot': 6, 'minutes_per_image': 0.5, 'units_per_hour': 10},
}


def settings(cfg):
    s = copy.deepcopy(DEFAULT)
    for key, value in ((cfg or {}).get('calendar') or {}).items():
        s[key] = {**s[key], **value} if isinstance(s.get(key), dict) else value
    return s


def per_day(cfg, given=None):
    """--per-day wins; otherwise the calendar setting when the app has one, else the old one-a-day plan."""
    if given:
        return given
    return settings(cfg)['per_day'] if (cfg or {}).get('calendar') else 1


def assign(scripts, days, n, cfg):
    """[(script index, day index, slot name, script)]: each day takes the next n scripts, slots in order."""
    if n < 1 or n > 4:
        raise ValueError('Günde 1–4 gönderi olmalı.')
    if len(scripts) < days * n:
        raise ValueError(f'{days} gün × {n} gönderi için en az {days * n} senaryo gerekli (var: {len(scripts)}).')
    names = [s['name'] for s in settings(cfg)['slots']]
    out = []
    for i in range(days * n):
        s = scripts[i]
        slot = s.get('slot') or (names[i % n] if n > 1 and i % n < len(names) else None)
        out.append((i, i // n, slot, s))
    return out


def slot_time(slot, cfg):
    return next((s.get('time') for s in settings(cfg)['slots'] if s['name'] == slot), None)


def gpu_items(job):
    """(video generations, image generations) a job will send to the Studio MCP."""
    f = job.get('format', 'ai_video')
    if f == 'image_post':
        return 0, 1 if job.get('image_prompt') else 0
    if f == 'carousel':
        return 0, sum(1 for s in job.get('slides') or [] if s.get('image_prompt'))
    if f == 'template_video':
        return 0, 0
    # A video shot with a prompt costs a generation; montage parents and real-footage clips do not.
    return (1 if job.get('prompt') and job.get('role') != 'edit' and job.get('source') != 'clip' else 0), 0


def budget(jobs, cfg):
    """(report lines, warnings) for a plan: per-week videos, per-day images, estimated Colab time and units."""
    s = settings(cfg)
    b, g = s['budget'], s['gpu']
    videos_by_week, images_by_day = {}, {}
    total_v = total_i = 0
    for job in jobs:
        v, i = gpu_items(job)
        if not job.get('date'):
            continue
        week = date.fromisoformat(job['date']).isocalendar()[:2]
        videos_by_week[week] = videos_by_week.get(week, 0) + v
        images_by_day[job['date']] = images_by_day.get(job['date'], 0) + i
        total_v += v
        total_i += i
    warnings = [f"{y}-H{w}: {n} video üretimi (bütçe {b['ai_videos_per_week']}/hafta)"
                for (y, w), n in sorted(videos_by_week.items()) if n > b['ai_videos_per_week']]
    warnings += [f'{d}: {n} görsel üretimi (bütçe {b["images_per_day"]}/gün)'
                 for d, n in sorted(images_by_day.items()) if n > b['images_per_day']]
    minutes = total_v * g['minutes_per_video_shot'] + total_i * g['minutes_per_image']
    units = minutes / 60 * g['units_per_hour']
    lines = ['## GPU bütçesi', '',
             f'- Video üretimi (MiniMax çekimi): {total_v} · görsel üretimi (Qwen): {total_i}',
             f'- Tahmini Colab süresi: ~{minutes:.0f} dk GPU (yükleme hariç) · ~{units:.1f} işlem birimi',
             f"- Bütçe: haftada {b['ai_videos_per_week']} video, günde {b['images_per_day']} görsel"
             + ('' if warnings else ' · aşılmıyor')]
    lines += [f'- ⚠️ {w}' for w in warnings]
    return lines + [''], warnings


def suggest(start, days, n, cfg):
    """[(day, slot, format)] for the strategy brief: each slot rotates its formats; AI video only while the
    week's budget lasts, then the slot's next non-AI format."""
    s = settings(cfg)
    slots = s['slots'][:n] if n > 1 else [s['slots'][-1]]
    cap = s['budget']['ai_videos_per_week']
    used, out = {}, []
    for d in range(days):
        day = start + timedelta(days=d)
        week = day.isocalendar()[:2]
        for k, slot in enumerate(slots):
            options = slot['formats']
            choice = options[(d + k) % len(options)]
            if choice == 'ai_video' and used.get(week, 0) >= cap:
                choice = next((f for f in options if f != 'ai_video'), 'template_video')
            if choice == 'ai_video':
                used[week] = used.get(week, 0) + 1
            out.append((day.isoformat(), slot['name'] if n > 1 else None, choice))
    return out
