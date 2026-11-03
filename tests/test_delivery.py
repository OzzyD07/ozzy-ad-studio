import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

import delivery
import pipeline


def job(ws, identity, day, *, folder='jobs', video=None, selected=None, **extra):
    data = {'id': identity, 'date': day, 'status': 'done' if video else 'planned', 'angle': 'Angle ' + identity,
            'caption': 'Caption #tag', 'cta': 'Try Demo', **extra}
    if video:
        out = ws/'exports'/identity
        out.mkdir(parents=True)
        (out/'video.mp4').write_bytes(video)
        data['export'] = str(out)
    if selected is not None:
        data['selected_for_publication'] = selected
    pipeline.write(ws/folder/f'{identity}.json', data)
    return data


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)/'apps'/'demo'
        pipeline.write(self.ws/'product.json', {'name': 'Demo', 'url': 'https://play.example/demo',
                                                'ios_url': 'https://apps.example/demo'})
        self.cfg = {'app': {'slug': 'demo', 'name': 'Demo', 'product': 'product.json',
                            'delivery_dir': str(Path(self.tmp.name)/'out'),
                            'publish': {'time': '19:00', 'timezone': 'America/New_York',
                                        'local_timezone': 'Europe/Istanbul'}}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_publish_slot_follows_daylight_saving(self):
        self.assertEqual(delivery.convert('2026-10-31', '19:00', 'America/New_York', 'Europe/Istanbul'),
                         datetime(2026, 11, 1, 2, 0))
        self.assertEqual(delivery.convert('2026-11-01', '19:00', 'America/New_York', 'Europe/Istanbul'),
                         datetime(2026, 11, 2, 3, 0))
        self.assertEqual(delivery.convert('2026-07-01', '09:00', 'Europe/Istanbul', 'Europe/London'),
                         datetime(2026, 7, 1, 7, 0))

    def test_platform_captions(self):
        product = {'url': 'https://play.example/demo', 'ios_url': 'https://apps.example/demo'}
        job_data = {'caption': 'Every entry is a star. Watch it fill up. #journaling #MentorAi\n'
                               'Android: https://play.example/demo', 'angle': 'Stars'}
        got = {k: v[1] for k, v in delivery.platform_captions(job_data, product).items()}
        self.assertEqual(got['tiktok'], 'Every entry is a star. Watch it fill up. #journaling #MentorAi\n\nApp link in bio.')
        self.assertTrue(got['instagram'].endswith('\n\n#journaling #MentorAi'))
        self.assertTrue(got['youtube'].startswith('Every entry is a star. #Shorts\n'))
        self.assertIn('iOS: https://apps.example/demo', got['youtube'])
        self.assertEqual(got['ad'], 'Every entry is a star. Watch it fill up.')
        self.assertNotIn('http', got['tiktok'] + got['instagram'])
        long = delivery.platform_captions({'caption': 'x' * 120, 'captions': {'ad': 'Short ad.'}}, product)
        self.assertEqual(long['ad'][1:], ('Short ad.', []))  # a job can override any platform text

    def test_select_deliver_and_board(self):
        ws = self.ws
        job(ws, 'd1', '2026-11-01', video=b'one', selected='True')  # old string flag still counts
        job(ws, 'd2-A', '2026-11-02', video=b'a', variant='A')
        job(ws, 'd2-B-r2', '2026-11-02', folder='revisions/r2/jobs', video=b'b', variant='B', hook_text='Hook B')
        job(ws, 'd2-s2', '2026-11-02', role='shot', video=b'shot')
        job(ws, 'd3', '2026-11-03')
        job(ws, 'gone', '2026-11-04', status='removed_by_cleanup')
        plan = delivery.days(ws)
        self.assertEqual(list(plan), ['2026-11-01', '2026-11-02', '2026-11-03'])
        self.assertIsNone(plan['2026-11-02']['selected'])
        with self.assertRaises(ValueError):
            delivery.select(ws, 'd3')  # nothing rendered yet
        delivery.select(ws, 'd2-B-r2')
        delivery.select(ws, 'd2-A')
        flags = {j['id']: j.get('selected_for_publication') for j in delivery.ad_jobs(ws)}
        self.assertEqual((flags['d2-A'], flags['d2-B-r2']), (True, False))
        out = Path(self.cfg['app']['delivery_dir'])
        (out/'99_old').mkdir(parents=True)
        manifest = delivery.deliver(ws, self.cfg)
        self.assertEqual([m['folder'] for m in manifest], ['01_2026-11-01', '02_2026-11-02'])
        self.assertEqual((out/'02_2026-11-02'/'video.mp4').read_bytes(), b'a')
        caption = (out/'01_2026-11-01'/'aciklama.txt').read_text(encoding='utf-8')
        self.assertEqual(caption, 'Caption #tag\nAndroid: https://play.example/demo\niOS: https://apps.example/demo')
        self.assertEqual(manifest[0]['publish_local'], '2026-11-02T03:00')
        self.assertIn('App link in bio.', (out/'01_2026-11-01'/'aciklama-tiktok.txt').read_text(encoding='utf-8'))
        self.assertTrue((out/'99_old').exists())  # never deletes
        delivery.select(ws, 'd2-B-r2')
        delivery.deliver(ws, self.cfg)
        self.assertEqual((out/'02_2026-11-02'/'video.mp4').read_bytes(), b'b')
        page = delivery.board(ws, self.cfg).read_text(encoding='utf-8')
        self.assertEqual(page.count('<article'), 3)
        self.assertIn('Hook B', page)
        self.assertIn('<span class="tag">#tag</span>', page)
        self.assertIn('2 Kas Pzt 03.00', page)
        self.assertIn('Planlandı', page)
        for src in __import__('re').findall(r'<video[^>]* src="([^"]+)"', page):
            self.assertTrue((ws/unquote(src)).resolve().is_file(), src)
        self.assertNotIn('d2-s2', page)
        self.assertEqual(json.loads((out/'teslim.json').read_text(encoding='utf-8'))['items'][1]['id'], 'd2-B-r2')


if __name__ == '__main__':
    unittest.main()
