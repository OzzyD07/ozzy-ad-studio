"""Ozzy Ad Studio MCP server (Streamable HTTP).

    STUDIO_TOKEN=… python -m studio.server          # Colab: the notebook sets env from Colab Secrets

Every MCP request needs "Authorization: Bearer $STUDIO_TOKEN" (K-11). Output files are served at
/files/<path>?sig=<hmac>, so the links that get_job returns download without a header.
"""
import argparse
import hmac
import mimetypes
import shutil
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from .comfy import ComfyError
from .jobs import Studio, sign
from .settings import Settings

INSTRUCTIONS = """Ozzy Ad Studio: Colab GPU'da video (MiniMax H3 Ref2VA FP8) ve görsel (Qwen Image 2.1 Turbo FP8) üretimi.
İşler sıraya girer: generate_* bir job_id döner, get_job ile durum ve indirme bağlantısı alınır.
Aynı türdeki işler art arda çalışır (önce videolar, sonra görseller); model değişiminde VRAM bir kez boşaltılır.
Referanslar önce upload_asset ile yüklenir; dönen asset_id images/videos/audios listelerinde kullanılır.
MiniMax'ta konuşma yalnızca <d>[English] …</d> içinde yazılır; negatif prompt CFG 1.0 olduğu için etkisizdir.
Görseller varsayılan olarak yazısız üretilir; metin, logo ve rozetler Remotion'da eklenir."""


def build(settings: Settings, comfy=None, start_worker=True):
    studio = Studio(settings, comfy)
    mcp = FastMCP('ozzy-ad-studio', instructions=INSTRUCTIONS, stateless_http=True, json_response=True,
                  host=settings.host, port=settings.port,
                  # The bearer token is the protection; ngrok forwards a public Host header.
                  transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))

    def link(rel):
        url = f'/files/{rel}?sig={sign(settings.token, rel)}'
        return settings.public_url + url if settings.public_url else url

    def view(job):
        out = {k: v for k, v in job.items() if k not in ('started_ts', 'cancel_requested')}
        urls = [link(p) for p in job.get('outputs') or []]
        if urls:
            out['outputs'] = urls
            out['output_video' if job['kind'] == 'video' else 'output_image'] = urls[0]
        return out

    def queued(job):
        return {'job_id': job['id'], 'status': job['status'], 'job': view(job)}

    @mcp.tool()
    def generate_video(prompt: str, images: list[str] | None = None, videos: list[str] | None = None,
                       audios: list[str] | None = None, aspect_ratio: str = '9:16', duration: int = 8,
                       quality: Literal['draft', 'standard', 'high', 'max'] = 'max', seed: int = -1,
                       ref_image_size: Literal['match', 'max'] = 'max', negative_prompt: str | None = None,
                       loras: list[dict] | None = None, priority: int = 0, model: str = 'minimax_h3') -> dict[str, Any]:
        """MiniMax H3 Ref2VA ile 4–15 sn video + doğal 32 kHz stereo ses. images ≤9 (<Picture N>),
        videos ≤3 (<Video N>, 2–15 sn, toplam ≤15 sn), audios ≤3 (<Audio N>): asset_id, sunucu yolu veya URL.
        quality=max referansları 2048 px'e kadar korur. Konuşma: <d>[English] metin</d>. Sıraya girer; get_job ile izleyin."""
        request = dict(prompt=prompt, images=images or [], videos=videos or [], audios=audios or [],
                       aspect_ratio=aspect_ratio, duration=duration, quality=quality, seed=seed,
                       ref_image_size=ref_image_size, negative_prompt=negative_prompt, loras=loras or [])
        return queued(studio.submit(model, request, priority))

    @mcp.tool()
    def generate_omni_video(prompt: str, images: list[str] | None = None, videos: list[str] | None = None,
                            audios: list[str] | None = None, aspect_ratio: str = '9:16', duration: int = 8,
                            quality: Literal['draft', 'standard', 'high', 'max'] = 'max', seed: int = -1,
                            ref_image_size: Literal['match', 'max'] = 'max', negative_prompt: str | None = None,
                            enhance_prompt: bool = False, loras: list[dict] | None = None) -> dict[str, Any]:
        """Eski OzzyVision-Lab adı (OtoReklam config uyumu): generate_video ile aynı. enhance_prompt yok sayılır."""
        return generate_video(prompt, images, videos, audios, aspect_ratio, duration, quality, seed,
                              ref_image_size, negative_prompt, loras)

    @mcp.tool()
    def generate_image(prompt: str, aspect_ratio: str = '4:5', count: int = 1,
                       quality: Literal['draft', 'standard', 'high', 'max'] = 'max', seed: int = -1,
                       negative_prompt: str | None = None, text_ok: bool = False, priority: int = 0,
                       model: str = 'qwen_image') -> dict[str, Any]:
        """Qwen Image 2.1 Turbo ile görsel (1–4 adet). Oranlar: 1:1, 4:5, 9:16, 16:9, 3:4, 4:3, 2:3, 3:2.
        Varsayılan olarak yazı/logo üretmez (text_ok=true kapatır); post metni Remotion'da eklenir."""
        request = dict(prompt=prompt, aspect_ratio=aspect_ratio, count=count, quality=quality, seed=seed,
                       negative_prompt=negative_prompt, text_ok=text_ok)
        return queued(studio.submit(model, request, priority))

    @mcp.tool()
    def get_job(job_id: str) -> dict[str, Any]:
        """İşin durumu (queued/running/done/failed/cancelled), sıradaki yeri, tahmini bekleme, model değişimi
        bekleyip beklemediği ve bittiyse indirme bağlantıları (job.output_video / job.output_image / job.outputs)."""
        return {'job': view(studio.get(job_id))}

    @mcp.tool()
    def list_jobs(limit: int = 20, status: str | None = None) -> dict[str, Any]:
        """Son işler (en yeni önce); status ile süzülebilir."""
        return {'jobs': [view(j) for j in studio.list(limit, status)]}

    @mcp.tool()
    def cancel_job(job_id: str) -> dict[str, Any]:
        """Sıradaki veya çalışan işi iptal eder."""
        return {'job': view(studio.cancel(job_id))}

    @mcp.tool()
    def retry_job(job_id: str) -> dict[str, Any]:
        """Başarısız veya iptal edilmiş işi aynı ayarlarla yeniden sıraya koyar."""
        return {'job': view(studio.retry(job_id))}

    @mcp.tool()
    def reorder_job(job_id: str, direction: Literal['up', 'down']) -> dict[str, Any]:
        """Sıradaki bir işin önceliğini artırır (up) veya azaltır (down)."""
        return {'job': view(studio.reorder(job_id, direction))}

    @mcp.tool()
    def upload_asset(file_path: str | None = None, url: str | None = None, base64_data: str | None = None,
                     filename: str | None = None, media_type: Literal['image', 'video', 'audio'] | None = None) -> dict[str, Any]:
        """Referans görsel/video/ses yükler (sunucu yolu, URL veya base64). Dönen asset_id üretimde kullanılır."""
        return studio.add_asset(file_path, url, base64_data, filename, media_type)

    @mcp.tool()
    def list_assets() -> dict[str, Any]:
        """Yüklenmiş referanslar."""
        return {'assets': studio.assets()}

    @mcp.tool()
    def list_models() -> dict[str, Any]:
        """Modeller, desteklenen oranlar, süreler, kalite seviyeleri ve referans sınırları."""
        return {'models': [e.describe() for e in studio.engines.values()]}

    @mcp.tool()
    def server_status() -> dict[str, Any]:
        """GPU/VRAM, ComfyUI bağlantısı, kuyruk, VRAM'deki model türü ve disk alanı."""
        status = {'status': 'online', 'loaded_kind': studio.loaded_kind,
                  'running': studio.current and studio.current['id'],
                  'queue': {s: sum(j['status'] == s for j in studio.jobs.values())
                            for s in ('queued', 'running', 'done', 'failed', 'cancelled')},
                  'home': str(settings.home), 'free_disk_gb': round(shutil.disk_usage(settings.home).free / 1024**3, 1)}
        try:
            stats = studio.comfy.system_stats()
            status['comfyui'] = {'online': True, 'devices': [
                {'name': d.get('name'), 'vram_gb': round(d.get('vram_total', 0) / 1024**3, 1),
                 'vram_free_gb': round(d.get('vram_free', 0) / 1024**3, 1)} for d in stats.get('devices', [])]}
            files = studio.model_files()
            status['model_files'] = {k: len(v) for k, v in files.items()}
        except ComfyError as e:
            status['comfyui'] = {'online': False, 'error': str(e)}
        return status

    @mcp.tool()
    def get_system_status() -> dict[str, Any]:
        """Eski ad: server_status ile aynı."""
        return server_status()

    @mcp.tool()
    def free_vram() -> dict[str, Any]:
        """ComfyUI'deki tüm modelleri VRAM'den boşaltır (iş çalışmıyorken)."""
        studio.free_vram()
        return {'ok': True}

    @mcp.custom_route('/health', methods=['GET'])
    async def health(request: Request) -> Response:
        return JSONResponse({'ok': True, 'queued': sum(j['status'] == 'queued' for j in studio.jobs.values())})

    @mcp.custom_route('/files/{path:path}', methods=['GET'])
    async def files(request: Request) -> Response:
        rel = request.path_params['path']
        if not hmac.compare_digest(request.query_params.get('sig', ''), sign(settings.token, rel)):
            return Response('forbidden', status_code=403)
        target = (settings.home/rel).resolve()
        if settings.home.resolve() not in target.parents or not target.is_file():
            return Response('not found', status_code=404)
        return FileResponse(target, media_type=mimetypes.guess_type(target.name)[0] or 'application/octet-stream')

    app = mcp.streamable_http_app()
    app.add_middleware(BearerAuth, token=settings.token)
    if start_worker:
        studio.start()
    return app, studio, mcp


class BearerAuth:
    """ASGI middleware: everything except /health and signed /files needs the token, as a bearer header or as
    ?key=… in the URL (Claude's custom connector form only takes a URL)."""

    def __init__(self, app, token):
        self.app = app
        self.token = token.encode()

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and not scope['path'].startswith(('/health', '/files/')):
            given = dict(scope.get('headers') or []).get(b'authorization', b'')
            key = parse_qs(scope.get('query_string', b'').decode()).get('key', [''])[0].encode()
            if not (hmac.compare_digest(given, b'Bearer ' + self.token) or hmac.compare_digest(key, self.token)):
                await Response('unauthorized', status_code=401, headers={'WWW-Authenticate': 'Bearer'})(scope, receive, send)
                return
        await self.app(scope, receive, send)


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description='Ozzy Ad Studio MCP')
    parser.add_argument('--port', type=int)
    args = parser.parse_args()
    settings = Settings.from_env(**({'port': args.port} if args.port else {}))
    if len(settings.token) < 16:
        raise SystemExit('STUDIO_TOKEN en az 16 karakter olmalı (K-11). Colab Secrets → STUDIO_TOKEN')
    app, _, _ = build(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level='info')


if __name__ == '__main__':
    main()
