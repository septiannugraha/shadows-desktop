"""Install into an isolated Pi agent directory and exercise the real bridge, no provider call."""
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = os.environ.get('SHADOWS_TEST_SOURCE', str(ROOT))
pi = os.environ.get('SHADOWS_TEST_PI') or shutil.which('pi')
if not pi: raise SystemExit('Pi is required for this integration check')
with tempfile.TemporaryDirectory(prefix='shadows-pi-smoke-') as folder:
    root = Path(folder)
    env = {**os.environ, 'PI_CODING_AGENT_DIR': str(root/'agent'), 'SHADOWS_STATE_DIR': str(root/'runtime/sessions'), 'SHADOWS_CONFIG': str(root/'config.json')}
    subprocess.run([pi, 'install', SOURCE], env=env, cwd=root, check=True, capture_output=True, text=True)
    settings = json.loads((root/'agent/settings.json').read_text())
    assert any(entry == SOURCE or (root/'agent'/entry).resolve() == ROOT for entry in settings['packages']), settings
    process = subprocess.Popen([pi, '--mode', 'rpc', '--no-session', '--no-skills', '--no-prompt-templates'], cwd=root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        process.stdin.write(json.dumps({'id':'mode','type':'prompt','message':'/shadows-mode commander'})+'\n');process.stdin.flush()
        deadline = time.time()+10
        while time.time()<deadline:
            snapshots = list((root/'runtime/sessions').glob('*.json'))
            if snapshots:
                data=json.loads(snapshots[0].read_text())
                if data.get('mode') == 'commander': break
            time.sleep(.1)
        else: raise AssertionError('Bridge did not publish commander state')
        assert data['protocol']=='shadows-desktop/1' and data['host']=='tenka'
        process.stdin.write(json.dumps({'id':'neutral','type':'prompt','message':'/shadows-mode neutral'})+'\n');process.stdin.flush()
        deadline = time.time()+5
        while time.time()<deadline:
            if json.loads(snapshots[0].read_text())['mode']=='neutral':break
            time.sleep(.1)
        else:raise AssertionError('Return to neutral failed')
        print('PASS: clean Pi package install, standalone bridge, two mode commands; no model call')
    finally:
        process.terminate()
        stdout,stderr=process.communicate(timeout=5)
        if stderr: print(stderr[:3000])
    subprocess.run([pi,'remove',SOURCE],env=env,cwd=root,check=True,capture_output=True,text=True)
    assert not json.loads((root/'agent/settings.json').read_text()).get('packages',[])
    print('PASS: Pi package removal from isolated config')
