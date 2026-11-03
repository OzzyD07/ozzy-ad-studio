"""Persistent job queue with one GPU worker.

Jobs are JSON files under STUDIO_HOME/jobs (Drive), so a Colab restart keeps history and re-queues work that was
running. Scheduling (K-10): while a model kind is loaded, jobs of that kind go first; switching kind frees VRAM
once, so a mixed queue runs as "all videos, then all images" without reloading per job.
"""
import base64
import hashlib
import hmac
import json
import shutil
import threading
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import media
from .comfy import Comfy, ComfyError
from .engines import EngineError, registry

ACTIVE = ('queued', 'running')
MEDIA_TYPES = {'image': ('.png', '.jpg', '.jpeg', '.webp'), 'video': ('.mp4', '.mov', '.webm', '.m4v', '.mkv'),
               'audio': ('.wav', '.mp3', '.m4a', '.aac', '.flac', '.ogg')}
MAX_ASSET_BYTES = 1024**3


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def media_type(name):
    ext = Path(name).suffix.lower()
    return next((t for t, exts in MEDIA_TYPES.items() if ext in exts), None)


class Studio:
    def __init__(self, settings, comfy=None):
        self.s = settings
        self.comfy = comfy or Comfy(settings.comfy_url)
        self.engines = registry()
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.jobs = {}
        self.loaded_kind = None
        self.current = None
        self.durations = {}  # engine -> recent run seconds, for ETA
        self.stop = False
        for path in sorted((self.s.home/'jobs').glob('*.json')):
            job = json.loads(path.read_text(encoding='utf-8'))
            if job['status'] == 'running':  # Interrupted by a restart: run it again.
                job.update(status='queued', note='sunucu yeniden başladı, iş tekrar sırada')
            self.jobs[job['id']] = job
        self.worker = threading.Thread(target=self._loop, name='studio-gpu', daemon=True)

    # ---------- store ----------
    def _save(self, job):
        job['updated'] = now()
        path = self.s.home/'jobs'/f"{job['id']}.json"
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding='utf-8')
        tmp.replace(path)

    def get(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                raise KeyError(f'İş bulunamadı: {job_id}')
            return {**job, **self._position(job)}

    def list(self, limit=20, status=None):
        with self.lock:
            jobs = [j for j in self.jobs.values() if not status or j['status'] == status]
            jobs.sort(key=lambda j: j['created'], reverse=True)
            return [{**j, **self._position(j)} for j in jobs[:limit]]

    # ---------- assets ----------
    def add_asset(self, file_path=None, url=None, base64_data=None, filename=None, kind=None):
        sources = [x for x in (file_path, url, base64_data) if x]
        if len(sources) != 1:
            raise ValueError('file_path, url veya base64_data alanlarından tam olarak biri gerekli')
        asset_id = 'ast_' + uuid.uuid4().hex[:12]
        name = Path(filename or (Path(file_path).name if file_path else Path(url.split('?')[0]).name if url else 'asset')).name
        kind = kind or media_type(name)
        if kind not in MEDIA_TYPES:
            raise ValueError(f'Medya türü anlaşılamadı: {name} (media_type: image/video/audio)')
        if not Path(name).suffix:
            name += MEDIA_TYPES[kind][0]
        target = self.s.home/'assets'/f'{asset_id}_{name}'
        if file_path:
            shutil.copyfile(file_path, target)
        elif url:
            if not url.startswith(('https://', 'http://')):
                raise ValueError('url http(s) olmalı')
            with urllib.request.urlopen(url, timeout=120) as r, target.open('wb') as f:
                size = 0
                while chunk := r.read(1 << 20):
                    size += len(chunk)
                    if size > MAX_ASSET_BYTES:
                        raise ValueError('Dosya 1 GB sınırını aşıyor')
                    f.write(chunk)
        else:
            target.write_bytes(base64.b64decode(base64_data))
        return {'asset_id': asset_id, 'filename': name, 'media_type': kind, 'bytes': target.stat().st_size}

    def assets(self):
        out = []
        for p in sorted((self.s.home/'assets').glob('ast_*'), key=lambda p: p.stat().st_mtime, reverse=True):
            asset_id, _, name = p.name.partition('_')[2].partition('_')
            out.append({'asset_id': 'ast_' + asset_id, 'filename': name, 'media_type': media_type(name),
                        'bytes': p.stat().st_size})
        return out

    def resolve_asset(self, ref):
        """asset_id, an absolute server path, or an http(s) URL → local file."""
        if ref.startswith('ast_'):
            found = list((self.s.home/'assets').glob(ref + '_*'))
            if not found:
                raise ValueError(f'Asset bulunamadı: {ref}')
            return found[0]
        if ref.startswith(('http://', 'https://')):
            return self.resolve_asset(self.add_asset(url=ref)['asset_id'])
        path = Path(ref)
        if path.is_file():
            return path
        raise ValueError(f'Referans bulunamadı: {ref}')

    # ---------- queue ----------
    def submit(self, engine, request, priority=0):
        if engine not in self.engines:
            raise EngineError(f'Bilinmeyen model: {engine} ({", ".join(self.engines)})')
        eng = self.engines[engine]
        eng.validate(request)
        for key in ('images', 'videos', 'audios'):
            for ref in request.get(key) or []:
                self.resolve_asset(ref)  # Fail now, not after an hour in the queue.
        job_id = f"{'vid' if eng.kind == 'video' else 'img'}_{datetime.now():%Y%m%d}_{uuid.uuid4().hex[:6]}"
        job = {'id': job_id, 'engine': engine, 'kind': eng.kind, 'status': 'queued', 'priority': int(priority),
               'request': request, 'created': now(), 'attempts': 0}
        with self.lock:
            self.jobs[job_id] = job
            self._save(job)
        self.wake.set()
        return self.get(job_id)

    def _order(self):
        """Queued jobs in the order the worker will take them."""
        queued = sorted((j for j in self.jobs.values() if j['status'] == 'queued'),
                        key=lambda j: (-j['priority'], j['created']))
        kinds = []
        for j in queued:
            if j['kind'] not in kinds:
                kinds.append(j['kind'])
        if self.loaded_kind in kinds:
            kinds.remove(self.loaded_kind)
            kinds.insert(0, self.loaded_kind)
        return [j for k in kinds for j in queued if j['kind'] == k]

    def _position(self, job):
        if job['status'] != 'queued':
            return {}
        order = self._order()
        ahead = order[:order.index(job)] if job in order else []
        eta = sum(self.durations.get(j['engine'], 600) for j in ahead)
        if self.current:
            started = self.current.get('started_ts', time.time())
            eta += max(0, self.durations.get(self.current['engine'], 600) - (time.time() - started))
        return {'queue_position': len(ahead) + 1, 'eta_seconds': int(eta),
                'waits_for_model_switch': job['kind'] != (self.current or {}).get('kind', self.loaded_kind)}

    def cancel(self, job_id):
        with self.lock:
            job = self.jobs[job_id]
            if job['status'] not in ACTIVE:
                raise ValueError(f"İş zaten {job['status']}")
            job['cancel_requested'] = True
            if job['status'] == 'queued':
                job['status'] = 'cancelled'
            self._save(job)
            return self.get(job_id)

    def retry(self, job_id):
        with self.lock:
            job = self.jobs[job_id]
            if job['status'] not in ('failed', 'cancelled'):
                raise ValueError('Yalnızca başarısız veya iptal edilmiş iş yeniden denenir')
            job.update(status='queued', error=None, cancel_requested=False, created=now())
            self._save(job)
        self.wake.set()
        return self.get(job_id)

    def reorder(self, job_id, direction):
        with self.lock:
            job = self.jobs[job_id]
            job['priority'] += 1 if direction == 'up' else -1
            self._save(job)
            return self.get(job_id)

    def free_vram(self):
        with self.lock:
            if self.current:
                raise ValueError('Bir iş çalışırken VRAM boşaltılamaz')
            self.comfy.free()
            self.loaded_kind = None

    # ---------- worker ----------
    def start(self):
        self.worker.start()
        self.wake.set()

    def _loop(self):
        while not self.stop:
            with self.lock:
                order = self._order()
                job = order[0] if order else None
                if job:
                    if self.loaded_kind and job['kind'] != self.loaded_kind:
                        try:
                            self.comfy.free()  # One switch per batch, not per job (K-10).
                        except ComfyError:
                            pass
                    self.loaded_kind = job['kind']
                    job.update(status='running', started=now(), attempts=job['attempts'] + 1)
                    job['started_ts'] = time.time()
                    self.current = job
                    self._save(job)
            if not job:
                self.wake.wait(5)
                self.wake.clear()
                continue
            try:
                self._run(job)
            except Exception as e:  # Any failure is recorded on the job; the worker keeps going.
                with self.lock:
                    job.update(status='cancelled' if job.get('cancel_requested') else 'failed',
                               error=str(e)[:4000], finished=now())
                    self._save(job)
            finally:
                with self.lock:
                    self.current = None

    def model_files(self):
        files = {}
        for folder in ('diffusion_models', 'text_encoders', 'vae'):
            try:
                files[folder] = self.comfy._json('/models/' + folder)
            except ComfyError:
                files[folder] = []
        return files

    def _inputs(self, job):
        r = job['request']
        refs = {'images': [], 'videos': [], 'audios': []}
        work = self.s.home/'work'/job['id']
        work.mkdir(parents=True, exist_ok=True)
        for i, ref in enumerate(r.get('images') or []):
            path = self.resolve_asset(ref)
            refs['images'].append(self.comfy.upload(path, f"{job['id']}_img{i}{path.suffix}"))
        total = 0.0
        for i, ref in enumerate(r.get('videos') or []):
            prepared = work/f'ref_video_{i}.mp4'
            info = media.prepare_reference_video(self.resolve_asset(ref), prepared)
            total += info['duration'] or 0
            refs['videos'].append({'file': self.comfy.upload(prepared, f"{job['id']}_vid{i}.mp4"), 'has_audio': info['has_audio']})
        if total > 15.5:
            raise EngineError(f'Referans videoların toplamı en fazla 15 sn ({total:.1f} sn)')
        for i, ref in enumerate(r.get('audios') or []):
            path = self.resolve_asset(ref)
            refs['audios'].append(self.comfy.upload(path, f"{job['id']}_aud{i}{path.suffix}"))
        return refs

    def _run(self, job):
        engine = self.engines[job['engine']]
        refs = self._inputs(job)
        workflow, meta = engine.build({**job['request'], 'job_id': job['id']}, refs, self.model_files())
        with self.lock:
            job['metadata'] = meta
            self._save(job)
        prompt_id = self.comfy.submit(workflow)
        history = self.comfy.wait(prompt_id, self.s.job_timeout, lambda: job.get('cancel_requested'))
        files = self.comfy.outputs(history)
        if not files:
            raise ComfyError('ComfyUI çıktı üretmedi')
        day = self.s.home/'outputs'/datetime.now().strftime('%Y-%m-%d')
        saved = []
        for i, f in enumerate(files):
            suffix = Path(f['filename']).suffix or ('.mp4' if engine.kind == 'video' else '.png')
            target = day/(job['id'] + (f'_{i + 1}' if len(files) > 1 else '') + suffix)
            self.comfy.download(f, target)
            if engine.kind == 'video':
                media.make_playable(target)
            saved.append(target)
        took = time.time() - job['started_ts']
        prev = self.durations.get(job['engine'])
        self.durations[job['engine']] = took if prev is None else prev * 0.5 + took * 0.5
        shutil.rmtree(self.s.home/'work'/job['id'], ignore_errors=True)
        with self.lock:
            job.update(status='done', finished=now(), seconds=round(took, 1),
                       outputs=[str(p.relative_to(self.s.home)).replace('\\', '/') for p in saved])
            self._save(job)


def sign(token, path):
    """Download links carry an HMAC of the path, so files are private without an auth header."""
    return hmac.new(token.encode(), path.encode(), hashlib.sha256).hexdigest()[:32]
