import tempfile
import unittest
from datetime import date
from pathlib import Path

import delivery
import pipeline
import strategy
import takvim
from tests.test_formats import CAROUSEL, POST, PROMO, VIDEO

CFG = {'calendar': {'per_day': 2, 'budget': {'ai_videos_per_week': 1, 'images_per_day': 2}}}


def plan(ws, scripts, days, cfg=CFG):
    p, r = ws/'product.json', ws/'research.json'
    pipeline.write(p, {'name': 'Demo', 'language': 'en', 'audience': 'u', 'features': ['f'], 'cta': 'Try Demo',
                       'url': 'https://example.com', 'scripts': scripts})
    pipeline.write(r, {'findings': [{'finding': 'x', 'implication': 'y', 'url': 'https://e.com', 'checked_on': '2026-11-01'}]})
    pipeline.plan(p, r, '2026-11-05', days, ws, cfg)
    return sorted(map(pipeline.read, (ws/'jobs').glob('*.json')), key=lambda j: (j['date'], j.get('slot') or ''))


class TakvimTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_assign_two_slots_a_day(self):
        scripts = [{'angle': str(k)} for k in range(4)] + [{'angle': 'x', 'slot': 'gece'}]
        out = takvim.assign(scripts[:4], 2, 2, CFG)
        self.assertEqual([(d, s) for _, d, s, _ in out], [(0, 'sabah'), (0, 'aksam'), (1, 'sabah'), (1, 'aksam')])
        self.assertEqual(takvim.assign([scripts[4], scripts[0]], 1, 2, CFG)[0][2], 'gece')  # own slot wins
        with self.assertRaisesRegex(ValueError, 'en az 6'):
            takvim.assign(scripts, 3, 2, CFG)
        self.assertEqual(takvim.per_day({}, None), 1)  # no calendar: the old one-a-day plan
        self.assertEqual(takvim.per_day(CFG, None), 2)

    def test_plan_two_a_day_with_slots_and_budget(self):
        jobs = plan(self.ws, [POST, VIDEO, CAROUSEL, {**VIDEO, 'angle': 'Video 2'}], 2)
        self.assertEqual([(j['date'], j['slot']) for j in jobs],
                         [('2026-11-05', 'aksam'), ('2026-11-05', 'sabah'), ('2026-11-06', 'aksam'), ('2026-11-06', 'sabah')])
        md = next((self.ws/'plans').glob('plan-*.md')).read_text(encoding='utf-8')
        self.assertIn('2 posts a day', md)
        self.assertIn('## 2026-11-05 · sabah — Tip (image_post)', md)
        self.assertIn('## GPU bütçesi', md)
        self.assertIn('Video üretimi (MiniMax çekimi): 2 · görsel üretimi (Qwen): 2', md)
        self.assertIn('2 video üretimi (bütçe 1/hafta)', md)  # two videos in one ISO week, budget 1
        csv_text = next((self.ws/'plans').glob('calendar-*.csv')).read_text(encoding='utf-8-sig')
        self.assertIn('slot,format', csv_text.splitlines()[0])

    def test_budget_counts_generations_not_montages(self):
        jobs = [{'date': '2026-11-05', 'prompt': 'p'}, {'date': '2026-11-05', 'role': 'edit', 'prompt': 'p'},
                {'date': '2026-11-05', 'prompt': 'p', 'source': 'clip'},
                {'date': '2026-11-05', 'format': 'carousel', 'slides': [{'image_prompt': 'a'}, {}, {'image_prompt': 'b'}]},
                {'date': '2026-11-05', 'format': 'template_video'}]
        lines, warnings = takvim.budget(jobs, CFG)
        self.assertIn('Video üretimi (MiniMax çekimi): 1 · görsel üretimi (Qwen): 2', '\n'.join(lines))
        self.assertEqual(warnings, [])

    def test_suggest_falls_back_when_video_budget_is_spent(self):
        rows = takvim.suggest(date(2026, 11, 2), 3, 2, CFG)  # a Monday: one ISO week
        evening = [f for _, slot, f in rows if slot == 'aksam']
        self.assertEqual(evening.count('ai_video'), 1)
        self.assertTrue(all(f in ('image_post', 'carousel', 'template_video') for _, s, f in rows if s == 'sabah'))
        lines = strategy.slot_plan(date(2026, 11, 2), 3, 2, CFG)
        self.assertIn('| 2026-11-02 | sabah | 09:00 |', '\n'.join(lines))

    def test_delivery_and_board_handle_two_slots_and_images(self):
        ws = self.ws
        jobs = plan(ws, [POST, PROMO, CAROUSEL, PROMO | {'angle': 'Promo 2'}], 2)
        # Pretend the queue finished them: post.png, video.mp4 and carousel slides.
        for job in jobs:
            out = ws/'exports'/job['id']
            out.mkdir(parents=True)
            if job['format'] == 'image_post':
                (out/'post.png').write_bytes(b'post')
            elif job['format'] == 'carousel':
                for k in (1, 2, 3):
                    (out/f'{k:02}.png').write_bytes(b'slide%d' % k)
            else:
                (out/'video.mp4').write_bytes(b'video')
            data = pipeline.read(ws/'jobs'/f"{job['id']}.json")
            data.update(status='done', export=str(out))
            pipeline.write(ws/'jobs'/f"{job['id']}.json", data)
        for job in jobs:
            delivery.select(ws, job['id'])
        cfg = {**CFG, 'app': {'slug': 'demo', 'delivery_dir': str(ws/'teslim'),
                              'publish': {'time': '19:00', 'timezone': 'Europe/Istanbul'}}}
        plan_days = delivery.days(ws, cfg)
        self.assertEqual(list(plan_days), ['2026-11-05 sabah', '2026-11-05 aksam', '2026-11-06 sabah', '2026-11-06 aksam'])
        self.assertTrue(all(info['selected'] for info in plan_days.values()))  # selecting one slot keeps the other
        manifest = delivery.deliver(ws, cfg)
        folders = {m['folder']: m for m in manifest}
        self.assertEqual(folders['01_2026-11-05_sabah']['files'], ['post.png'])
        self.assertEqual(folders['03_2026-11-06_sabah']['files'], ['01.png', '02.png', '03.png'])
        self.assertEqual(folders['02_2026-11-05_aksam']['publish_local'], '2026-11-05T19:00')
        self.assertEqual(folders['01_2026-11-05_sabah']['publish_local'], '2026-11-05T09:00')
        sabah, aksam = ws/'teslim'/'01_2026-11-05_sabah', ws/'teslim'/'02_2026-11-05_aksam'
        self.assertFalse((sabah/'aciklama-youtube.txt').exists())  # no Shorts copy for a still post
        self.assertTrue((aksam/'aciklama-youtube.txt').exists())
        page = delivery.board(ws, cfg).read_text(encoding='utf-8')
        self.assertIn('4 gönderi', page)
        self.assertIn('Instagram gönderi', page)
        self.assertIn('class="post"', page)
        self.assertEqual(page.count('alt="slayt'), 3)
        self.assertIn('Carousel · sabah', page)


if __name__ == '__main__':
    unittest.main()
