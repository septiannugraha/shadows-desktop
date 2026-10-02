#!/usr/bin/env python3
"""Launch and diagnose the app without importing GTK for non-GUI commands."""
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from model import runtime_root, read_sessions, atomic_json
from packs import ROOT, load_packs, atlases


def config_path():
    return Path(os.environ.get('SHADOWS_CONFIG', str(Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home()/'.config')))/'shadows-desktop/config.json')))


def doctor():
    failures = 0
    print('Shadows Desktop 0.1.0 · local protocol shadows-desktop/1')
    print(f'Package: {ROOT}\nConfig: {config_path()}\nSessions: {runtime_root()}')
    for module in ['gi', 'cairo']:
        available = importlib.util.find_spec(module) is not None
        print(f'{module}: {"OK" if available else "MISSING"}')
        failures += not available
    gtk = subprocess.run([sys.executable, '-c', "import gi; gi.require_version('Gtk','4.0'); from gi.repository import Gtk"], capture_output=True)
    print('GTK4: '+('OK' if gtk.returncode == 0 else 'MISSING')); failures += gtk.returncode != 0
    layer = subprocess.run([sys.executable, '-c', "import gi; gi.require_version('Gtk4LayerShell','1.0')"], capture_output=True)
    print('Layer-shell: '+('available' if layer.returncode == 0 else 'unavailable; normal-window fallback'))
    print('Display: '+(os.environ.get('WAYLAND_DISPLAY') or os.environ.get('DISPLAY') or 'none (launch from a graphical session)'))
    print('Pi executable: '+(os.environ.get('SHADOWS_PI_BINARY') or shutil.which('pi') or 'not on PATH; configure SHADOWS_PI_BINARY for delegation'))
    try:
        for name, atlas_path in atlases():
            atlas = json.loads(atlas_path.read_text())
            for frame in atlas['frames'].values():
                image = (atlas_path.parent/frame['image']).resolve()
                assert image.is_relative_to(atlas_path.parent.resolve()) and image.is_file()
                assert frame['x'] >= 0 and frame['y'] >= 0 and frame['width'] > 0 and frame['height'] > 0
                assert frame['x']+frame['width'] <= atlas['sheetWidth'] and frame['y']+frame['height'] <= atlas['sheetHeight']
        print('Character pack metadata: OK')
    except (ValueError, KeyError, OSError, AssertionError) as error:
        print(f'Character packs: INVALID ({error})'); failures += 1
    incompatible = 0
    for file in runtime_root().glob('*.json'):
        try:
            data=json.loads(file.read_text())
            if data.get('schema') != 1 or data.get('protocol') != 'shadows-desktop/1': incompatible += 1
        except (ValueError, OSError, AttributeError): continue
    if incompatible:
        print(f'INCOMPATIBLE snapshots: {incompatible}; update bridge and desktop together.'); failures += 1
    live = read_sessions(runtime_root())
    print(f'Live Pi instances: {len(live)}')
    for instance, session in live.items(): print(f'  {instance} · {session["name"]} · {session["mode"]}')
    if not live: print('Waiting for Pi: install this package, /reload, then /shadows. Remote Pi is not supported in v0.1.')
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    subs.add_parser('doctor')
    setup = subs.add_parser('configure')
    setup.add_argument('--pack', choices=list(load_packs()))
    setup.add_argument('--persona', choices=['on','off'])
    setup.add_argument('--delegation', choices=['on','off'])
    launch = subs.add_parser('launch')
    launch.add_argument('--session')
    launch.add_argument('--windowed', action='store_true')
    launch.add_argument('--toggle', action='store_true')
    launch.add_argument('--dismiss', action='store_true')
    args = parser.parse_args()
    if args.command == 'doctor': return doctor()
    if args.command == 'configure':
        file = config_path()
        try: data = json.loads(file.read_text())
        except FileNotFoundError: data = {}
        if not isinstance(data, dict): raise ValueError('Config must be an object')
        if args.pack: data['pack'] = args.pack
        for key in ['persona', 'delegation']:
            value = getattr(args, key)
            if value: data[key] = value == 'on'
        atomic_json(file, data)
        print(f'Saved {file}. Defaults apply to new sessions; use /shadows-mode for the current session.')
        return 0
    command = [sys.executable, str(ROOT/'desktop/desktop.py')]
    if args.session: command += ['--session', args.session]
    for flag in ['windowed','toggle','dismiss']:
        if getattr(args, flag): command.append('--'+flag)
    directory = Path(os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state')))/'shadows-desktop'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory/'desktop.log').open('a') as log:
        return subprocess.call(command, stdout=log, stderr=log)

if __name__ == '__main__':
    try: sys.exit(main())
    except (ValueError, OSError) as error: sys.exit(f'Shadows Desktop: {error}')
