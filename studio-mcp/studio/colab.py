"""Colab setup steps the notebook calls (kept here so they are versioned and testable, not buried in cells).

Layout on Drive:
  MyDrive/OzzyAdStudio/code      git clone of the repo: the code that runs; GitHub is the source/backup
  MyDrive/OzzyAdStudio/{jobs,assets,outputs}
  MyDrive/OzzyVision-Lab/models  model weights (shared with the old studio, so nothing downloads twice; K-23)
"""
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

REPO = 'https://github.com/OzzyD07/ozzy-ad-studio.git'
DRIVE = Path('/content/drive/MyDrive')
HOME = DRIVE/'OzzyAdStudio'
CODE = HOME/'code'
COMFY = Path('/content/ComfyUI')
LOGS = Path('/content/logs')


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, text=True, capture_output=True, **kw).stdout.strip()


def models_dir():
    """Reuse the old studio's model folder when it exists; otherwise keep models under OzzyAdStudio."""
    old = DRIVE/'OzzyVision-Lab'/'models'
    return old if old.is_dir() else HOME/'models'


# ---------- 1. code: Drive copy vs GitHub ----------
def sync_code(branch='main'):
    """The Drive copy is what runs. Compare it with GitHub and fast-forward when GitHub is newer; when GitHub is
    unreachable, keep running the Drive copy."""
    HOME.mkdir(parents=True, exist_ok=True)
    if not (CODE/'.git').is_dir():
        print('⬇️  Kod Drive\'a ilk kez kopyalanıyor (GitHub)...')
        run(['git', 'clone', '-q', '--branch', branch, REPO, str(CODE)])
        print('✅ Kod:', run(['git', '-C', str(CODE), 'log', '-1', '--format=%h %s (%cd)', '--date=short']))
        return
    before = run(['git', '-C', str(CODE), 'rev-parse', 'HEAD'])
    try:
        run(['git', '-C', str(CODE), 'fetch', '-q', 'origin', branch])
    except subprocess.CalledProcessError as e:
        print('⚠️  GitHub\'a ulaşılamadı; Drive\'daki kod kullanılacak:', (e.stderr or '')[-200:])
        return
    remote = run(['git', '-C', str(CODE), 'rev-parse', 'FETCH_HEAD'])
    current = run(['git', '-C', str(CODE), 'rev-parse', '--abbrev-ref', 'HEAD'])
    if before == remote and current == branch:
        print('✅ Drive\'daki kod güncel:', run(['git', '-C', str(CODE), 'log', '-1', '--format=%h %s (%cd)', '--date=short']))
        return
    changes = run(['git', '-C', str(CODE), 'log', '--oneline', f'{before}..{remote}']) if current == branch else ''
    # Drive's copy is managed by this notebook; local edits there are not expected, so it follows GitHub exactly.
    run(['git', '-C', str(CODE), 'checkout', '-q', '-B', branch, remote])
    print(f'🔄 Kod güncellendi ({before[:7]} → {remote[:7]}):')
    print(changes or '(dal değişti: ' + branch + ')')


# ---------- 2. models on Drive ----------
def sha256(path, chunk=64 << 20):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def ensure_models(qwen_variant='bf16', verify_sha=False, engines=('minimax_h3', 'qwen_image')):
    """Download missing weights straight to Drive, check sizes (and sha256 once, cached), report what is missing."""
    from huggingface_hub import hf_hub_download
    manifest = json.loads((CODE/'studio-mcp'/'models.json').read_text(encoding='utf-8'))
    root = models_dir()
    marks = root/'.verified.json'
    verified = json.loads(marks.read_text()) if marks.is_file() else {}
    files = [f for e in engines for f in manifest[e]['default' if e == 'minimax_h3' else qwen_variant]]
    need = sum(f['size'] for f in files if not (root/f['file']).is_file())
    free = shutil.disk_usage(DRIVE).free
    print(f'📦 Modeller: {root}  (eksik {need / 1e9:.1f} GB, Drive boş {free / 1e9:.1f} GB)')
    if need > free:
        raise RuntimeError('Drive\'da yer yok. qwen_variant="int8" (17 GB) deneyin veya Drive\'da yer açın.')
    token = secret('HF_TOKEN')
    problems = []
    for f in files:
        target = root/f['file']
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file() and target.stat().st_size != f['size']:
            print(f'   ⚠️  {target.name}: boyut tutmuyor ({target.stat().st_size} ≠ {f["size"]}), yeniden indirilecek')
            target.unlink()
        if not target.is_file():
            print(f'   ⬇️  {target.name} ({f["size"] / 1e9:.1f} GB) Drive\'a indiriliyor...')
            got = Path(hf_hub_download(repo_id=f['repo'], filename=f['file'], local_dir=str(root), token=token))
            if got.resolve() != target.resolve():
                shutil.move(str(got), target)
        if target.stat().st_size != f['size']:
            problems.append(f'{target.name}: boyut hatalı')
            continue
        key = f'{f["file"]}:{f["size"]}:{int(target.stat().st_mtime)}'
        if verify_sha and verified.get(key) != f['sha256']:
            print(f'   🔎 {target.name} sha256 doğrulanıyor...')
            if sha256(target) != f['sha256']:
                problems.append(f'{target.name}: sha256 tutmuyor (dosyayı silip yeniden çalıştırın)')
                continue
            verified[key] = f['sha256']
        print(f'   ✅ {target.name}' + ('  (sha256 ✓)' if verified.get(key) == f['sha256'] else ''))
    marks.write_text(json.dumps(verified, indent=1))
    if problems:
        raise RuntimeError('Model sorunları:\n  ' + '\n  '.join(problems))
    link_models(root)


def link_models(root):
    """Point ComfyUI at the Drive folder (extra_model_paths.yaml): no copies on the Colab disk."""
    yaml = COMFY/'extra_model_paths.yaml'
    yaml.write_text(f'drive:\n  base_path: {root}\n  diffusion_models: |\n    diffusion_models\n    unet\n'
                    '  text_encoders: |\n    text_encoders\n    clip\n  vae: vae\n  loras: loras\n', encoding='utf-8')
    print('🔗 ComfyUI modelleri Drive\'dan okuyacak:', root)


# ---------- 3. processes ----------
def _get(url, timeout=3):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read() or b'{}')
    except Exception:
        return None


def _wait(url, seconds, log):
    for _ in range(seconds):
        if _get(url) is not None:
            return True
        time.sleep(1)
    print(f'❌ Yanıt yok: {url}\n--- {log} (son satırlar) ---')
    print('\n'.join(Path(log).read_text(errors='replace').splitlines()[-25:]) if Path(log).exists() else '(log yok)')
    return False


def start_comfy():
    if _get('http://127.0.0.1:8188/system_stats'):
        print('✅ ComfyUI zaten çalışıyor')
        return True
    LOGS.mkdir(exist_ok=True)
    env = {**os.environ, 'PYTORCH_CUDA_ALLOC_CONF': 'expandable_segments:True'}
    # --highvram is not used: it pins models in VRAM and breaks the video→image model switch (K-10).
    subprocess.Popen(['python', 'main.py', '--listen', '127.0.0.1', '--port', '8188', '--preview-method', 'none',
                      '--reserve-vram', '2.0'], cwd=COMFY, env=env,
                     stdout=open(LOGS/'comfyui.log', 'w'), stderr=subprocess.STDOUT)
    ok = _wait('http://127.0.0.1:8188/system_stats', 240, LOGS/'comfyui.log')
    if ok:
        print('✅ ComfyUI hazır')
    return ok


def secret(name):
    """Colab Secret (None when missing or not shared with this notebook), else environment variable."""
    try:
        from google.colab import userdata
        return userdata.get(name) or None
    except Exception:
        return os.environ.get(name) or None


def studio_token():
    """STUDIO_TOKEN from Colab Secrets; otherwise one is generated once and kept on Drive."""
    token = secret('STUDIO_TOKEN')
    if token:
        return token, 'Colab Secrets'
    path = HOME/'.studio_token'
    if not path.is_file():
        path.write_text(secrets.token_urlsafe(32))
    return path.read_text().strip(), str(path)


def start_server(token, port=8000):
    """(Re)start the server so a code update from cell 1 takes effect; queued jobs live on Drive and resume."""
    if _get(f'http://127.0.0.1:{port}/health') is not None:
        subprocess.run(['pkill', '-f', 'studio.server'])
        for _ in range(20):
            if _get(f'http://127.0.0.1:{port}/health') is None:
                break
            time.sleep(.5)
        print('🔄 Studio MCP yeniden başlatılıyor')
    LOGS.mkdir(exist_ok=True)
    env = {**os.environ, 'STUDIO_TOKEN': token, 'STUDIO_HOME': str(HOME), 'STUDIO_PORT': str(port)}
    subprocess.Popen(['python', '-m', 'studio.server'], cwd=CODE/'studio-mcp', env=env,
                     stdout=open(LOGS/'studio.log', 'w'), stderr=subprocess.STDOUT)
    ok = _wait(f'http://127.0.0.1:{port}/health', 60, LOGS/'studio.log')
    if ok:
        print('✅ Studio MCP hazır (port', port, ')')
    return ok


def start_tunnel(port=8000):
    from pyngrok import ngrok
    auth = secret('NGROK_AUTHTOKEN') or secret('NGROK_AUTH_TOKEN')
    if not auth:
        raise RuntimeError('Colab Secrets içinde NGROK_AUTHTOKEN yok (ve bu notebook\'a erişim izni verilmeli)')
    domain = secret('NGROK_DOMAIN')
    try:
        ngrok.set_auth_token(auth)
    except Exception as e:  # Re-running with ngrok already up can fail to rewrite its config; the tunnel may still be fine.
        print('ℹ️  ngrok jetonu yeniden yazılamadı:', str(e)[:120])
    existing = [t for t in ngrok.get_tunnels() if t.config.get('addr', '').endswith(f':{port}')]
    if existing and (not domain or domain in existing[0].public_url):
        url = existing[0].public_url  # The tunnel survives a server restart; keep it.
    else:
        for t in ngrok.get_tunnels():
            ngrok.disconnect(t.public_url)
        url = ngrok.connect(port, domain=domain).public_url if domain else ngrok.connect(port).public_url
    health = _get(url + '/health', timeout=15)
    print(('✅' if health is not None else '⚠️ ') + ' Dış adres:', url, '| sağlık:', health)
    return url
