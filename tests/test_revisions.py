import tempfile
import unittest
from pathlib import Path

import minimax
import pipeline
import revisions

SHOT = {'duration': 15, 'camera': ['Push in'], 'visual': 'She lights a lamp, writes, then looks outside.',
        'beats': ['0-3 s: she lights the lamp.', '3-10 s: she writes.', '10-15 s: she looks outside.']}
PRODUCT = {
    'name': 'DemoApp', 'audience': 'adults', 'features': ['journal'], 'cta': 'Try DemoApp',
    'url': 'https://example.com', 'language': 'en',
    'scripts': [
        {**SHOT, 'angle': 'single', 'caption': 'c #tag', 'hook': 'Evenings got darker.',
         'voiceover': 'Evenings got darker. Write three lines tonight and see one small next step. Try DemoApp.'},
        {'angle': 'multi', 'caption': 'c', 'hooks': [
            {'duration': 6, 'camera': ['Push in'], 'visual': 'A star goes up.', 'voiceover': 'A star goes up.'},
            {'duration': 6, 'camera': ['Tilt up'], 'visual': 'Stars blink on.', 'voiceover': 'Your ceiling is a diary.'}],
         'shots': [{'duration': 12, 'camera': ['Pull out'], 'visual': 'The ceiling glows.',
                    'voiceover': 'Every entry lights a star. Try DemoApp.'}]}]}


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        pipeline.write(self.ws/'product.json', PRODUCT)
        pipeline.write(self.ws/'research.json', {'findings': [
            {'finding': 'f', 'implication': 'i', 'url': 'https://example.com', 'checked_on': '2026-10-29'}]})
        pipeline.plan(self.ws/'product.json', self.ws/'research.json', '2026-11-01', 2, self.ws)
        self.jobs = {j['id']: j for j in map(pipeline.read, (self.ws/'jobs').glob('*.json'))}

    def tearDown(self):
        self.tmp.cleanup()

    def find(self, suffix):
        return next(i for i in self.jobs if i.endswith(suffix))

    def test_split_single_ad_into_continuous_montage(self):
        single = next(i for i, j in self.jobs.items() if j['date'] == '2026-11-01')
        out = {j['id']: j for j in revisions.split(self.ws, single, [8, 8], 'DemoApp', note='too long')}
        p1, p2, montage = out[f'{single}-r2-p1'], out[f'{single}-r2-p2'], out[f'{single}-r2']
        self.assertEqual(montage['shots'], [p1['id'], p2['id']])
        self.assertEqual((montage['role'], montage['caption'], montage['revision_note']), ('edit', 'c #tag\nAndroid: https://example.com', 'too long'))
        self.assertEqual(p1['voiceover'] + ' ' + p2['voiceover'], self.jobs[single]['voiceover'])
        self.assertEqual((p2['continuity_from'], p2['voice_from_previous'], p2['transition']), (p1['id'], True, 'cut'))
        self.assertIn('8-second', p2['prompt'])
        self.assertIn('Continuing the same moment: she looks outside.', p2['prompt'])
        self.assertIn('<Picture 1> is the last frame of the previous shot', p2['prompt'])
        self.assertIn('timbre of <Audio 1>', p2['prompt'])
        self.assertNotIn('Opening hook', p2['prompt'])
        self.assertNotIn('The final seconds', p1['prompt'])
        self.assertIn(f"<d>[English] {p2['voiceover']}</d>", p2['prompt'])
        self.assertEqual(self.jobs[single], pipeline.read(self.ws/'jobs'/f'{single}.json'))  # original kept
        self.assertEqual(pipeline.complete(montage), False)
        with self.assertRaises(ValueError):
            revisions.split(self.ws, self.find('-ha'), [4, 4])  # one sentence cannot be split

    def test_revise_hook_with_chain_rebuilds_body_and_montages(self):
        hook = self.find('-ha')
        out = {j['id']: j for j in revisions.revise(self.ws, hook, 'DemoApp', 'arm repeated',
                                                       'Her arm moves once.', chain=True)}
        body = out[self.find('-s2') + '-r2']
        self.assertEqual(body['continuity_from'], hook + '-r2')
        self.assertIn('Her arm moves once.\n' + minimax.RULES, out[hook + '-r2']['prompt'])
        montages = sorted(i for i, j in out.items() if j.get('role') == 'edit')
        self.assertEqual(len(montages), 2)
        a = out[next(m for m in montages if '-A-' in m)]
        self.assertEqual(a['shots'], [hook + '-r2', body['id']])
        self.assertFalse(a['selected_for_publication'] if 'selected_for_publication' in a else False)
        second = revisions.revise(self.ws, hook)
        self.assertEqual(second[0]['id'], hook + '-r3')

    def test_revise_rejects_montages(self):
        with self.assertRaises(ValueError):
            revisions.revise(self.ws, self.find('-A'))


if __name__ == '__main__':
    unittest.main()
