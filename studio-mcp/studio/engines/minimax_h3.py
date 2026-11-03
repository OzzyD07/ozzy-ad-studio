"""MiniMax H3 Ref2VA (official Comfy-Org FP8 scaled): video + native 32 kHz stereo audio, up to 9 image,
3 video and 3 audio references. Graph and model constraints ported from OzzyVision-Lab's engine."""
import os

from . import Engine, EngineError, new_seed, pick

SIZES = {'16:9': (1344, 768), '9:16': (768, 1344), '1:1': (768, 768),
         '4:3': (1024, 768), '3:4': (768, 1024), '21:9': (1536, 640)}
# The model is CFG-distilled: guidance stays 1.0, quality comes from steps and reference resolution.
STEPS = {'draft': 4, 'standard': 8, 'high': 10, 'max': 10}
LIMITS = {'images': 9, 'videos': 3, 'audios': 3, 'total': 12}
UNETS = [r'minimax_h3.*fp8_scaled', r'minimax_h3.*int8', r'minimax_h3.*bf16', r'minimax_h3.*\.gguf$']
TEXT_ENCODERS = [r'qwen3vl.*minimax.*nvfp4', r'qwen3vl.*minimax.*int8', r'qwen3vl.*minimax.*int4', r'qwen3vl.*minimax.*bf16']


def frame_count(seconds, fps=24):
    """The 3D VAE needs 17k+5 frames: round the requested length up to that grid."""
    raw = max(5, round(seconds * fps))
    return int(raw + ((5 - raw % 17) % 17))


class MiniMaxH3(Engine):
    name = 'minimax_h3'
    kind = 'video'
    title = 'MiniMax H3 Ref2VA FP8'

    def describe(self):
        return {**super().describe(), 'aspect_ratios': list(SIZES), 'duration': [4, 15], 'limits': LIMITS,
                'notes': 'quality=max: ref_image_size=max (2048 px referans), 10 adım. Konuşma: <d>[English] …</d>'}

    def validate(self, r):
        if r.get('aspect_ratio', '9:16') not in SIZES:
            raise EngineError('aspect_ratio: ' + ', '.join(SIZES))
        if not 4 <= int(r.get('duration', 8)) <= 15:
            raise EngineError('duration 4–15 sn olmalı')
        if r.get('quality', 'max') not in STEPS:
            raise EngineError('quality: ' + ', '.join(STEPS))
        counts = {k: len(r.get(k) or []) for k in ('images', 'videos', 'audios')}
        for k, n in counts.items():
            if n > LIMITS[k]:
                raise EngineError(f'En fazla {LIMITS[k]} {k} referansı (verilen {n})')
        if sum(counts.values()) > LIMITS['total']:
            raise EngineError(f'Toplam referans en fazla {LIMITS["total"]}')

    def build(self, r, refs, model_files):
        wf = self.template()
        quality = r.get('quality', 'max')
        width, height = SIZES[r.get('aspect_ratio', '9:16')]
        if quality == 'draft':
            width, height = int(width * .75) // 32 * 32, int(height * .75) // 32 * 32
        duration = int(r.get('duration', 8))
        frames = frame_count(duration)
        seed = new_seed(r.get('seed'))
        # "max" protects references: up to 2048 px instead of the output resolution.
        ref_size = 'max' if quality == 'max' else r.get('ref_image_size') or 'match'

        unet = pick(model_files.get('diffusion_models', []), UNETS, os.environ.get('MINIMAX_DIFFUSION_MODEL'))
        clip = pick(model_files.get('text_encoders', []), TEXT_ENCODERS, os.environ.get('MINIMAX_TEXT_ENCODER'))
        if not unet or not clip:
            raise EngineError('MiniMax H3 model dosyaları ComfyUI içinde bulunamadı (diffusion_models / text_encoders)')
        wf['1'] = ({'class_type': 'UnetLoaderGGUF', 'inputs': {'unet_name': unet}} if unet.endswith('.gguf') else
                   {'class_type': 'UNETLoader', 'inputs': {'unet_name': unet, 'weight_dtype': 'default'}})
        wf['2']['inputs'].update(clip_name=clip, type='minimax', device='default')
        wf['3']['inputs']['vae_name'] = os.environ.get('MINIMAX_VIDEO_VAE', 'minimax_h3_video_vae_fp16.safetensors')
        wf['4']['inputs']['vae_name'] = os.environ.get('MINIMAX_AUDIO_VAE', 'minimax_h3_audio_vae_fp32.safetensors')

        model = ['1', 0]
        for i, lora in enumerate((r.get('loras') or [])[:3]):
            # LoRA only on the diffusion model; the 32B Qwen3-VL encoder is left alone (VRAM).
            node = str(50 + i)
            wf[node] = {'class_type': 'LoraLoaderModelOnly',
                        'inputs': {'model': model, 'lora_name': lora['name'], 'strength_model': float(lora.get('strength', 1.0))}}
            model = [node, 0]

        images, videos, audios = refs.get('images', []), refs.get('videos', []), refs.get('audios', [])
        common = {'clip': ['2', 0], 'vae': ['3', 0], 'audio_vae': ['4', 0], 'prompt': r['prompt'],
                  'width': width, 'height': height, 'length': frames}
        if images or videos or audios:
            node = {'class_type': 'MiniMaxH3ReferenceToVideo', 'inputs': {**common, 'ref_image_size': ref_size}}
            for i, name in enumerate(images):
                wf[f'10{i + 1}'] = {'class_type': 'LoadImage', 'inputs': {'image': name}}
                node['inputs'][f'ref_images.ref_image_{i}'] = [f'10{i + 1}', 0]
            for i, video in enumerate(videos):
                # ref_videos takes IMAGE frames; GetVideoComponents splits LoadVideo into frames (0) and audio (1).
                wf[f'20{i + 1}'] = {'class_type': 'LoadVideo', 'inputs': {'file': video['file']}}
                wf[f'21{i + 1}'] = {'class_type': 'GetVideoComponents', 'inputs': {'video': [f'20{i + 1}', 0]}}
                node['inputs'][f'ref_videos.ref_video_{i}'] = [f'21{i + 1}', 0]
                if video.get('has_audio'):
                    node['inputs'][f'ref_video_audios.ref_video_audio_{i}'] = [f'21{i + 1}', 1]
            for i, name in enumerate(audios):
                wf[f'30{i + 1}'] = {'class_type': 'LoadAudio', 'inputs': {'audio': name}}
                node['inputs'][f'ref_audios.ref_audio_{i}'] = [f'30{i + 1}', 0]
        else:
            node = {'class_type': 'MiniMaxH3ImageToVideo', 'inputs': common}
        wf['8'] = node
        wf['9']['inputs'].update(model=model, conditioning=['8', 0])
        wf['11']['inputs'].update(model=model, steps=STEPS[quality], denoise=1.0)
        wf['12']['inputs']['noise_seed'] = seed
        wf['13']['inputs']['latent_image'] = ['8', 1]
        wf['16']['inputs']['fps'] = 24
        wf['17']['inputs'].update(filename_prefix=f"studio/{r.get('job_id', 'video')}", format='auto')
        return wf, {'seed': seed, 'width': width, 'height': height, 'frames': frames, 'fps': 24,
                    'steps': STEPS[quality], 'ref_image_size': ref_size, 'quality': quality,
                    'models': {'diffusion': unet, 'text_encoder': clip},
                    'references': {'images': len(images), 'videos': len(videos), 'audios': len(audios)}}
