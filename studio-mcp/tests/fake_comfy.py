"""A stand-in ComfyUI HTTP API for tests: records workflows and VRAM frees, 'renders' small files instantly."""
import json
import re
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

MODELS = {
    'diffusion_models': ['minimax_h3_ref2va_pruned_bf16.safetensors', 'minimax_h3_ref2va_pruned_fp8_scaled.safetensors',
                         'qwen_image_2.1_turbo_int8_convrot.safetensors', 'qwen_image_2.1_turbo_bf16.safetensors',
                         'qwen_image_2.1_bf16.safetensors'],
    'text_encoders': ['qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors', 'qwen3vl_8b_int8_convrot.safetensors',
                      'qwen3vl_8b_bf16.safetensors'],
    'vae': ['minimax_h3_video_vae_fp16.safetensors', 'qwen_image_2.1_vae_bf16.safetensors'],
}


class FakeComfy:
    def __init__(self):
        self.prompts = []  # (prompt_id, workflow)
        self.events = []  # 'free' and 'run:<SaveNode>' in order
        self.uploads = {}
        self.history = {}
        self.fail_next = False
        handler = self._handler()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()

    def _finish(self, prompt_id, workflow):
        save = next((k for k, n in workflow.items() if n['class_type'] in ('SaveVideo', 'SaveImage')), None)
        kind = workflow[save]['class_type']
        self.events.append('run:' + kind)
        if self.fail_next:
            self.fail_next = False
            self.history[prompt_id] = {'status': {'status_str': 'error', 'completed': False,
                                                  'messages': [['execution_error', {'exception_message': 'CUDA OOM'}]]}}
            return
        if kind == 'SaveVideo':
            out = {'videos': [{'filename': f'{prompt_id}.mp4', 'subfolder': 'studio', 'type': 'output'}]}
        else:
            count = next(n['inputs']['batch_size'] for n in workflow.values() if n['class_type'] == 'EmptyLatentImage')
            out = {'images': [{'filename': f'{prompt_id}_{i}.png', 'subfolder': 'studio', 'type': 'output'}
                              for i in range(count)]}
        self.history[prompt_id] = {'status': {'status_str': 'success', 'completed': True}, 'outputs': {save: out}}

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def send(self, code, body, ctype='application/json'):
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(code)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                url = urlparse(self.path)
                if url.path == '/object_info':
                    return self.send(200, {})  # empty: schema validation is skipped
                if url.path == '/system_stats':
                    return self.send(200, {'devices': [{'name': 'Fake RTX PRO 6000', 'vram_total': 96 * 1024**3,
                                                         'vram_free': 90 * 1024**3}]})
                if url.path.startswith('/models/'):
                    return self.send(200, MODELS.get(url.path.split('/')[-1], []))
                if url.path.startswith('/history/'):
                    pid = url.path.split('/')[-1]
                    return self.send(200, {pid: fake.history[pid]} if pid in fake.history else {})
                if url.path == '/view':
                    name = parse_qs(url.query)['filename'][0]
                    return self.send(200, b'FAKE-' + name.encode(), 'application/octet-stream')
                self.send(404, {})

            def do_POST(self):
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length)
                if self.path == '/prompt':
                    workflow = json.loads(body)['prompt']
                    pid = uuid.uuid4().hex
                    fake.prompts.append((pid, workflow))
                    fake._finish(pid, workflow)
                    return self.send(200, {'prompt_id': pid, 'node_errors': {}})
                if self.path == '/free':
                    fake.events.append('free')
                    return self.send(200, b'', 'text/plain')
                if self.path == '/interrupt':
                    return self.send(200, b'', 'text/plain')
                if self.path == '/upload/image':
                    name = re.search(rb'filename="([^"]+)"', body).group(1).decode()
                    fake.uploads[name] = len(body)
                    return self.send(200, {'name': name, 'subfolder': '', 'type': 'input'})
                self.send(404, {})

        return Handler
