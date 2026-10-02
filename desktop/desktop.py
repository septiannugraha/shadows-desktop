#!/usr/bin/env python3
"""Shadows Desktop: a session-owned visual-novel stage for Pi."""
import os
import sys

if os.path.exists('/usr/lib/libgtk4-layer-shell.so') and 'libgtk4-layer-shell' not in os.environ.get('LD_PRELOAD', ''):
    os.environ['LD_PRELOAD'] = '/usr/lib/libgtk4-layer-shell.so:' + os.environ.get('LD_PRELOAD', '')
    os.execv(sys.executable, [sys.executable, *sys.argv])

import json
import math
import time
import uuid
import argparse
from pathlib import Path
import cairo
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, Gio, GLib, Pango
try:
    gi.require_version('Gtk4LayerShell', '1.0')
    from gi.repository import Gtk4LayerShell as Layer
except (ValueError, ImportError):
    Layer = None
from model import Selection, read_sessions, runtime_root, cast_for, expression, atomic_json, CHARACTERS, SpeechClock, speaker_for

from packs import load_packs, atlases
PACKS = load_packs()
ROOT = Path(__file__).resolve().parent
CONFIG = Path(os.environ.get('SHADOWS_CONFIG', str(Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home()/'.config')))/'shadows-desktop/config.json')))
CSS = b'''
window { background: transparent; }
.dialogue { background: rgba(19,16,29,.97); border: 1px solid #796341;
 border-radius: 18px; padding: 12px; box-shadow: 0 8px 22px rgba(0,0,0,.4); }
.commander { border-color: #77b7ad; }
.commander .speaker { color: #98e0cb; }
.speaker { color: #f0c469; font-size: 15px; font-weight: 700; }
.body { color: #eee7f5; font-size: 14px; }
.meta { color: #c5b5d5; font-size: 11px; }
.roster button { border-radius: 12px; padding: 5px 9px; }
button, entry, dropdown { background: #292135; color: #eee7f5; border-radius: 9px; }
button:hover { background: #44304f; }
entry { padding: 7px; }
.chrome { min-width: 20px; min-height: 20px; padding: 2px 5px; background: transparent; }
.session-chip { color: #b6a6c3; font-size: 10px; }
'''


class Sprites:
    def __init__(self):
        self.sheets = {}
        self.atlases = {}
        for name, atlas_path in atlases():
            folder = atlas_path.parent
            try:
                atlas = json.loads((folder/'atlas.json').read_text())
                self.atlases[name] = atlas
                for frame in atlas['frames'].values():
                    file = folder/frame['image']
                    if str(file) not in self.sheets:
                        self.sheets[str(file)] = cairo.ImageSurface.create_from_png(str(file))
                    frame['_sheet'] = str(file)
            except (OSError, ValueError, cairo.Error) as error:
                print(f'Shadows Desktop: cannot load {name}: {error}', file=sys.stderr)

    def draw(self, cr, name, state, x, y, width, height, opacity=1):
        atlas = self.atlases.get(name)
        if not atlas:
            # A code-drawn neutral badge also represents unknown agents honestly.
            cr.save(); cr.set_source_rgba(.25, .38, .43, opacity)
            cr.arc(x+width/2, y+height*.48, width*.38, 0, math.tau); cr.fill()
            cr.set_source_rgba(.85, .94, .95, opacity); cr.set_font_size(width*.15)
            cr.move_to(x+width*.20, y+height*.5); cr.show_text(name.title()[:8])
            cr.restore(); return
        f = atlas['frames'].get(state, atlas['frames']['resting-smile'])
        cr.save()
        cr.rectangle(x, y, width, height); cr.clip()
        cr.translate(x, y); cr.scale(width/f['width'], height/f['height'])
        cr.set_source_surface(self.sheets[f['_sheet']], -f['x'], -f['y'])
        cr.paint_with_alpha(opacity)
        cr.restore()


class Window(Gtk.ApplicationWindow):
    def __init__(self, app, args):
        super().__init__(application=app, title='Shadows Desktop')
        self.set_decorated(False)
        self.set_resizable(False)
        self.args = args
        self.selection = Selection()
        self.session = None
        self.sessions = {}
        self.selected_run = None
        self.current_key = None
        self.entered = {}
        self.last_cast = {}
        self.sprites = Sprites()
        self.session_options = []
        self.session_signature = None
        self.selection_refresh = None
        self.roster_signature = None
        self.sending = None
        self.last_display_write = 0
        self.pat_until = 0
        self.speech_clock = SpeechClock()
        self.settings = {'scale': .9, 'right': 24, 'bottom': 24, 'quiet': False, 'private': False, 'collapsed': False}
        try: self.settings.update(json.loads(CONFIG.read_text()))
        except (OSError, ValueError): pass
        self.settings['scale'] = max(.65, min(1.4, float(self.settings['scale'])))
        self.selection.pinned = args.session or self.settings.get('pinned')
        self.layered = bool(Layer and not args.windowed and Layer.is_supported())
        if self.layered:
            Layer.init_for_window(self)
            Layer.set_namespace(self, 'shadows-desktop-v1')
            Layer.set_layer(self, Layer.Layer.OVERLAY)
            Layer.set_anchor(self, Layer.Edge.RIGHT, True)
            Layer.set_anchor(self, Layer.Edge.BOTTOM, True)
            Layer.set_keyboard_mode(self, Layer.KeyboardMode.NONE)
            self.position()
        else:
            self.set_decorated(True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(box)
        self.stage = Gtk.DrawingArea()
        self.stage.set_draw_func(self.draw_stage)
        box.append(self.stage)
        drag = Gtk.GestureDrag.new()
        drag.connect('drag-begin', self.drag_begin)
        drag.connect('drag-update', self.drag_update)
        drag.connect('drag-end', self.drag_end)
        self.stage.add_controller(drag)
        self.dragged = False
        click = Gtk.GestureClick.new(); click.connect('released', self.headpat); self.stage.add_controller(click)
        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect('scroll', self.zoom); self.stage.add_controller(scroll)
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        panel.add_css_class('dialogue'); box.append(panel); self.panel = panel
        top = Gtk.Box(spacing=8); panel.append(top)
        self.speaker = Gtk.Label(label='Shadows Desktop', xalign=0); self.speaker.add_css_class('speaker'); self.speaker.set_hexpand(True)
        top.append(self.speaker)
        self.badge = Gtk.Label(); self.badge.add_css_class('meta'); top.append(self.badge)
        menu = Gtk.Button(label='⋯'); menu.add_css_class('chrome'); menu.set_tooltip_text('Sessions and controls'); menu.connect('clicked', self.toggle_details); top.append(menu)
        reply = Gtk.Button(label='↩'); reply.add_css_class('chrome'); reply.set_tooltip_text('Reply to this session'); reply.connect('clicked', self.toggle_reply); top.append(reply)
        compact = Gtk.Button(label='−'); compact.add_css_class('chrome'); compact.set_tooltip_text('Collapse or expand the stage'); compact.connect('clicked', self.collapse); top.append(compact)
        close = Gtk.Button(label='×'); close.add_css_class('chrome'); close.set_tooltip_text('Dismiss Shadows Desktop'); close.connect('clicked', lambda _: app.quit()); top.append(close)
        self.message = Gtk.Label(xalign=0, yalign=0); self.message.set_wrap(True); self.message.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.message.set_selectable(True); self.message.add_css_class('body')
        self.message.set_max_width_chars(43)
        message_scroll = Gtk.ScrolledWindow(); message_scroll.set_min_content_height(34); message_scroll.set_max_content_height(100)
        message_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); message_scroll.set_propagate_natural_height(True); message_scroll.set_child(self.message); panel.append(message_scroll)
        self.session_chip = Gtk.Label(xalign=0); self.session_chip.add_css_class('session-chip')
        self.session_chip.set_ellipsize(Pango.EllipsizeMode.MIDDLE); self.session_chip.set_max_width_chars(43); panel.append(self.session_chip)
        self.details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        self.details.set_visible(False); panel.append(self.details)
        self.mode_button = Gtk.Button(label='Mode · Master Shadow'); self.mode_button.connect('clicked', self.change_mode); self.details.append(self.mode_button)
        self.session_select = Gtk.DropDown.new_from_strings(['Auto · waiting for Pi'])
        self.session_select.connect('notify::selected', self.select_session); self.details.append(self.session_select)
        self.session_meta = Gtk.Label(xalign=0); self.session_meta.add_css_class('meta'); self.session_meta.set_ellipsize(Pango.EllipsizeMode.MIDDLE); self.details.append(self.session_meta)
        self.roster = Gtk.Box(spacing=5); self.roster.add_css_class('roster')
        roster_scroll = Gtk.ScrolledWindow(); roster_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER); roster_scroll.set_child(self.roster); self.details.append(roster_scroll)
        controls = Gtk.Box(spacing=5); self.details.append(controls)
        self.quiet = Gtk.CheckButton(label='Quiet motion'); self.quiet.set_active(bool(self.settings['quiet'])); self.quiet.connect('toggled', self.options); controls.append(self.quiet)
        self.private = Gtk.CheckButton(label='Hide text'); self.private.set_active(bool(self.settings['private'])); self.private.connect('toggled', self.options); controls.append(self.private)
        history_button = Gtk.Button(label='History'); history_button.connect('clicked', self.toggle_history); controls.append(history_button)
        self.history = Gtk.Label(xalign=0); self.history.set_wrap(True); self.history.set_max_width_chars(43); self.history.add_css_class('meta'); self.history.set_visible(False); self.details.append(self.history)
        self.whisper = Gtk.Entry(); self.whisper.set_visible(False); self.whisper.set_placeholder_text('Reply to this session…'); self.whisper.set_max_length(4000)
        self.whisper.connect('activate', self.send); panel.append(self.whisper)
        focus = Gtk.EventControllerFocus(); focus.connect('enter', self.begin_whisper); focus.connect('leave', lambda _: self.keyboard(False)); self.whisper.add_controller(focus)
        # Request on-demand keyboard access on click before Entry tries to focus.
        entry_click = Gtk.GestureClick.new(); entry_click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        entry_click.connect('pressed', lambda *_: self.keyboard(True)); self.whisper.add_controller(entry_click)
        keys = Gtk.EventControllerKey(); keys.connect('key-pressed', self.key); self.whisper.add_controller(keys)
        self.delivery = Gtk.Label(xalign=0); self.delivery.add_css_class('meta'); self.delivery.set_wrap(True); self.delivery.set_max_width_chars(43); self.delivery.set_visible(False); self.delivery.connect('notify::label', lambda label, _: label.set_visible(bool(label.get_text()))); panel.append(self.delivery)
        self.scale_stage()
        self.poll()
        GLib.timeout_add(200, self.poll)
        GLib.timeout_add(33, self.animate)

    def save(self):
        self.settings['pinned'] = self.selection.pinned
        try: atomic_json(CONFIG, self.settings)
        except OSError as error: self.delivery.set_text(f'Could not save preferences: {error}')

    def position(self):
        if self.layered:
            Layer.set_margin(self, Layer.Edge.RIGHT, int(self.settings['right']))
            Layer.set_margin(self, Layer.Edge.BOTTOM, int(self.settings['bottom']))

    def scale_stage(self):
        scale = self.settings['scale']
        self.stage.set_content_width(int(440*scale)); self.stage.set_content_height(int(220*scale))
        self.panel.set_size_request(int(440*scale), -1)
        self.stage.set_visible(not self.settings['collapsed'])

    def zoom(self, _controller, _dx, dy):
        self.settings['scale'] = max(.65, min(1.4, self.settings['scale'] - dy*.04)); self.scale_stage(); self.save(); return True

    def drag_begin(self, *_):
        self.dragged = False; self.drag_origin = (self.settings['right'], self.settings['bottom'])

    def drag_update(self, _gesture, dx, dy):
        if abs(dx)+abs(dy) > 5: self.dragged = True
        if self.dragged:
            self.settings['right'] = max(0, self.drag_origin[0]-dx)
            self.settings['bottom'] = max(0, self.drag_origin[1]-dy)
            self.position()

    def drag_end(self, *_): self.save()

    def headpat(self, *_):
        if not self.dragged:
            self.pat_until = time.monotonic()+2
            self.stage.queue_draw()  # local visual reaction; never writes another session's state

    def collapse(self, *_): self.settings['collapsed'] = not self.settings['collapsed']; self.scale_stage(); self.save()

    def options(self, *_):
        self.settings['quiet'] = self.quiet.get_active(); self.settings['private'] = self.private.get_active(); self.save(); self.poll()

    def change_mode(self, *_):
        live = read_sessions(runtime_root()).get(self.current_key)
        if not live or not live.get('modeSwitch'):
            self.delivery.set_text('Reload Pi extensions with /reload to enable modes.'); return
        self.selection.pinned = live['instanceId']; self.save()
        request_id = str(uuid.uuid4())
        modes = list(PACKS)
        current = live.get('mode', 'neutral')
        mode = modes[(modes.index(current)+1) % len(modes)] if current in modes else 'neutral'
        request = dict(schema=1, id=request_id, type='mode', mode=mode, instanceId=live['instanceId'], sessionId=live['sessionId'], at=int(time.time()*1000))
        try:
            atomic_json(runtime_root()/'inbox'/live['instanceId']/f'{request_id}.json', request)
            self.sending = (live['instanceId'], request_id, time.monotonic())
            self.delivery.set_text('Requesting mode change in this Pi session…')
        except OSError as error: self.delivery.set_text(f'Could not switch mode: {error}')

    def toggle_details(self, *_):
        self.details.set_visible(not self.details.get_visible())

    def toggle_reply(self, *_):
        shown = not self.whisper.get_visible()
        self.whisper.set_visible(shown)
        if shown:
            self.keyboard(True); self.whisper.grab_focus()
        else:
            self.set_focus(None); self.keyboard(False)

    def toggle_history(self, *_): self.history.set_visible(not self.history.get_visible())

    def keyboard(self, enabled):
        if self.layered: Layer.set_keyboard_mode(self, Layer.KeyboardMode.ON_DEMAND if enabled else Layer.KeyboardMode.NONE)

    def begin_whisper(self, *_):
        self.keyboard(True)
        if self.current_key:
            self.selection.pinned = self.current_key
            self.save(); self.poll()

    def key(self, _controller, keyval, *_):
        if keyval == Gdk.KEY_Escape:
            self.whisper.set_text(''); self.whisper.set_visible(False); self.set_focus(None); self.keyboard(False); return True
        return False

    def select_session(self, *_):
        index = self.session_select.get_selected()
        if index < len(self.session_options):
            self.selection.pinned = self.session_options[index]
            self.selected_run = None; self.save()
            # GTK still owns the activated popup row until this signal returns.
            # Defer refresh so session churn cannot replace its model mid-signal.
            if self.selection_refresh is None:
                self.selection_refresh = GLib.idle_add(self.refresh_selection)

    def refresh_selection(self):
        self.selection_refresh = None
        self.poll()
        return False

    def select_run(self, _button, run): self.selected_run = run; self.poll()

    def send(self, entry):
        text = entry.get_text().strip()
        if not text: return
        # Revalidate the exact displayed instance at send time, never auto-switch here.
        key = self.current_key
        live = read_sessions(runtime_root()).get(key)
        if not live:
            self.delivery.set_text('That session is disconnected. Select a live session before sending.'); return
        request_id = str(uuid.uuid4())
        request = dict(schema=1, id=request_id, instanceId=key, sessionId=live['sessionId'], at=int(time.time()*1000), text=text)
        try:
            atomic_json(runtime_root()/'inbox'/key/f'{request_id}.json', request)
            self.sending = (key, request_id, time.monotonic())
            self.delivery.set_text(f'Waiting for {live["name"]} to accept your whisper…')
            entry.set_text(''); entry.set_visible(False); self.set_focus(None); self.keyboard(False)
        except OSError as error: self.delivery.set_text(f'Could not queue whisper: {error}')

    def poll(self):
        sessions = read_sessions(runtime_root()); self.sessions = sessions
        missing_pin = self.selection.pinned if self.selection.pinned not in sessions else None
        signature = tuple(sorted((k, s.get('name', ''), s.get('cwd', '')) for k, s in sessions.items())) + ((missing_pin,),)
        if signature != self.session_signature:
            self.session_signature = signature
            options = [None] + sorted(sessions)
            labels = ['Auto · stay with the busy session'] + [f'{sessions[k]["name"]} · {Path(sessions[k]["cwd"]).name} · {k[:8]}' for k in options[1:]]
            if self.selection.pinned and self.selection.pinned not in sessions:
                options.append(self.selection.pinned); labels.append('Pinned session · disconnected')
            # Block notifications during model replacement to preserve the pin.
            self.session_options = []
            self.session_select.set_model(Gtk.StringList.new(labels))
            self.session_select.set_selected(options.index(self.selection.pinned) if self.selection.pinned in options else 0)
            self.session_options = options
        # A change of pin alone must not replace the dropdown's model.
        selected = self.session_options.index(self.selection.pinned) if self.selection.pinned in self.session_options else 0
        if self.session_select.get_selected() != selected:
            options = self.session_options
            self.session_options = []
            self.session_select.set_selected(selected)
            self.session_options = options
        session = self.selection.choose(sessions)
        key = session['instanceId'] if session else None
        if key != self.current_key or (session or {}).get('mode', 'neutral') != getattr(self, 'current_mode', 'neutral'):
            self.selected_run = None; self.entered = {}; self.last_cast = {}; self.current_key = key
        self.session = session
        self.current_mode = (session or {}).get('mode', 'neutral')
        if time.monotonic()-self.last_display_write > 3 or key != getattr(self, 'published_key', None):
            try:
                atomic_json(runtime_root().parent/'display.json', dict(instanceId=key,
                    sessionId=session['sessionId'] if session else None, desktopPid=os.getpid(), at=int(time.time()*1000)))
                self.last_display_write = time.monotonic(); self.published_key = key
            except OSError: pass
        self.whisper.set_sensitive(session is not None)
        commander = (session or {}).get('mode') == 'commander'
        pack = PACKS.get((session or {}).get('mode', 'neutral'), PACKS['neutral'])
        self.mode_button.set_label('Pack · ' + pack['name'] + ' ⇄')
        self.mode_button.set_sensitive(session is not None)
        if commander: self.panel.add_css_class('commander')
        else: self.panel.remove_css_class('commander')
        if not session:
            self.speaker.set_text('Shadows Desktop'); self.badge.set_text('Disconnected' if self.selection.pinned else 'Waiting')
            self.session_meta.set_text('Choose a live session, or run /shadows in Pi.'); self.session_chip.set_text('Disconnected' if self.selection.pinned else 'Waiting for Pi · ⋯ to choose a session')
            self.message.set_text('The Shadows will join when Pi activates them. Reload Pi extensions with /reload after installing.')
        else:
            runs = session['agents']; active = [a for a in runs.values() if a['phase']=='running']
            picked = runs.get(self.selected_run)
            cast = cast_for(session, self.selected_run)
            speaker = speaker_for(session, self.selected_run)
            self.speaker.set_text(speaker['agent'].title())
            self.badge.set_text(speaker['phase'].title() + (f' · {len(active)}' if active else ''))
            short_id = session['sessionId'][:8]
            prefix = 'Pinned' if self.selection.pinned else 'Auto'
            self.session_meta.set_text(f'{prefix} · {session["name"]} · {short_id} · PID {session["pid"]} · {session["cwd"]}')
            self.session_meta.set_tooltip_text(session['cwd'])
            self.session_chip.set_text(f'{prefix} · {session["name"]} · {short_id}')
            self.session_chip.set_tooltip_text(self.session_meta.get_text())
            text = (speaker.get('dialogue') or ('Composing a response…' if speaker['phase'] == 'running' else 'No spoken response was captured for this run.')) if speaker['runId'] != '__host__' else session.get('message', '')
            if self.settings['private']: text = 'Dialogue hidden · task status remains visible.'

            self.message.set_text(text or pack['greeting'])
        runs = session['agents'] if session else {}
        roster_sig = (commander,) + tuple((a['runId'], a['phase'], a['agent']) for a in runs.values())
        if roster_sig != self.roster_signature:
            self.roster_signature = roster_sig
            while self.roster.get_first_child(): self.roster.remove(self.roster.get_first_child())
            alpha = Gtk.Button(label=pack['host'].title()); alpha.connect('clicked', self.select_run, '__host__'); self.roster.append(alpha)
            for a in sorted(runs.values(), key=lambda a: a['startedAt'], reverse=True)[:12]:
                icon = {'running':'●', 'success':'✓', 'error':'!', 'cancelled':'−'}.get(a['phase'], '·')
                button = Gtk.Button(label=f'{icon} {a["agent"].title()}')
                button.set_tooltip_text(f'Run {a["runId"][:8]} · {a["phase"]}')
                button.connect('clicked', self.select_run, a['runId']); self.roster.append(button)
        history = (session or {}).get('history', [])[-5:]
        self.history.set_text('\n'.join(f'{h["agent"].title()} · {h["phase"]}' + ('' if self.settings['private'] else f' — {h["text"][:110]}') for h in history) or 'No delegated activity yet.')
        if self.sending:
            owner, request, since = self.sending
            delivery = sessions.get(owner, {}).get('delivery', {})
            if delivery.get('id') == request:
                self.delivery.set_text({'queued':'Whisper queued in the selected Pi session.', 'mode-changed':'Mode changed · ready for your next message.', 'mode-busy':'Wait for the current turn and subagents to finish, then switch again.'}.get(delivery['status'], 'Pi could not accept the request. Try again in its terminal.'))
                self.sending = None
            elif time.monotonic()-since > 10:
                self.delivery.set_text('No acknowledgement yet. Check that Pi session before resending.'); self.sending = None
        self.stage.queue_draw()
        return True

    def animate(self):
        if not self.settings['quiet'] and self.stage.get_visible(): self.stage.queue_draw()
        return True

    def draw_stage(self, _area, cr, width, height):
        now = time.monotonic()
        cast = cast_for(self.session, self.selected_run)
        current = {a['runId']: a for a in cast}
        for key, a in current.items():
            if key not in self.last_cast: self.entered[key] = now
        self.last_cast = current
        cr.save(); cr.scale(width/660, height/330)
        count = len(cast)
        speaker = speaker_for(self.session, self.selected_run)
        hero_index = next((i for i, a in enumerate(cast) if a['agent'] == speaker['agent']), 0)
        # Draw the speaker last, at the center, so companions cannot cover her.
        order = [i for i in range(count) if i != hero_index] + [hero_index]
        companions = [i for i in range(count) if i != hero_index]
        for i in order:
            a = cast[i]
            hero = i == hero_index
            h = 326 if hero else 285
            w = h*.75
            x = (660-w)/2 if hero else (10 if companions.index(i) == 0 else 442)
            progress = 1 if self.settings['quiet'] else min(1, (now-self.entered.get(a['runId'], now))/.3)
            eased = 1-(1-progress)**3
            x += (1-eased)*60
            alpha = (1 if hero else .60)*eased
            dialogue = a.get('dialogue', '') if a['runId'] != '__host__' else ((self.session or {}).get('message', '') if a['phase'] in ('speaking', 'idle') else '')
            speaking = self.speech_clock.update((self.current_key, a['runId']), dialogue, now)
            state = expression(a['phase'])
            if not self.settings['quiet']:
                if speaking and hero: state = ['speaking-small','speaking-wide','speaking-rounded','resting-smile'][int(now*7)%4]
                if (now + i * .73) % 4.3 < .14: state='listening-blink'
            if self.pat_until>now and hero: state='success-delighted'
            self.sprites.draw(cr, a['agent'], state, x, 330-h, w, h, alpha)
        cr.restore()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session'); parser.add_argument('--windowed', action='store_true')
    parser.add_argument('--smoke-test', action='store_true')
    parser.add_argument('--toggle', action='store_true')
    parser.add_argument('--dismiss', action='store_true')
    args = parser.parse_args()
    app = Gtk.Application(application_id='io.shadowsdesktop.app.v1', flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
    def command(application, command_line):
        argv = command_line.get_arguments()[1:]
        incoming = parser.parse_args(argv)
        window = application.get_active_window()
        if incoming.dismiss: application.quit(); return 0
        if window and incoming.toggle: application.quit(); return 0
        if not window:
            provider = Gtk.CssProvider(); provider.load_from_data(CSS)
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            window = Window(application, incoming)
        elif incoming.session:
            window.selection.pinned = incoming.session; window.save(); window.poll()
        window.present()
        if incoming.smoke_test: GLib.timeout_add(1200, lambda: (application.quit(), False)[1])
        return 0
    app.connect('command-line', command)
    return app.run(sys.argv)


if __name__ == '__main__': sys.exit(main())
