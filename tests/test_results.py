import tempfile
import unittest
from pathlib import Path

import delivery
import pipeline
import results


def ad(ws, identity, day, variant=None, selected=None):
    data = {'id': identity, 'date': day, 'status': 'done', 'caption': 'c', 'variant': variant}
    if selected is not None:
        data['selected_for_publication'] = selected
    pipeline.write(ws/'jobs'/f'{identity}.json', data)


class ResultTests(unittest.TestCase):
    def test_numbers_in_platform_formats(self):
        for text, value in [('1,234', 1234), ('1.234', 1234), ('1.234,5', 1234.5), ('12.5%', 12.5), ('$3.20', 3.2),
                            ('0,8', .8), ('', None), ('-', None), ('2,000,000', 2000000)]:
            self.assertEqual(results.number(text), value, text)

    def test_import_matches_rows_and_advises(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            ad(ws, '2026-11-01-aaaa', '2026-11-01')
            ad(ws, '2026-11-02-bbbb-A', '2026-11-02', 'A')
            ad(ws, '2026-11-02-bbbb-B-r2', '2026-11-02', 'B', selected=True)
            ad(ws, '2026-11-03-cccc', '2026-11-03')
            ad(ws, '2026-11-04-dddd', '2026-11-04')
            meta = ws/'meta.csv'
            meta.write_text(
                'Ad name,Impressions,3-second video plays,ThruPlays,Link clicks,Amount spent (USD),App installs\n'
                'MentorAi 2026-11-01-aaaa,4000,800,200,20,30.00,6\n'          # hook 20% → hook
                'MentorAi 11-02 A,5000,2000,100,60,40,8\n'                    # hold 5% → hold
                'MentorAi 11-02 B,5000,2000,600,20,40,4\n'                    # ctr 0.4% → cta
                'Nov 3 sky ad,3000,1500,500,40,10,2\n'                        # no id/date → unmatched
                'Total,17000,,,,,\n', encoding='utf-8')
            report, unmatched = results.import_results(ws, meta)
            got = {a['id']: e['advice'] for a, e in report}
            self.assertEqual(got, {'2026-11-01-aaaa': 'hook', '2026-11-02-bbbb-A': 'hold', '2026-11-02-bbbb-B-r2': 'cta'})
            self.assertEqual(unmatched, ['Nov 3 sky ad'])
            first = pipeline.read(ws/'jobs'/'2026-11-01-aaaa.json')['results'][0]
            self.assertAlmostEqual(first['hook_rate'], .2)
            self.assertAlmostEqual(first['cpi'], 5.0)
            tiktok = ws/'tiktok.csv'
            tiktok.write_text('Reklam adı;Gösterimler;2-second video views;6-second video views;Tıklamalar;Maliyet\n'
                              '0311 sky;12.000;6.000;2.400;150;55,5\n'
                              '04.11 breath;400;200;80;4;3\n', encoding='utf-8')
            report, unmatched = results.import_results(ws, tiktok)
            got = {a['id']: (e['advice'], e['impressions']) for a, e in report}
            self.assertEqual(got, {'2026-11-03-cccc': ('scale', 12000), '2026-11-04-dddd': ('wait', 400)})
            self.assertEqual(len(pipeline.read(ws/'jobs'/'2026-11-01-aaaa.json')['results']), 1)
            cfg = {'app': {'slug': 'demo', 'name': 'Demo'}}
            page = delivery.board(ws, cfg).read_text(encoding='utf-8')
            self.assertIn('12.000 gösterim', page)
            self.assertIn('Hook zayıf', page)


if __name__ == '__main__':
    unittest.main()
