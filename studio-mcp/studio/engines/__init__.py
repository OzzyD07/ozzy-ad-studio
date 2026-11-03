"""Generation engines: each turns tool arguments into a ComfyUI API workflow.

kind: 'video' or 'image'. The queue runs all jobs of one kind before switching, and frees VRAM on a switch (K-10).
"""
import copy
import json
import random
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent


class EngineError(ValueError):
    pass


def pick(files, preferences, override=None):
    """Choose a model file: an explicit override, else the first preference pattern that matches a file."""
    if override:
        return override
    for pattern in preferences:
        for name in files:
            if re.search(pattern, name, re.I):
                return name
    return None


def new_seed(seed):
    return random.randint(1, 2**31 - 1) if seed is None or int(seed) <= 0 else int(seed)


class Engine:
    name = ''
    kind = 'video'
    title = ''
    qualities = ('draft', 'standard', 'high', 'max')

    def template(self):
        return copy.deepcopy(json.loads((HERE/f'{self.name}.api.json').read_text(encoding='utf-8')))

    def describe(self):
        return {'name': self.name, 'kind': self.kind, 'title': self.title, 'qualities': list(self.qualities)}

    def validate(self, request):
        """Raise EngineError for a bad request before it enters the queue."""

    def build(self, request, refs, model_files):
        """-> (workflow, metadata). refs: prepared reference inputs; model_files: {folder: [file names]}."""
        raise NotImplementedError


def registry():
    from .minimax_h3 import MiniMaxH3
    from .qwen_image import QwenImage
    return {e.name: e for e in (MiniMaxH3(), QwenImage())}
