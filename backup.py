"""Drive backup of the campaign data in workspace/apps (K-13, K-32).

workspace/ never enters git (public repo), so `pipeline.py yedekle` zips workspace/apps without the generated media
(exports, raw, review: reproducible and large) and sends it to the Studio MCP on Colab, which writes it to Drive
(MyDrive/OzzyAdStudio/backups). The zip also stays in workspace/backups and, when set, in config.json → backup.dir
(e.g. a second disk). `yedek-geri` unpacks a backup next to the data first; --uygula copies it over workspace/apps.

    "backup": {"dir": "D:/Yedek/OtoReklam", "keep": 10, "skip_dirs": ["exports", "raw", "review"], "max_file_mb": 50}
"""
import base64
import shutil
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin

DEFAULT = {'dir': '', 'keep': 10, 'skip_dirs': ['exports', 'raw', 'review'], 'max_file_mb': 50}
SKIP_FILES = {'.queue.lock'}


def settings(cfg):
    return {**DEFAULT, **(cfg.get('backup') or {})}


def roots(cfg):
    ws = Path(cfg['workspace'])
    return ws/'apps', ws/'backups'


def files(apps, s):
    """(files to back up, files skipped for size): everything under apps except generated-media folders."""
    skip_dirs, limit = set(s['skip_dirs']), s['max_file_mb'] << 20
    keep, big = [], []
    for path in sorted(apps.rglob('*')):
        rel = path.relative_to(apps)
        if not path.is_file() or path.name in SKIP_FILES or path.suffix == '.tmp':
            continue
        if any(part in skip_dirs for part in rel.parts[1:-1]):  # apps/<slug>/<dir>/…: per-app media folders
            continue
        (big if path.stat().st_size > limit else keep).append(path)
    return keep, big


def make(cfg, stamp=None):
    """Zip workspace/apps into workspace/backups; returns (zip path, file count, skipped big files)."""
    apps, out = roots(cfg)
    if not apps.is_dir():
        raise ValueError(f'Yedeklenecek klasör yok: {apps}')
    s = settings(cfg)
    keep, big = files(apps, s)
    out.mkdir(parents=True, exist_ok=True)
    target = out/f"apps-{stamp or datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in keep:
            z.write(path, path.relative_to(apps).as_posix())
    for old in sorted(out.glob('apps-*.zip'), reverse=True)[max(1, int(s['keep'])):]:
        old.unlink()
    return target, len(keep), big


def upload(cfg, path):
    """Send the zip to the Studio MCP (save_backup); it lands on Drive."""
    from mcp_bridge import call
    data = base64.b64encode(Path(path).read_bytes()).decode('ascii')
    return call(cfg['mcp'], 'save_backup', {'name': Path(path).name, 'base64_data': data})


def backup(cfg, send=True):
    """Make the zip, copy it to backup.dir and send it to Drive. Returns a summary; Drive errors do not lose the zip."""
    path, count, big = make(cfg)
    s = settings(cfg)
    summary = {'zip': str(path), 'files': count, 'bytes': path.stat().st_size,
               'skipped_big': [str(p) for p in big], 'copy': None, 'drive': None, 'drive_error': None}
    if s['dir']:
        folder = Path(s['dir'])
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, folder/path.name)
        for old in sorted(folder.glob('apps-*.zip'), reverse=True)[max(1, int(s['keep'])):]:
            old.unlink()
        summary['copy'] = str(folder/path.name)
    if send:
        try:
            result = upload(cfg, path)
            summary['drive'] = f"{result.get('folder', 'Drive')}/{result.get('saved', path.name)}"
        except Exception as e:  # Colab is often off; the local zip is still a backup.
            summary['drive_error'] = str(e).splitlines()[0][:300] if str(e) else type(e).__name__
    return summary


def latest_from_drive(cfg, folder):
    """Download the newest Drive backup (list_backups) into folder; returns its path."""
    from mcp_bridge import call
    items = call(cfg['mcp'], 'list_backups', {}).get('backups') or []
    if not items:
        raise ValueError("Drive'da yedek yok.")
    url = items[0]['url']
    if url.startswith('/'):
        url = urljoin(cfg['mcp']['url'], url)
    target = Path(folder)/items[0]['name']
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=300) as r, target.open('wb') as f:
        shutil.copyfileobj(r, f)
    return target


def safe_names(z):
    for name in z.namelist():
        p = PurePosixPath(name)
        if p.is_absolute() or '..' in p.parts or ':' in name or '\\' in name:
            raise ValueError('Yedekte güvensiz dosya yolu: ' + name)
    return z.namelist()


def restore(cfg, source, apply=False):
    """Unpack source (a zip path, or "drive" for the newest Drive backup) into workspace/restore/<name>. With
    apply=True its files are then copied over workspace/apps, after a fresh local backup of the current data."""
    apps, out = roots(cfg)
    zpath = latest_from_drive(cfg, out/'drive') if source == 'drive' else Path(source)
    if not zpath.is_file():
        raise ValueError(f'Yedek bulunamadı: {zpath}')
    staging = Path(cfg['workspace'])/'restore'/zpath.stem
    if staging.exists():
        shutil.rmtree(staging)
    with zipfile.ZipFile(zpath) as z:
        names = safe_names(z)
        z.extractall(staging)
    result = {'zip': str(zpath), 'files': len([n for n in names if not n.endswith('/')]), 'staging': str(staging),
              'applied': False, 'before': None}
    if apply:
        if apps.is_dir() and any(apps.iterdir()):
            result['before'] = str(make(cfg, datetime.now().strftime('%Y%m%d-%H%M%S') + '-geri-oncesi')[0])
        shutil.copytree(staging, apps, dirs_exist_ok=True)
        result['applied'] = True
    return result
