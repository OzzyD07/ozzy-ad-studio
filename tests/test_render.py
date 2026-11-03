import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import render


class RenderBridgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_words_from_segments_uses_word_timings_or_estimates(self):
        timed = [{'start': 0, 'end': 1, 'text': 'hi there', 'words': [
            {'start': 0, 'end': .4, 'text': ' hi'}, {'start': .5, 'end': 1, 'text': ' there'}]}]
        self.assertEqual(render.words_from_segments(timed),
                         [{'text': 'hi', 'start': 0, 'end': .4}, {'text': 'there', 'start': .5, 'end': 1}])
        estimated = render.words_from_segments([{'start': 0, 'end': 2, 'text': 'one two'}])
        self.assertEqual([w['text'] for w in estimated], ['one', 'two'])
        self.assertEqual(estimated[-1]['end'], 2)

    def test_stage_links_local_files_once_and_keeps_urls(self):
        (self.dir/'a.mp4').write_bytes(b'x')
        public = self.dir/'public'
        props = {'clips': [{'src': 'a.mp4'}, {'src': 'a.mp4'}], 'theme': {'primary': '#fff'},
                 'endCard': {'icon': 'https://example.com/i.png', 'badges': ['a.mp4'], 'appName': 'a.mp4'}}
        staged = render.stage(props, public, self.dir)
        self.assertEqual(staged['clips'][0]['src'], 'm/00-a.mp4')
        self.assertEqual(staged['clips'][1]['src'], 'm/00-a.mp4')
        self.assertEqual(staged['endCard']['badges'], ['m/00-a.mp4'])
        self.assertEqual(staged['endCard']['icon'], 'https://example.com/i.png')
        self.assertEqual(staged['endCard']['appName'], 'a.mp4')  # not a media key
        self.assertTrue((public/'m'/'00-a.mp4').is_file())

    def test_stage_missing_file_is_an_error(self):
        with self.assertRaises(FileNotFoundError):
            render.stage({'background': 'nope.png'}, self.dir/'public', self.dir)

    def test_defaults_null_optional_fields_and_fill_end_card(self):
        cfg = {'end_card': {'enabled': True, 'seconds': 3, 'extend_seconds': 1.5, 'stores': []},
               'app': {'name': 'MentorAi'}, 'cta': {'text': 'Try it free'}, 'whisper': {'language': 'en'},
               'edit': {'transition': 'slide', 'transition_seconds': .5}, 'theme': {'primary': '#123456'}}
        (self.dir/'x.mp4').write_bytes(b'x')
        with patch('render.media.media_duration', return_value=6.0):
            props = render.with_defaults('AdVideo', {'clips': [{'src': 'x.mp4', 'trimBefore': 1}],
                                                     'captions': {'words': []}}, cfg, self.dir, self.dir)
        self.assertIsNone(props['hookText'])
        self.assertIsNone(props['music'])
        self.assertEqual(props['clips'][0]['duration'], 5.0)
        self.assertEqual(props['transition'], {'type': 'slide', 'seconds': .5})
        self.assertEqual(props['captions']['language'], 'en')
        self.assertEqual(props['theme'], {'primary': '#123456'})
        self.assertEqual(props['endCard'], {'seconds': 3, 'extendSeconds': 1.5, 'appName': 'MentorAi',
                                            'headline': 'Try it free'})

    def test_end_card_can_be_turned_off(self):
        cfg = {'end_card': {'enabled': True}}
        props = render.with_defaults('TemplatePromo', {'scenes': [], 'endCard': None}, cfg, self.dir, self.dir)
        self.assertIsNone(props['endCard'])
        props = render.with_defaults('TemplatePromo', {'scenes': []}, {'end_card': {'enabled': False}}, self.dir, self.dir)
        self.assertIsNone(props['endCard'])

    def test_unknown_composition(self):
        with self.assertRaises(ValueError):
            render.render('Nope', {}, self.dir/'x.mp4', {})


if __name__ == '__main__':
    unittest.main()
