"""Local text-to-speech: Kokoro-82M on CPU (English and other Kokoro languages) and Piper for Turkish.

speak() writes a WAV and returns caption words [{text, start, end}] that Remotion uses directly.
Kokoro gives word timings itself; Piper's Turkish voices do not, so Whisper aligns the known script.
"""
import os
import re
import wave
from pathlib import Path

import media

ROOT = Path(__file__).resolve().parent
KOKORO_REPO = 'hexgrad/Kokoro-82M'
KOKORO_RATE = 24000
# Kokoro voice names start with their language code: af_heart → 'a' (American English).
KOKORO_LANGS = {'a': 'en', 'b': 'en', 'e': 'es', 'f': 'fr', 'h': 'hi', 'i': 'it', 'p': 'pt', 'j': 'ja', 'z': 'zh'}
KOKORO_VOICES = {
    'a': ['af_heart', 'af_bella', 'af_nicole', 'af_aoede', 'af_kore', 'af_sarah', 'af_sky',
          'am_michael', 'am_fenrir', 'am_puck', 'am_echo', 'am_eric', 'am_liam', 'am_onyx'],
    'b': ['bf_emma', 'bf_isabella', 'bf_alice', 'bf_lily', 'bm_george', 'bm_fable', 'bm_lewis', 'bm_daniel'],
}
PIPER_VOICES = ['tr_TR-dfki-medium', 'tr_TR-fahrettin-medium', 'tr_TR-fettah-medium']
DEFAULTS = {'voice': 'af_heart', 'speed': 1.0, 'pronounce': {},
            'turkish': False, 'piper_voice': 'tr_TR-dfki-medium'}
_kokoro = {}


def settings(cfg):
    return {**DEFAULTS, **(cfg.get('tts') or {})}


def models_dir(cfg):
    base = Path(cfg.get('workspace', 'workspace'))
    return (base if base.is_absolute() else ROOT/base)/'models'


def write_wav(path, samples, rate):
    import numpy as np
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(samples, -1, 1) * 32767).astype('<i2')
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def with_pronunciations(text, pronounce):
    """{"MentorAi": "/mˈɛntɔɹ ˌAˈI/"} → Kokoro's inline phoneme markup; captions keep the written word."""
    for word, sound in pronounce.items():
        if sound.startswith('/'):
            text = re.sub(rf'(?<![\w\[]){re.escape(word)}(?![\w\]])', f'[{word}]({sound})', text)
    return text


def merge_tokens(tokens, offset):
    """Kokoro tokens → words; punctuation tokens stick to the word before them, as written."""
    words = []
    for tok in tokens:
        if tok.start_ts is None or tok.end_ts is None:
            continue
        start, end = round(offset + tok.start_ts, 3), round(offset + tok.end_ts, 3)
        if words and not re.search(r'\w', tok.text) and not words[-1]['space']:
            words[-1]['text'] += tok.text
            words[-1]['end'] = end
        else:
            words.append({'text': tok.text, 'start': start, 'end': end, 'space': bool(tok.whitespace)})
        words[-1]['space'] = bool(tok.whitespace)
    return [{k: w[k] for k in ('text', 'start', 'end')} for w in words if re.search(r'\w', w['text'])]


def kokoro(text, output, cfg, voice, speed):
    import numpy as np
    os.environ.setdefault('HF_HUB_CACHE', str(models_dir(cfg)))
    from kokoro import KPipeline
    lang = voice[0]
    if lang not in KOKORO_LANGS:
        raise ValueError('Bilinmeyen Kokoro sesi: ' + voice)
    if lang not in _kokoro:
        _kokoro[lang] = KPipeline(lang_code=lang, repo_id=KOKORO_REPO)
    chunks, words, offset = [], [], 0.0
    for result in _kokoro[lang](with_pronunciations(text, settings(cfg)['pronounce']), voice=voice, speed=speed):
        audio = result.audio.numpy()
        words += merge_tokens(result.tokens or [], offset)
        chunks.append(audio)
        offset += len(audio) / KOKORO_RATE
    if not chunks:
        raise ValueError('Kokoro ses üretmedi (metin boş mu?)')
    write_wav(output, np.concatenate(chunks), KOKORO_RATE)
    return words


def piper(text, output, cfg, voice, speed):
    from piper import PiperVoice, SynthesisConfig
    from piper.download_voices import download_voice
    folder = models_dir(cfg)/'piper'
    model = folder/(voice + '.onnx')
    if not model.is_file():
        folder.mkdir(parents=True, exist_ok=True)
        download_voice(voice, folder)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), 'wb') as w:
        PiperVoice.load(model).synthesize_wav(text, w, syn_config=SynthesisConfig(length_scale=1 / speed))
    # Piper's Turkish voices carry no alignments: Whisper times the audio, the script supplies the spelling.
    whisper = {**cfg.get('whisper', {}), 'language': 'tr'}
    segments = media.align_script(media.transcribe(output, whisper, models_dir(cfg)), text)
    import render
    return render.words_from_segments(segments)


def speak(text, output, cfg, language=None, voice=None, speed=None):
    """Write a WAV for text; returns {audio, duration, words, engine, voice}."""
    s = settings(cfg)
    text = ' '.join(text.split()) if '\n' not in text.strip() else text.strip()
    if not text:
        raise ValueError('Seslendirilecek metin boş.')
    language = language or KOKORO_LANGS.get((voice or s['voice'])[0], 'en')
    if language == 'tr':
        if not s['turkish']:
            raise ValueError('Türkçe seslendirme kapalı (K-9). Açmak için config.json → "tts": {"turkish": true}')
        engine, voice = 'piper', voice or s['piper_voice']
        words = piper(text, output, cfg, voice, speed or s['speed'])
    else:
        engine, voice = 'kokoro', voice or s['voice']
        if KOKORO_LANGS.get(voice[0]) != language:
            raise ValueError(f'{voice} sesi {language} dili için değil.')
        words = kokoro(text, output, cfg, voice, speed or s['speed'])
    return {'audio': str(Path(output).resolve()), 'duration': round(media.media_duration(output), 3),
            'words': words, 'engine': engine, 'voice': voice}
