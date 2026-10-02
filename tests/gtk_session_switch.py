"""Real GTK regression with isolated state and no Pi/model calls."""
import os
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"desktop"))
import desktop
from desktop import Gtk, Gio, GLib, Window
from model import atomic_json
from types import SimpleNamespace
import time

sandbox = tempfile.TemporaryDirectory(prefix='shadows-gtk-test-')
root = Path(sandbox.name)
os.environ['SHADOWS_STATE_DIR'] = str(root/'sessions')
desktop.CONFIG = root/'settings.json'
app = Gtk.Application(application_id='io.shadowsdesktop.regression', flags=Gio.ApplicationFlags.NON_UNIQUE)
failures = []

def descendants(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from descendants(child)
        child = child.get_next_sibling()

def start(application):
    now = int(time.time()*1000)
    for key in ('a', 'b'):
        atomic_json(root/'sessions'/f'{key}.json', dict(schema=1, protocol="shadows-desktop/1", host="companion", mode="neutral", instanceId=key, sessionId=key,
            pid=os.getpid(), name=f'Test {key}', cwd='/test', phase='idle', agents={},
            heartbeatAt=now, activityAt=now))
    window = Window(application, SimpleNamespace(session=None, windowed=False))
    window.present()
    assert not window.details.get_visible() and not window.whisper.get_visible()
    window.toggle_details()
    assert window.details.get_visible()
    window.toggle_details()
    count = 0
    def switch():
        nonlocal count
        try:
            views = [w for w in descendants(window.session_select) if isinstance(w, Gtk.ListView)]
            assert views, 'Dropdown ListView was not found'
            index = 1 + count % 2
            views[0].get_model().select_item(index, True)
            views[0].emit('activate', index)
            assert window.selection.pinned == ('a' if index == 1 else 'b'), (index, window.selection.pinned)
            count += 1
            if count < 30: return True
            (root/'sessions/b.json').unlink()
            window.poll()
            assert window.selection.pinned == 'b' and window.session is None
            window.session_select.set_selected(0)
            GLib.idle_add(finish)
        except Exception as error:
            failures.append(repr(error)); application.quit()
        return False
    def finish():
        try:
            assert window.get_width() <= 520, window.get_width()
            window.toggle_reply()
            assert window.whisper.get_visible()
            window.toggle_reply()
            assert not window.whisper.get_visible()
            window.selection.pinned = None
            window.poll()
            assert window.selection.pinned is None
            assert window.session['instanceId'] == 'a'
            print('PASS: 30 GTK row activations, disconnected pin, and return to Auto', flush=True)
        except Exception as error: failures.append(repr(error))
        application.quit()
        return False
    GLib.timeout_add(70, switch)
app.connect('activate', start)
app.run([])
sandbox.cleanup()
if failures: raise SystemExit('\n'.join(failures))
