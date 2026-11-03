"""Minimal ComfyUI HTTP client (stdlib only): queue a workflow, wait, fetch outputs, upload inputs, free VRAM."""
import json
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


class ComfyError(RuntimeError):
    pass


# Inputs engines add "when the node supports them"; any other unknown input is left for ComfyUI to reject loudly.
OPTIONAL_INPUTS = {'audio_vae', 'device', 'format', 'weight_dtype', 'dtype', 'ref_image_size'}


class Comfy:
    def __init__(self, url, timeout=30):
        self.url = url.rstrip('/')
        self.timeout = timeout
        self.client_id = uuid.uuid4().hex

    def _request(self, path, data=None, headers=None, method=None):
        req = urllib.request.Request(self.url + path, data=data, headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                body = r.read()
        except urllib.error.HTTPError as e:
            raise ComfyError(f'ComfyUI {path}: HTTP {e.code} {e.read()[:2000].decode("utf-8", "replace")}') from e
        except OSError as e:
            raise ComfyError(f'ComfyUI erişilemiyor ({self.url}): {e}') from e
        return body

    def _json(self, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        body = self._request(path, data, {'Content-Type': 'application/json'} if data else None)
        return json.loads(body) if body.strip() else {}

    def system_stats(self):
        return self._json('/system_stats')

    def object_info(self):
        if not getattr(self, '_object_info', None):
            self._object_info = self._json('/object_info')
        return self._object_info

    def validate(self, workflow):
        """Check the graph against ComfyUI's real node schemas (ported from OzzyVision-Lab): node classes that are
        not installed fail with a readable error; inputs the engine adds "if supported" are dropped when a node does
        not take them (e.g. MiniMaxH3ImageToVideo has no audio_vae). Returns the warnings."""
        info = self.object_info()
        if not info:
            return []
        missing = sorted({n['class_type'] for n in workflow.values() if n['class_type'] not in info})
        if missing:
            raise ComfyError('ComfyUI\'de düğüm yok: ' + ', '.join(missing) + ' (ComfyUI güncel mi?)')
        warnings = []
        for node_id, node in workflow.items():
            spec = info[node['class_type']].get('input') or {}
            accepted = {k for part in ('required', 'optional') for k in (spec.get(part) or {})}
            for key in list(node.get('inputs', {})):
                # Dotted names (ref_images.ref_image_0) are dynamic inputs that the schema does not list.
                if key not in accepted and '.' not in key and key in OPTIONAL_INPUTS:
                    del node['inputs'][key]
                    warnings.append(f"{node_id} ({node['class_type']}): '{key}' desteklenmiyor, kaldırıldı")
        return warnings

    def submit(self, workflow):
        """Returns ComfyUI's prompt_id; node validation errors come back as a readable message."""
        result = self._json('/prompt', {'prompt': workflow, 'client_id': self.client_id})
        if result.get('node_errors'):
            raise ComfyError('Workflow hatası: ' + json.dumps(result['node_errors'], ensure_ascii=False)[:3000])
        return result['prompt_id']

    def wait(self, prompt_id, timeout, should_stop=lambda: False, poll=2.0):
        """Block until the prompt finishes; returns its history entry."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if should_stop():
                self.interrupt()
                raise ComfyError('İptal edildi')
            history = self._json('/history/' + prompt_id).get(prompt_id)
            if history:
                status = history.get('status') or {}
                if status.get('status_str') == 'error':
                    messages = [m for m in status.get('messages', []) if m and m[0] == 'execution_error']
                    detail = messages[-1][1] if messages else status
                    raise ComfyError('ComfyUI çalıştırma hatası: ' + json.dumps(detail, ensure_ascii=False)[:3000])
                if status.get('completed', True):
                    return history
            time.sleep(poll)
        self.interrupt()
        raise ComfyError(f'Zaman aşımı ({timeout} sn)')

    def outputs(self, history, node_id=None):
        """Files a finished prompt produced: [{filename, subfolder, type}] (SaveImage, SaveVideo, VHS…)."""
        files = []
        for nid, out in (history.get('outputs') or {}).items():
            if node_id and str(nid) != str(node_id):
                continue
            for key in ('videos', 'gifs', 'images', 'audio'):
                files += [f for f in out.get(key, []) if isinstance(f, dict) and f.get('filename')]
        return files

    def download(self, file, target):
        query = urllib.parse.urlencode({'filename': file['filename'], 'subfolder': file.get('subfolder', ''),
                                        'type': file.get('type', 'output')})
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        Path(target).write_bytes(self._request('/view?' + query))
        return Path(target)

    def upload(self, path, name=None):
        """Copies a local file into ComfyUI's input folder; returns the name LoadImage/LoadVideo/LoadAudio use."""
        path = Path(path)
        boundary = uuid.uuid4().hex
        name = name or path.name
        parts = [
            f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\n'
            'Content-Type: application/octet-stream\r\n\r\n'.encode() + path.read_bytes() + b'\r\n',
            f'--{boundary}\r\nContent-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n'.encode(),
            f'--{boundary}--\r\n'.encode(),
        ]
        body = self._request('/upload/image', b''.join(parts), {'Content-Type': f'multipart/form-data; boundary={boundary}'})
        info = json.loads(body)
        return (info.get('subfolder') + '/' if info.get('subfolder') else '') + info['name']

    def free(self):
        """Unload every model from VRAM (used when the queue switches between video and image models)."""
        self._json('/free', {'unload_models': True, 'free_memory': True})

    def interrupt(self):
        try:
            self._request('/interrupt', b'', method='POST')
        except ComfyError:
            pass
