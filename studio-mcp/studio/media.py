"""FFmpeg helpers on the server: probe, reference-video preparation (ported from OzzyVision-Lab), safe outputs."""
import json
import shutil
import subprocess
from pathlib import Path

REFERENCE_FPS = 24
REFERENCE_MAX_SECONDS = 15.0
REFERENCE_MIN_SECONDS = 2.0  # MiniMax H3: reference clips are 2–15 s


def _tool(name):
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f'{name} bulunamadı (Colab: apt-get install -y ffmpeg)')
    return path


def probe(path):
    """{duration, fps, has_audio, video_codec, pix_fmt, width, height}; None when unreadable."""
    run = subprocess.run([_tool('ffprobe'), '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                         capture_output=True, text=True)
    if run.returncode:
        return None
    data = json.loads(run.stdout or '{}')
    video = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'), None)
    audio = next((s for s in data.get('streams', []) if s.get('codec_type') == 'audio'), None)
    fps = None
    if video and video.get('avg_frame_rate', '0/0') != '0/0':
        num, den = video['avg_frame_rate'].split('/')
        fps = float(num) / float(den) if float(den) else None
    duration = float((data.get('format') or {}).get('duration') or 0) or None
    return {'duration': duration, 'fps': fps, 'has_audio': audio is not None,
            'video_codec': video and video.get('codec_name'), 'pix_fmt': video and video.get('pix_fmt'),
            'width': video and video.get('width'), 'height': video and video.get('height')}


def prepare_reference_video(src, dst):
    """MiniMax H3 reads reference frames as 24 fps: other rates would mistime motion and sound. Clips are cut
    to 15 s; an already-fitting clip is copied untouched."""
    info = probe(src)
    if not info or not info['video_codec']:
        raise ValueError(f'Referans video okunamadı: {Path(src).name}')
    if info['duration'] and info['duration'] < REFERENCE_MIN_SECONDS - 0.05:
        raise ValueError(f'Referans video en az {REFERENCE_MIN_SECONDS:g} sn olmalı: {Path(src).name}')
    fits = info['fps'] and abs(info['fps'] - REFERENCE_FPS) < 0.01 and (info['duration'] or 0) <= REFERENCE_MAX_SECONDS + 1e-3
    if fits:
        shutil.copyfile(src, dst)
    else:
        subprocess.run([_tool('ffmpeg'), '-hide_banner', '-loglevel', 'error', '-y', '-i', str(src),
                        '-t', str(REFERENCE_MAX_SECONDS), '-vf', f'fps={REFERENCE_FPS}', '-c:v', 'libx264', '-crf', '14',
                        '-preset', 'medium', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '256k', str(dst)], check=True)
    out = probe(dst)
    return {'has_audio': info['has_audio'], 'duration': out and out['duration'], 'converted': not fits}


def make_playable(path):
    """ComfyUI's SaveVideo can write 10-bit H.264, which browsers and some decoders cannot show; re-encode those
    to 8-bit yuv420p at near-lossless quality. Returns the probe of the final file."""
    info = probe(path)
    if not info or (info['video_codec'] == 'h264' and info['pix_fmt'] in ('yuv420p', 'yuvj420p')):
        return info
    tmp = Path(path).with_suffix('.tmp.mp4')
    subprocess.run([_tool('ffmpeg'), '-hide_banner', '-loglevel', 'error', '-y', '-i', str(path), '-c:v', 'libx264',
                    '-crf', '12', '-preset', 'slow', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '320k',
                    '-movflags', '+faststart', str(tmp)], check=True)
    tmp.replace(path)
    return probe(path)
