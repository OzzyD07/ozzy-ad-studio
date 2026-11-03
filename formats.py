"""Content formats besides the MiniMax AI video: image post, carousel and template video, plus Remotion finishing
and multiple cuts for AI videos.

A job's "format" picks the flow (default "ai_video", the original pipeline):
  image_post      Qwen image (Studio MCP generate_image) → Remotion PostStill → exports/<id>/post.png
  carousel        one Qwen image per slide that asks for one → Remotion Carousel → exports/<id>/01.png …
  template_video  no GPU: Remotion TemplatePromo (+ local TTS) → exports/<id>/video.mp4
  ai_video        with render.engine = "remotion": Remotion AdVideo finishing, and job "cuts" → one file per cut
Each run() call advances a job by one step, so a queue pass never blocks on the GPU.
"""
import shutil
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

FORMATS = ('ai_video', 'image_post', 'carousel', 'template_video')
IMAGE_ARGUMENTS = {'prompt': '{{image_prompt}}', 'aspect_ratio': '{{aspect_ratio}}', 'quality': 'max', 'count': 1}
MAX_IMAGE_BYTES = 200 * 1024**2


def fmt(job):
    return job.get('format', 'ai_video')


def read(path):
    import pipeline
    return pipeline.read(path)


def write(path, data):
    import pipeline
    pipeline.write(path, data)


# ---------- planning ----------
def validate_script(s, index):
    """Errors for a product.json script entry of a non-video format."""
    f, errors = s.get('format', 'ai_video'), []
    if f not in FORMATS:
        return [f'Senaryo {index}: bilinmeyen format {f} ({", ".join(FORMATS)})']
    if f == 'image_post':
        if not (s.get('post') or {}).get('title'):
            errors.append(f'Senaryo {index}: image_post için post.title gerekli')
    elif f == 'carousel':
        slides = s.get('slides') or []
        if not 2 <= len(slides) <= 10:
            errors.append(f'Senaryo {index}: carousel 2–10 slayt olmalı')
        errors += [f'Senaryo {index}: slayt {k} başlıksız' for k, sl in enumerate(slides, 1) if not sl.get('title')]
    elif f == 'template_video':
        if not (s.get('promo') or {}).get('scenes'):
            errors.append(f'Senaryo {index}: template_video için promo.scenes gerekli')
    prompts = [s.get('image_prompt')] + [sl.get('image_prompt') for sl in s.get('slides') or []]
    if any(p and len(p) > 2000 for p in prompts):
        errors.append(f'Senaryo {index}: image_prompt 2000 karakteri aşıyor')
    return errors


def plan_job(s, common, job_id):
    """Job for a non-video script entry; fields shared with video jobs come from `common`."""
    f = s['format']
    job = {'id': job_id, **common, 'format': f, 'status': 'planned', 'review_required': True}
    if f == 'image_post':
        job.update(image_prompt=s.get('image_prompt'), aspect_ratio=s.get('aspect_ratio', '4:5'), post=s['post'])
    elif f == 'carousel':
        job.update(aspect_ratio=s.get('aspect_ratio', '4:5'), swipe_label=s.get('swipe_label'),
                   slides=[{k: v for k, v in sl.items()} for sl in s['slides']])
    elif f == 'template_video':
        job.update(promo=s['promo'])
    return job


# ---------- Studio MCP images ----------
def submit_image(prompt, aspect_ratio, cfg):
    from mcp_bridge import call, expand, lookup
    mc = cfg['mcp']
    template = mc.get('image_arguments') or IMAGE_ARGUMENTS
    result = call(mc, mc.get('image_tool', 'generate_image'),
                  expand(template, {'image_prompt': prompt, 'aspect_ratio': aspect_ratio}))
    remote = lookup(result, mc.get('remote_id_path', 'job_id'))
    if remote is None:
        raise RuntimeError('Görsel işi kimliği dönmedi: ' + str(result)[:300])
    return remote, lookup(result, mc.get('image_result_path', 'job.output_image'))


def poll_image(remote_id, cfg):
    """Link of the finished image, None while it is still queued/running."""
    from mcp_bridge import call, expand, lookup
    mc = cfg['mcp']
    result = call(mc, mc['status_tool'], expand(mc['status_arguments'], {'remote_id': remote_id}))
    state = lookup(result, 'job.status')
    if state in ('failed', 'error', 'cancelled'):
        raise RuntimeError(f'Görsel işi {state}: ' + str(lookup(result, 'job.error') or result)[:500])
    return lookup(result, mc.get('image_result_path', 'job.output_image'))


def fetch(artifact, cfg, target):
    """Download a result (relative links resolve against the MCP URL) or copy a local one (stdio test server)."""
    mc = cfg['mcp']
    if mc.get('transport') == 'http' and str(artifact).startswith('/'):
        artifact = urljoin(mc['url'], artifact)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + '.part')
    try:
        if str(artifact).startswith('https://'):
            with urllib.request.urlopen(artifact, timeout=120) as r, tmp.open('wb') as f:
                size = 0
                while chunk := r.read(1 << 20):
                    size += len(chunk)
                    if size > MAX_IMAGE_BYTES:
                        raise ValueError('Görsel 200 MB sınırını aşıyor')
                    f.write(chunk)
        elif str(artifact).startswith('http://'):
            raise ValueError('İndirme HTTPS kullanmalı: ' + str(artifact)[:80])
        else:
            shutil.copy2(Path(artifact), tmp)
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)
    return target


def image_step(holder, key, prompt, aspect_ratio, cfg, target):
    """Advance one image: submit, poll, download. `holder` keeps remote id and path under `key`."""
    if holder.get(key) and Path(holder[key]).is_file():
        return True
    remote_key = key + '_remote_id'
    if not holder.get(remote_key):
        holder[remote_key], ready = submit_image(prompt, aspect_ratio, cfg)
    else:
        ready = poll_image(holder[remote_key], cfg)
    if ready:
        holder[key] = str(fetch(ready, cfg, target))
        return True
    return False


# ---------- runners ----------
def brand(cfg):
    card = cfg.get('end_card') or {}
    icon = card.get('icon')
    return {'appName': (cfg.get('app') or {}).get('name'), 'icon': icon if icon and Path(icon).is_file() else None}


def export_dir(ws, job):
    out = Path(ws)/'exports'/job['id']
    if out.exists() and any(out.iterdir()):
        raise ValueError('Çıktı zaten var: ' + str(out))
    out.mkdir(parents=True, exist_ok=True)
    return out


def finish_export(job, path, out):
    (out/'caption.txt').write_text(job.get('caption', ''), encoding='utf-8')
    write(out/'job.json', job)
    job.update(status='done', export=str(out))
    write(path, job)
    print(job['id'] + ': ' + str(out))


def run(job, path, cfg, ws):
    """One step for a non-video job, or for an AI video finished in Remotion. Returns the new status."""
    import render
    ws = Path(ws)
    f = fmt(job)
    if f == 'image_post':
        if job.get('image_prompt') and not image_step(job, 'image', job['image_prompt'], job.get('aspect_ratio', '4:5'),
                                                     cfg, ws/'raw'/f"{job['id']}.png"):
            job['status'] = 'waiting'
            write(path, job)
            print(job['id'] + ': görsel üretiliyor')
            return job['status']
        out = export_dir(ws, job)
        b = brand(cfg)
        props = {**job['post'], 'background': job.get('image')}
        if job['post'].get('brand', True):
            props = {'icon': b['icon'], 'appName': b['appName'], **props}
        props.pop('brand', None)
        render.render('PostStill', {k: v for k, v in props.items() if v is not None}, out/'post.png', cfg, base=ws)
        finish_export(job, path, out)
    elif f == 'carousel':
        pending = False
        for k, slide in enumerate(job['slides']):
            if slide.get('image_prompt'):
                done = image_step(slide, 'image', slide['image_prompt'], job.get('aspect_ratio', '4:5'), cfg,
                                  ws/'raw'/f"{job['id']}-{k + 1:02d}.png")
                pending = pending or not done
        if pending:
            job['status'] = 'waiting'
            write(path, job)
            print(job['id'] + ': carousel görselleri üretiliyor')
            return job['status']
        out = export_dir(ws, job)
        slides = []
        for slide in job['slides']:
            s = {k: v for k, v in slide.items() if k not in ('image_prompt', 'image', 'image_remote_id', 'brand')}
            if slide.get('image'):
                s['background'] = slide['image']
            if slide.get('brand'):
                s = {**{k: v for k, v in brand(cfg).items() if v}, **s}
            slides.append(s)
        props = {'slides': slides, **({'swipeLabel': job['swipe_label']} if job.get('swipe_label') else {})}
        render.render('Carousel', props, out, cfg, base=ws)
        finish_export(job, path, out)
    elif f == 'template_video':
        out = export_dir(ws, job)
        render.render('TemplatePromo', job['promo'], out/'video.mp4', cfg, base=ws)
        finish_export(job, path, out)
    else:
        raise ValueError(f'{job["id"]}: {f} bu yolla işlenmez')
    return job['status']


# ---------- AI video in Remotion ----------
def speech_words(job, cfg):
    """Whisper timing with the script's spelling (align_script), as caption words."""
    import media
    import render
    language = job.get('language') or cfg['whisper'].get('language') or 'en'
    segments = media.transcribe(job['raw_video'], {**cfg['whisper'], 'language': language},
                                Path(cfg['workspace'])/'models')
    if job.get('voiceover'):
        segments = media.align_script(segments, job['voiceover'])
    return render.words_from_segments(segments), language


def cut_props(job, cut, words, language, cfg, music=None, duration=None):
    """AdVideo props for one cut: its own trim, hook text and caption style over the same footage.
    duration: length of the raw footage, so the end card can wait for the speech (as the FFmpeg path does)."""
    trim = list(cut.get('trim') or [0]) + [None]
    start, end = float(trim[0] or 0), trim[1]
    clip = {'src': job['raw_video'], 'trimBefore': start}
    if end is not None:
        clip['duration'] = float(end) - start
    shifted = [{**w, 'start': round(w['start'] - start, 3), 'end': round(w['end'] - start, 3)}
               for w in words if w['start'] >= start - 0.05 and (end is None or w['end'] <= float(end) + 0.05)]
    style = cut.get('caption_style') or (cfg.get('subtitles') or {}).get('style', 'pop')
    props = {'clips': [clip],
             'captions': {'words': shifted, 'style': style, 'language': language,
                          'emphasis': [*(job.get('emphasis') or []), *([job['app_name']] if job.get('app_name') else [])]},
             'hookText': cut.get('hook_text', job.get('hook_text')) or None}
    if job.get('cta') or job.get('app_name'):
        props['endCard'] = {k: v for k, v in {'headline': job.get('cta'), 'appName': job.get('app_name')}.items() if v}
        length = (float(end) if end is not None else duration) and ((float(end) if end is not None else duration) - start)
        if length:
            # Start the card once the speech ends, but keep it on screen at least 2 s.
            card_cfg = cfg.get('end_card') or {}
            total = length + float(card_cfg.get('extend_seconds', 1.5))
            speech_end = shifted[-1]['end'] if shifted else 0
            props['endCard']['seconds'] = round(max(2.0, min(float(card_cfg.get('seconds', 3)), total - speech_end - .15)), 2)
    if music:
        props['music'] = {'src': str(music), 'volume': (cfg.get('music') or {}).get('volume', 0.22)}
    return props


def finish_ai_video(job, path, cfg, ws):
    """Remotion finishing for a raw_ready AI video; each entry of job["cuts"] becomes <name>.mp4 (first = video.mp4)."""
    import pipeline
    import render
    ws = Path(ws)
    out = export_dir(ws, job)
    words, language = speech_words(job, cfg)
    import media
    music = job.get('music') and pipeline.resolve_asset(job['music'], ws)
    duration = media.media_duration(job['raw_video'])
    cuts = job.get('cuts') or [{'name': 'video'}]
    files = []
    for k, cut in enumerate(cuts):
        name = 'video' if k == 0 else cut.get('name') or f'kesit-{k + 1}'
        props = cut_props(job, cut, words, language, cfg, music, duration)
        render.render('AdVideo', props, out/f'{name}.mp4', cfg, base=ws)
        files.append(f'{name}.mp4')
    job['cut_files'] = files
    finish_export(job, path, out)
