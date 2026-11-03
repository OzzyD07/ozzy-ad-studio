import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import formats
import pipeline

ROOT = Path(__file__).resolve().parent.parent

VIDEO = {'angle': 'Video', 'hook': 'Hook?', 'voiceover': 'Hook? Try Demo.', 'visual': 'Desk.', 'caption': 'Video caption'}
POST = {'format': 'image_post', 'angle': 'Tip', 'caption': 'Post caption',
        'image_prompt': 'A calm desk by a window', 'post': {'kicker': 'Tip', 'title': 'One line a *day*'}}
CAROUSEL = {'format': 'carousel', 'angle': 'Signs', 'caption': 'Swipe',
            'slides': [{'title': '3 signs', 'layout': 'center'},
                       {'title': 'Days blur', 'image_prompt': 'Blurred city lights'},
                       {'title': 'Start tonight', 'brand': True, 'cta': 'Try free'}]}
PROMO = {'format': 'template_video', 'angle': 'Promo', 'caption': 'Promo caption',
         'promo': {'scenes': [{'duration': 2, 'title': 'Hi'}], 'voiceover': {'text': 'Hi there.'}}}


def plan(ws, scripts):
    p, r = ws/'product.json', ws/'research.json'
    pipeline.write(p, {'name': 'Demo', 'language': 'en', 'audience': 'u', 'features': ['f'], 'cta': 'Try Demo',
                       'url': 'https://example.com', 'scripts': scripts})
    pipeline.write(r, {'findings': [{'finding': 'x', 'implication': 'y', 'url': 'https://e.com', 'checked_on': '2026-11-01'}]})
    pipeline.plan(p, r, '2026-11-05', len(scripts), ws)
    return {j['angle']: j for j in map(pipeline.read, (ws/'jobs').glob('*.json'))}


def mock_cfg(ws, image):
    """config with the stdio test MCP server; its generate_image returns the given local file."""
    cfg = pipeline.config(ROOT/'config.example.json')
    cfg['workspace'] = str(ws)
    cfg['mcp'].update(transport='stdio', command=sys.executable, args=[str(ROOT/'tests'/'mock_mcp.py')],
                      env={'TEST_IMAGE_PATH': str(image), 'TEST_VIDEO_PATH': str(image)}, timeout_seconds=30,
                      status_tool='get_job', status_arguments={'job_id': '{{remote_id}}'}, remote_id_path='job_id')
    return cfg


class FormatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_plan_mixes_formats(self):
        jobs = plan(self.ws, [{**VIDEO, 'cuts': [{'name': 'video'}, {'name': 'b', 'trim': [0, 6]}]}, POST, CAROUSEL, PROMO])
        self.assertEqual(formats.fmt(jobs['Video']), 'ai_video')
        self.assertEqual(jobs['Video']['cuts'][1]['trim'], [0, 6])
        self.assertNotIn('cuts', jobs['Tip'])
        self.assertEqual(jobs['Tip']['format'], 'image_post')
        self.assertEqual(jobs['Tip']['aspect_ratio'], '4:5')
        self.assertEqual(len(jobs['Signs']['slides']), 3)
        self.assertEqual(jobs['Promo']['promo']['voiceover']['text'], 'Hi there.')
        self.assertTrue(all(j['status'] == 'planned' for j in jobs.values()))
        md = next((self.ws/'plans').glob('plan-*.md')).read_text(encoding='utf-8')
        self.assertIn('(carousel)', md)

    def test_plan_rejects_bad_format_entries(self):
        for bad, msg in [({**POST, 'post': {}}, 'post.title'), ({**CAROUSEL, 'slides': [{'title': 'x'}]}, '2–10'),
                         ({**PROMO, 'promo': {}}, 'promo.scenes'), ({**POST, 'format': 'reel'}, 'bilinmeyen')]:
            with self.subTest(msg), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaisesRegex(ValueError, msg):
                    plan(Path(tmp), [bad])

    def test_image_post_generates_downloads_and_renders(self):
        jobs = plan(self.ws, [POST])
        image = self.ws/'fixture.png'
        image.write_bytes(b'png')
        cfg = mock_cfg(self.ws, image)
        path = pipeline.job_path(self.ws, jobs['Tip']['id'])
        with patch('render.render') as render:
            render.side_effect = lambda comp, props, out, cfg, base: Path(out).write_bytes(b'x') or [out]
            formats.run(pipeline.read(path), path, cfg, self.ws)  # submit
            job = pipeline.read(path)
            self.assertEqual(job['status'], 'waiting')
            self.assertTrue(job['image_remote_id'].startswith('img_'))
            formats.run(job, path, cfg, self.ws)  # poll, download, render
        job = pipeline.read(path)
        self.assertEqual(job['status'], 'done')
        comp, props = render.call_args.args[:2]
        self.assertEqual(comp, 'PostStill')
        self.assertEqual(props['title'], 'One line a *day*')
        self.assertTrue(Path(props['background']).is_file())
        self.assertNotIn('appName', props)  # no app configured: empty brand fields are left out
        self.assertTrue((Path(job['export'])/'caption.txt').read_text(encoding='utf-8').startswith('Post caption'))

    def test_carousel_waits_for_every_slide_image(self):
        jobs = plan(self.ws, [CAROUSEL])
        image = self.ws/'fixture.png'
        image.write_bytes(b'png')
        cfg = mock_cfg(self.ws, image)
        cfg['app'] = {'name': 'Demo'}
        path = pipeline.job_path(self.ws, jobs['Signs']['id'])
        with patch('render.render') as render:
            formats.run(pipeline.read(path), path, cfg, self.ws)
            self.assertFalse(render.called)  # slide 2 image still pending
            formats.run(pipeline.read(path), path, cfg, self.ws)
        comp, props, out = render.call_args.args[:3]
        self.assertEqual(comp, 'Carousel')
        slides = props['slides']
        self.assertNotIn('background', slides[0])
        self.assertTrue(Path(slides[1]['background']).is_file())
        self.assertNotIn('image_prompt', slides[1])
        self.assertEqual(slides[2]['appName'], 'Demo')  # brand: true adds the app name
        self.assertEqual(pipeline.read(path)['status'], 'done')

    def test_template_video_renders_without_gpu(self):
        jobs = plan(self.ws, [PROMO])
        path = pipeline.job_path(self.ws, jobs['Promo']['id'])
        with patch('render.render') as render:
            formats.run(pipeline.read(path), path, {'workspace': str(self.ws)}, self.ws)
        self.assertEqual(render.call_args.args[0], 'TemplatePromo')
        self.assertEqual(render.call_args.args[2].name, 'video.mp4')

    def test_cuts_share_footage_with_own_trim_hook_and_style(self):
        job = {'id': 'x', 'raw_video': 'raw.mp4', 'cta': 'Try', 'app_name': 'Demo', 'hook_text': 'Default hook',
               'emphasis': ['line']}
        words = [{'text': w, 'start': i, 'end': i + .8} for i, w in enumerate('one two three four five six'.split())]
        cfg = {'subtitles': {'style': 'pop'}}
        full = formats.cut_props(job, {}, words, 'en', cfg)
        self.assertEqual(full['clips'], [{'src': 'raw.mp4', 'trimBefore': 0.0}])
        self.assertEqual(full['hookText'], 'Default hook')
        self.assertEqual(full['captions']['style'], 'pop')
        short = formats.cut_props(job, {'trim': [2, 5], 'hook_text': 'POV', 'caption_style': 'hormozi'}, words, 'en', cfg)
        self.assertEqual(short['clips'][0], {'src': 'raw.mp4', 'trimBefore': 2.0, 'duration': 3.0})
        self.assertEqual([w['text'] for w in short['captions']['words']], ['three', 'four', 'five'])
        self.assertEqual(short['captions']['words'][0]['start'], 0)  # timings shift with the trim
        self.assertEqual((short['hookText'], short['captions']['style']), ('POV', 'hormozi'))
        self.assertIn('Demo', short['captions']['emphasis'])
        # 3 s cut, speech to 2.8 s, +1.5 s hold: the card waits for the speech but stays ≥ 2 s.
        self.assertEqual(short['endCard'], {'headline': 'Try', 'appName': 'Demo', 'seconds': 2.0})
        card = {'end_card': {'seconds': 3, 'extend_seconds': 1.5}}
        self.assertNotIn('seconds', formats.cut_props(job, {}, words, 'en', card)['endCard'])  # length unknown
        roomy = formats.cut_props(job, {}, [{'text': 'hi', 'start': 0, 'end': .5}], 'en', card, duration=6)
        self.assertEqual(roomy['endCard']['seconds'], 3.0)  # speech ends early: the configured 3 s

    def test_ffmpeg_engine_refuses_cuts(self):
        ws = self.ws
        (ws/'jobs').mkdir()
        pipeline.write(ws/'jobs'/'v.json', {'id': 'v', 'status': 'raw_ready', 'raw_video': 'x.mp4', 'cuts': [{}]})
        args = type('A', (), {'id': 'v', 'srt': None, 'no_subtitles': False})()
        with self.assertRaisesRegex(ValueError, 'remotion'):
            pipeline.render_job(args, {'render': {'engine': 'ffmpeg'}}, ws)


if __name__ == '__main__':
    unittest.main()
