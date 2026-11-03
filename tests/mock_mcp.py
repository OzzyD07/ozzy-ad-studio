"""Offline test double, never used by production config. Mirrors the OzzyVisionLab tool names."""
import json
import os
from mcp.server.fastmcp import FastMCP

server = FastMCP('otoreklam-test')


def log(entry):
    if os.environ.get('TEST_LOG'):
        with open(os.environ['TEST_LOG'], 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry) + '\n')


@server.tool()
def generate_omni_video(prompt: str, negative_prompt: str = '', images: list[str] = [], videos: list[str] = [],
                        audios: list[str] = [], ref_image_size: str = 'match', aspect_ratio: str = '16:9',
                        duration: int = 8, quality: str = 'standard', seed: int = -1,
                        enhance_prompt: bool = False) -> dict:
    """Return a pending synthetic video job."""
    log({'tool': 'generate', 'images': images, 'audios': audios, 'duration': duration,
         'ref_image_size': ref_image_size})
    return {'job_id': f'job_{abs(hash(prompt)) % 10**8}'}


@server.tool()
def generate_image(prompt: str, aspect_ratio: str = '4:5', quality: str = 'max', count: int = 1) -> dict:
    """Return a queued synthetic image job (Studio MCP shape)."""
    log({'tool': 'generate_image', 'prompt': prompt, 'aspect_ratio': aspect_ratio})
    return {'job_id': f'img_{abs(hash(prompt)) % 10**8}', 'status': 'queued', 'job': {'status': 'queued'}}


@server.tool()
def get_job(job_id: str) -> dict:
    """Return the synthetic fixture path."""
    if job_id.startswith('img_'):
        return {'job': {'id': job_id, 'status': 'done', 'output_image': os.environ['TEST_IMAGE_PATH']}}
    return {'job': {'job_id': job_id, 'status': 'completed', 'output_video': os.environ['TEST_VIDEO_PATH']}}


@server.tool()
def upload_asset(base64_data: str = '', filename: str = '', media_type: str = '') -> dict:
    """Pretend to store a reference file."""
    log({'tool': 'upload', 'filename': filename, 'media_type': media_type})
    return {'status': 'ok', 'asset': {'asset_id': 'asset_' + filename}}


if __name__ == '__main__':
    server.run(transport='stdio')
