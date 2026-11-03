"""Run from studio-mcp/: python -m unittest discover -s tests"""
import asyncio
import base64
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from studio import jobs as jobs_module  # noqa: E402
from studio.comfy import Comfy  # noqa: E402
from studio.engines import EngineError  # noqa: E402
from studio.engines.minimax_h3 import MiniMaxH3, frame_count  # noqa: E402
from studio.engines.qwen_image import QwenImage  # noqa: E402
from studio.server import build  # noqa: E402
from studio.settings import Settings  # noqa: E402
from fake_comfy import MODELS, FakeComfy  # noqa: E402

TOKEN = 'test-token-0123456789'


class EngineTest(unittest.TestCase):
    def test_frame_grid(self):
        for seconds in range(4, 16):
            frames = frame_count(seconds)
            self.assertEqual(frames % 17, 5)
            self.assertGreaterEqual(frames, seconds * 24)
        self.assertEqual(frame_count(8), 192)

    def test_minimax_text_only_uses_image_to_video(self):
        wf, meta = MiniMaxH3().build({'prompt': 'p', 'aspect_ratio': '9:16', 'duration': 8, 'quality': 'standard'},
                                     {}, MODELS)
        self.assertEqual(wf['8']['class_type'], 'MiniMaxH3ImageToVideo')
        self.assertEqual((wf['8']['inputs']['width'], wf['8']['inputs']['height']), (768, 1344))
        self.assertEqual(wf['11']['inputs']['steps'], 8)
        self.assertEqual(wf['1']['inputs']['unet_name'], 'minimax_h3_ref2va_pruned_fp8_scaled.safetensors')
        self.assertEqual(meta['frames'], 192)

    def test_minimax_references_and_max_quality(self):
        refs = {'images': ['a.png', 'b.png'], 'videos': [{'file': 'v.mp4', 'has_audio': True}], 'audios': ['s.wav']}
        wf, meta = MiniMaxH3().build({'prompt': 'p', 'quality': 'max', 'ref_image_size': 'match',
                                      'loras': [{'name': 'x.safetensors', 'strength': .7}]}, refs, MODELS)
        node = wf['8']
        self.assertEqual(node['class_type'], 'MiniMaxH3ReferenceToVideo')
        self.assertEqual(node['inputs']['ref_image_size'], 'max')  # max quality protects references
        self.assertEqual(node['inputs']['ref_images.ref_image_1'], ['102', 0])
        self.assertEqual(wf['102']['inputs']['image'], 'b.png')
        self.assertEqual(node['inputs']['ref_videos.ref_video_0'], ['211', 0])
        self.assertEqual(node['inputs']['ref_video_audios.ref_video_audio_0'], ['211', 1])
        self.assertEqual(wf['301']['inputs']['audio'], 's.wav')
        self.assertEqual(wf['9']['inputs']['model'], ['50', 0])
        self.assertEqual(meta['steps'], 10)

    def test_minimax_validation(self):
        with self.assertRaises(EngineError):
            MiniMaxH3().validate({'duration': 20})
        with self.assertRaises(EngineError):
            MiniMaxH3().validate({'images': ['x'] * 10})

    def test_qwen_turbo_graph_quality_and_no_text(self):
        wf, meta = QwenImage().build({'prompt': 'calm desk', 'aspect_ratio': '4:5', 'count': 2}, {}, MODELS)
        self.assertEqual(wf['1']['inputs']['unet_name'], 'qwen_image_2.1_turbo_bf16.safetensors')
        self.assertEqual(wf['2']['inputs']['clip_name'], 'qwen3vl_8b_bf16.safetensors')
        latent = wf['6']['inputs']
        self.assertEqual(latent['batch_size'], 2)
        self.assertTrue(latent['width'] % 32 == 0 and latent['height'] % 32 == 0)
        self.assertAlmostEqual(latent['width'] * latent['height'] / 1024**2, 4.0, delta=.1)  # max = native 2K
        self.assertAlmostEqual(latent['width'] / latent['height'], .8, delta=.01)
        self.assertIn('no text', wf['5']['inputs']['prompt'])  # cfg 1: negative is skipped, so ask in the prompt
        self.assertEqual(wf['10']['inputs']['cfg'], 1.0)
        wf, meta = QwenImage().build({'prompt': 'poster', 'text_ok': True, 'quality': 'draft'}, {}, MODELS)
        self.assertEqual(wf['5']['inputs']['prompt'], 'poster')
        self.assertEqual(meta['megapixels'], 1.0)


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeComfy()
        self.port = free_port()
        self.settings = Settings.from_env(home=Path(self.tmp.name), comfy_url=self.fake.url, token=TOKEN,
                                          host='127.0.0.1', port=self.port, job_timeout=30)
        patcher = patch.object(jobs_module.media, 'make_playable', lambda p: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app, self.studio, _ = build(self.settings, Comfy(self.fake.url), start_worker=False)
        import uvicorn
        self.server = uvicorn.Server(uvicorn.Config(self.app, host='127.0.0.1', port=self.port, log_level='error'))
        threading.Thread(target=self.server.run, daemon=True).start()
        for _ in range(100):
            if self.server.started:
                break
            time.sleep(.05)

    def tearDown(self):
        self.server.should_exit = True
        self.studio.stop = True
        time.sleep(.2)
        self.fake.close()
        self.tmp.cleanup()

    def call(self, tool, args=None, token=TOKEN):
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async def go():
            headers = {'Authorization': 'Bearer ' + token}
            async with streamablehttp_client(f'http://127.0.0.1:{self.port}/mcp', headers=headers,
                                             timeout=timedelta(seconds=10)) as (r, w, _):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    return await session.call_tool(tool, args or {})
        result = asyncio.run(go())
        if result.isError:
            raise RuntimeError(result.content[0].text)
        return result.structuredContent or {}

    def wait_done(self, job_id):
        for _ in range(100):
            job = self.call('get_job', {'job_id': job_id})['job']
            if job['status'] not in ('queued', 'running'):
                return job
            time.sleep(.1)
        self.fail('job did not finish')

    def test_token_required(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/mcp', data=b'{}', method='POST')
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        self.assertEqual(e.exception.code, 401)
        with urllib.request.urlopen(f'http://127.0.0.1:{self.port}/health') as r:
            self.assertEqual(r.status, 200)

    def test_video_with_reference_end_to_end(self):
        asset = self.call('upload_asset', {'base64_data': base64.b64encode(b'png').decode(), 'filename': 'face.png'})
        self.assertEqual(asset['media_type'], 'image')
        job = self.call('generate_omni_video', {'prompt': '<d>[English] Hi</d>', 'images': [asset['asset_id']],
                                                'duration': 8, 'quality': 'high', 'aspect_ratio': '9:16'})
        self.assertEqual(job['status'], 'queued')
        self.studio.start()
        done = self.wait_done(job['job_id'])
        self.assertEqual(done['status'], 'done', done.get('error'))
        self.assertEqual(done['metadata']['references']['images'], 1)
        self.assertTrue(any(name.endswith('_img0.png') for name in self.fake.uploads))
        # Relative signed link, as OtoReklam's client resolves it against the server URL.
        url = done['output_video']
        self.assertTrue(url.startswith('/files/outputs/') and '?sig=' in url)
        with urllib.request.urlopen(f'http://127.0.0.1:{self.port}{url}') as r:
            self.assertTrue(r.read().startswith(b'FAKE-'))
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(f'http://127.0.0.1:{self.port}{url.split("?")[0]}?sig=bad')
        self.assertEqual(e.exception.code, 403)

    def test_batches_by_kind_with_one_vram_switch(self):
        ids = [self.call('generate_video', {'prompt': 'v1'})['job_id'],
               self.call('generate_image', {'prompt': 'i1', 'count': 2})['job_id'],
               self.call('generate_video', {'prompt': 'v2'})['job_id'],
               self.call('generate_image', {'prompt': 'i2'})['job_id']]
        image = self.call('get_job', {'job_id': ids[1]})['job']
        self.assertEqual(image['queue_position'], 3)  # behind both videos
        self.studio.start()
        results = [self.wait_done(i) for i in ids]
        self.assertTrue(all(j['status'] == 'done' for j in results))
        self.assertEqual(self.fake.events, ['run:SaveVideo', 'run:SaveVideo', 'free', 'run:SaveImage', 'run:SaveImage'])
        self.assertEqual(len(results[1]['outputs']), 2)
        self.assertIn('output_image', results[1])

    def test_failure_is_reported_and_retry_works(self):
        self.fake.fail_next = True
        job_id = self.call('generate_image', {'prompt': 'x'})['job_id']
        self.studio.start()
        failed = self.wait_done(job_id)
        self.assertEqual(failed['status'], 'failed')
        self.assertIn('CUDA OOM', failed['error'])
        self.call('retry_job', {'job_id': job_id})
        self.assertEqual(self.wait_done(job_id)['status'], 'done')

    def test_bad_request_is_rejected_before_queueing(self):
        with self.assertRaisesRegex(RuntimeError, 'duration'):
            self.call('generate_video', {'prompt': 'x', 'duration': 30})
        with self.assertRaisesRegex(RuntimeError, 'Asset bulunamadı'):
            self.call('generate_video', {'prompt': 'x', 'images': ['ast_missing']})
        self.assertEqual(self.call('list_jobs')['jobs'], [])

    def test_restart_requeues_running_job(self):
        job_id = self.call('generate_video', {'prompt': 'x'})['job_id']
        job = self.studio.jobs[job_id]
        job['status'] = 'running'
        self.studio._save(job)
        _, again, _ = build(self.settings, Comfy(self.fake.url), start_worker=False)
        self.assertEqual(again.jobs[job_id]['status'], 'queued')

    def test_status_and_models(self):
        status = self.call('server_status')
        self.assertTrue(status['comfyui']['online'])
        self.assertEqual(status['comfyui']['devices'][0]['vram_gb'], 96.0)
        names = [m['name'] for m in self.call('list_models')['models']]
        self.assertEqual(names, ['minimax_h3', 'qwen_image'])


if __name__ == '__main__':
    unittest.main()
