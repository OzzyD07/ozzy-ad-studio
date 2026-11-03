"""Qwen Image 2.1 Turbo text-to-image, built like ComfyUI's official "Qwen Image 2.1 Turbo: Text to Image" template
(TextEncodeQwenImage21 + QwenImage21Cache, 8 steps on the checkpoint's fixed ManualSigmas schedule, euler, cfg 1).

Turbo steps are tied to that schedule, so quality is chosen by resolution: max = native 2K (~4 MP).
At cfg 1 ComfyUI skips the negative pass, so "no text" is asked for in the prompt itself (K-4).
"""
import os

from . import Engine, EngineError, new_seed, pick

RATIOS = {'1:1': (1, 1), '4:5': (4, 5), '9:16': (9, 16), '16:9': (16, 9),
          '3:4': (3, 4), '4:3': (4, 3), '2:3': (2, 3), '3:2': (3, 2)}
MEGAPIXELS = {'draft': 1.0, 'standard': 2.0, 'high': 3.0, 'max': 4.0}
NO_TEXT = ('The image contains no text, letters, numbers, captions, signs, labels, logos or watermarks; '
           'any screens, paper or packaging are blank.')
UNETS = [r'qwen_image_2\.1_turbo_bf16', r'qwen_image_2\.1_turbo.*fp8', r'qwen_image_2\.1_turbo_int8',
         r'qwen.?image.?2\.1.?turbo']
TEXT_ENCODERS = [r'^qwen3vl_8b_bf16', r'^qwen3vl_8b_int8', r'^qwen3vl_8b']
VAES = [r'qwen_image_2\.1_vae']


def size(ratio, megapixels):
    """Width/height for an aspect ratio at a pixel budget, multiples of 32 (the template's rule)."""
    w, h = RATIOS[ratio]
    scale = (megapixels * 1024 * 1024 / (w * h)) ** .5
    return int(round(w * scale / 32)) * 32, int(round(h * scale / 32)) * 32


class QwenImage(Engine):
    name = 'qwen_image'
    kind = 'image'
    title = 'Qwen Image 2.1 Turbo'

    def describe(self):
        return {**super().describe(), 'aspect_ratios': list(RATIOS), 'count': [1, 4],
                'sizes': {q: f'{mp:g} MP' for q, mp in MEGAPIXELS.items()},
                'notes': 'Turbo: 8 adım, cfg 1 (negatif prompt etkisiz). Varsayılan olarak yazısız üretir; '
                         'text_ok=true ile kapatılır (Qwen 2.1 tipografide güçlüdür).'}

    def validate(self, r):
        if r.get('aspect_ratio', '4:5') not in RATIOS:
            raise EngineError('aspect_ratio: ' + ', '.join(RATIOS))
        if not 1 <= int(r.get('count', 1)) <= 4:
            raise EngineError('count 1–4 olmalı')
        if r.get('quality', 'max') not in MEGAPIXELS:
            raise EngineError('quality: ' + ', '.join(MEGAPIXELS))

    def build(self, r, refs, model_files):
        wf = self.template()
        quality = r.get('quality', 'max')
        width, height = size(r.get('aspect_ratio', '4:5'), MEGAPIXELS[quality])
        seed = new_seed(r.get('seed'))
        unet = pick(model_files.get('diffusion_models', []), UNETS, os.environ.get('QWEN_UNET'))
        clip = pick(model_files.get('text_encoders', []), TEXT_ENCODERS, os.environ.get('QWEN_TEXT_ENCODER'))
        vae = pick(model_files.get('vae', []), VAES, os.environ.get('QWEN_VAE'))
        if not (unet and clip and vae):
            raise EngineError('Qwen Image 2.1 model dosyaları ComfyUI içinde bulunamadı (diffusion_models / text_encoders / vae)')
        prompt = r['prompt'] if r.get('text_ok') else f"{r['prompt'].rstrip()} {NO_TEXT}"
        wf['1']['inputs']['unet_name'] = unet
        wf['2']['inputs']['clip_name'] = clip
        wf['3']['inputs']['vae_name'] = vae
        wf['5']['inputs'].update(prompt=prompt, negative_prompt=r.get('negative_prompt') or '')
        wf['6']['inputs'].update(width=width, height=height, batch_size=int(r.get('count', 1)))
        wf['9']['inputs']['noise_seed'] = seed
        wf['13']['inputs']['filename_prefix'] = f"studio/{r.get('job_id', 'image')}"
        return wf, {'seed': seed, 'width': width, 'height': height, 'count': int(r.get('count', 1)),
                    'quality': quality, 'megapixels': MEGAPIXELS[quality], 'steps': 8, 'cfg': 1.0,
                    'prompt_sent': prompt, 'models': {'diffusion': unet, 'text_encoder': clip, 'vae': vae}}
