"""Data-only bundled character packs. No executable imports from packs."""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]


def load_packs():
    result = {}
    for file in sorted((ROOT/'packs').glob('*/pack.json')):
        pack = json.loads(file.read_text())
        if pack.get('schema') != 1 or pack.get('id') != file.parent.name:
            raise ValueError(f'Invalid pack: {file}')
        result[pack['id']] = pack
    return result


def atlases():
    for pack in load_packs().values():
        folder = ROOT/'packs'/pack['id']
        for name, relative in pack.get('characters', {}).items():
            file = (folder/relative).resolve()
            if not file.is_relative_to(folder.resolve()): raise ValueError('Atlas escapes pack')
            yield name, file
