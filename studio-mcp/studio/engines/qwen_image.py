"""Qwen Image (2.1 Turbo, FP8) text-to-image on ComfyUI's native Qwen-Image graph.

Images are generated text-free by default (K-4): titles, logos and badges are added later in Remotion.
Turbo checkpoints are step-distilled, so guidance stays at 1.0; QWEN_PRESETS (JSON) can retune per quality.
"""
import json
import os

from . import Engine, EngineError, new_seed, pick

# Qwen-Image native sizes (~1.3–1.7 MP, multiples of 16); 4:5 is the Instagram feed post.
SIZES = {'1:1': (1328, 1328), '4:5': (1184, 1472), '9:16': (928, 1664), '16:9': (1664, 928),
         '3:4': (1104, 1472), '4:3': (1472, 1104), '2:3': (1056, 1584), '3:2': (1584, 1056)}
PRESETS = {'draft': {'steps': 4, 'cfg': 1.0}, 'standard': {'steps': 8, 'cfg': 1.0},
           'high': {'steps': 8, 'cfg': 1.0}, 'max': {'steps': 12, 'cfg': 1.0}}
NO_TEXT = ('text, letters, words, typography, caption, subtitles, watermark, logo, brand name, signature, '
           'low quality, blurry, deformed, distorted hands, extra fingers, jpeg artifacts')
UNETS = [r'qwen.?image.*2\.1.*turbo.*fp8', r'qwen.?image.*turbo.*fp8', r'qwen.?image.*2\.1.*fp8',
         r'qwen.?image.*fp8', r'qwen.?image(?!.*edit)']
TEXT_ENCODERS = [r'qwen_?2\.5_?vl.*fp8', r'qwen_?2\.5_?vl', r'qwen.*vl']
VAES = [r'qwen.?image.*vae']


class QwenImage(Engine):
    name = 'qwen_image'
    kind = 'image'
    title = 'Qwen Image 2.1 Turbo FP8'

    def presets(self):
        override = os.environ.get('QWEN_PRESETS')
        return {**PRESETS, **(json.loads(override) if override else {})}

    def describe(self):
        return {**super().describe(), 'aspect_ratios': list(SIZES), 'count': [1, 4],
                'notes': 'Varsayılan olarak yazısız üretir (metin/logo Remotion\'da eklenir). text_ok=true ile kapatılır.'}

    def validate(self, r):
        if r.get('aspect_ratio', '4:5') not in SIZES:
            raise EngineError('aspect_ratio: ' + ', '.join(SIZES))
        if not 1 <= int(r.get('count', 1)) <= 4:
            raise EngineError('count 1–4 olmalı')
        if r.get('quality', 'max') not in self.presets():
            raise EngineError('quality: ' + ', '.join(self.presets()))

    def build(self, r, refs, model_files):
        wf = self.template()
        quality = r.get('quality', 'max')
        preset = self.presets()[quality]
        width, height = SIZES[r.get('aspect_ratio', '4:5')]
        seed = new_seed(r.get('seed'))
        unet = pick(model_files.get('diffusion_models', []), UNETS, os.environ.get('QWEN_UNET'))
        clip = pick(model_files.get('text_encoders', []), TEXT_ENCODERS, os.environ.get('QWEN_TEXT_ENCODER'))
        vae = pick(model_files.get('vae', []), VAES, os.environ.get('QWEN_VAE'))
        if not (unet and clip and vae):
            raise EngineError('Qwen Image model dosyaları ComfyUI içinde bulunamadı (diffusion_models / text_encoders / vae)')
        negative = ', '.join(x for x in [r.get('negative_prompt'), None if r.get('text_ok') else NO_TEXT] if x)
        wf['1']['inputs']['unet_name'] = unet
        wf['2']['inputs']['clip_name'] = clip
        wf['3']['inputs']['vae_name'] = vae
        wf['4']['inputs']['shift'] = float(preset.get('shift', 3.1))
        wf['5']['inputs']['text'] = r['prompt']
        wf['6']['inputs']['text'] = negative
        wf['7']['inputs'].update(width=width, height=height, batch_size=int(r.get('count', 1)))
        wf['8']['inputs'].update(seed=seed, steps=int(preset['steps']), cfg=float(preset['cfg']))
        wf['10']['inputs']['filename_prefix'] = f"studio/{r.get('job_id', 'image')}"
        return wf, {'seed': seed, 'width': width, 'height': height, 'count': int(r.get('count', 1)),
                    'quality': quality, **preset, 'negative_prompt': negative,
                    'models': {'diffusion': unet, 'text_encoder': clip, 'vae': vae}}
