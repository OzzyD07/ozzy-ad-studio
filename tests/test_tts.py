import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as Tok
from unittest.mock import patch

import render
import tts


class TtsTest(unittest.TestCase):
    def test_merge_tokens_attaches_punctuation_and_offsets(self):
        tokens = [Tok(text='blurry', whitespace='', start_ts=.9, end_ts=1.5),
                  Tok(text='?', whitespace=' ', start_ts=1.5, end_ts=1.7),
                  Tok(text='Write', whitespace=' ', start_ts=1.7, end_ts=2.0),
                  Tok(text='skip', whitespace=' ', start_ts=None, end_ts=None)]
        self.assertEqual(tts.merge_tokens(tokens, 10), [
            {'text': 'blurry?', 'start': 10.9, 'end': 11.7}, {'text': 'Write', 'start': 11.7, 'end': 12.0}])

    def test_pronunciations_only_whole_words_with_phonemes(self):
        out = tts.with_pronunciations('MentorAi, not MentorAis.', {'MentorAi': '/mˈɛntɔɹ ˌAˈI/', 'not': 'nought'})
        self.assertEqual(out, '[MentorAi](/mˈɛntɔɹ ˌAˈI/), not MentorAis.')

    def test_turkish_is_off_by_default(self):
        with self.assertRaisesRegex(ValueError, 'Türkçe seslendirme kapalı'):
            tts.speak('Merhaba', 'x.wav', {}, language='tr')

    def test_voice_must_match_language(self):
        with self.assertRaises(ValueError):
            tts.speak('Hola', 'x.wav', {}, language='en', voice='ef_dora')


class VoiceoverPropsTest(unittest.TestCase):
    spoken = {'audio': 'C:/v.wav', 'duration': 5.6, 'engine': 'kokoro', 'voice': 'af_heart',
              'words': [{'text': 'Hi', 'start': .2, 'end': .5}]}

    def run_voiceover(self, props, cfg=None):
        with tempfile.TemporaryDirectory() as tmp, patch('tts.speak', return_value=self.spoken) as speak:
            render.voiceover(props, cfg or {'subtitles': {'style': 'hormozi'}}, Path(tmp))
        return speak

    def test_text_becomes_audio_and_captions(self):
        props = {'voiceover': {'text': 'Hi', 'voice': 'am_michael'}, 'captions': {'emphasis': ['Hi']}}
        speak = self.run_voiceover(props)
        self.assertEqual(speak.call_args.kwargs['voice'], 'am_michael')
        self.assertEqual(props['voiceover'], {'src': 'C:/v.wav', 'volume': 1})
        self.assertEqual(props['captions'], {'style': 'hormozi', 'emphasis': ['Hi'], 'language': 'en',
                                             'words': self.spoken['words']})

    def test_captions_null_stays_off_and_src_is_untouched(self):
        props = {'voiceover': {'text': 'Hi'}, 'captions': None}
        self.run_voiceover(props)
        self.assertIsNone(props['captions'])
        props = {'voiceover': {'src': 'a.wav', 'text': 'Hi'}}
        self.assertFalse(self.run_voiceover(props).called)

    def test_fit_scenes_to_speech(self):
        props = {'voiceover': {'text': 'Hi'}, 'fitToVoiceover': True, 'transition': {'type': 'fade', 'seconds': .5},
                 'scenes': [{'duration': 1}, {'duration': 3}]}
        self.run_voiceover(props, {'end_card': {'enabled': True}})
        # 5.6 s speech + 0.4 s tail + overlaps (scene→scene, scene→card) of 0.5 s each.
        self.assertEqual([s['duration'] for s in props['scenes']], [1.75, 5.25])
        self.assertNotIn('fitToVoiceover', props)


if __name__ == '__main__':
    unittest.main()
