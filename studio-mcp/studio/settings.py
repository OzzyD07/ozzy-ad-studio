"""Runtime settings from environment variables (the Colab notebook sets them from Colab Secrets)."""
import os
from dataclasses import dataclass
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    home: Path  # jobs/, assets/, outputs/ (on Drive in Colab, so a restart keeps history)
    workflows: Path  # *.api.json templates exported from ComfyUI + *.bind.json bindings
    comfy_url: str
    token: str
    public_url: str  # optional absolute base for output links; relative links otherwise
    host: str
    port: int
    job_timeout: int  # seconds per job before it is marked failed

    @classmethod
    def from_env(cls, **overrides):
        env = os.environ.get
        values = dict(
            home=Path(env('STUDIO_HOME', '/content/drive/MyDrive/OzzyAdStudio')),
            workflows=Path(env('STUDIO_WORKFLOWS', str(PACKAGE/'workflows'))),
            comfy_url=env('COMFY_URL', 'http://127.0.0.1:8188').rstrip('/'),
            token=env('STUDIO_TOKEN', ''),
            public_url=env('STUDIO_PUBLIC_URL', '').rstrip('/'),
            host=env('STUDIO_HOST', '0.0.0.0'),
            port=int(env('STUDIO_PORT', '8000')),
            job_timeout=int(env('STUDIO_JOB_TIMEOUT', '5400')),
        )
        values.update(overrides)
        s = cls(**values)
        for sub in ('jobs', 'assets', 'outputs'):
            (s.home/sub).mkdir(parents=True, exist_ok=True)
        return s
