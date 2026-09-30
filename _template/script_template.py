#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# resolve-menu: Utility
"""
DaVinci Resolve script template
================================
Copy the _template folder, rename it (e.g. my-script/) and rename this file
(e.g. my_script.py): that name is what you see under Workspace > Scripts.
As-is it only prints info about the open project, so you can check that
Resolve can run your scripts.

Menu: the "# resolve-menu:" line above is where tools/install.py copies it
(Utility, Edit, Color, Deliver, or Comp).

Keep the script in a single file: Resolve copies and runs it alone, without
the rest of this repository.
"""
import sys

# --------------------------------------------------------------------------- settings
CONFIG = {
    'show_dialog': True,   # options window (if this Resolve build supports it)
    'greeting': 'Hello',   # example option
}


# --------------------------------------------------------------------------- helpers
def log(*args):
    print('[my script]', *args)
    sys.stdout.flush()


class Abort(Exception):
    """Stop with a clear message for the user."""


def get_resolve():
    """The Resolve object, whether run from the Scripts menu, the Console or outside Resolve."""
    g = globals()
    if g.get('resolve'):
        return g['resolve']
    for name in ('app', 'fusion', 'fu'):
        obj = g.get(name)
        if obj is not None:
            try:
                r = obj.GetResolve()
                if r:
                    return r
            except Exception:
                pass
    b = g.get('bmd')
    if b is not None:
        try:
            r = b.scriptapp('Resolve')
            if r:
                return r
        except Exception:
            pass
    try:
        import DaVinciResolveScript as dvr
        return dvr.scriptapp('Resolve')
    except ImportError:
        return None


def get_ui(resolve):
    """(ui, dispatcher) for windows, or (None, None) when this Resolve doesn't offer them."""
    g = globals()
    fu = g.get('fu') or g.get('fusion')
    if fu is None:
        try:
            fu = resolve.Fusion()
        except Exception:
            fu = None
    b = g.get('bmd')
    if fu is None or b is None or not hasattr(b, 'UIDispatcher'):
        return None, None
    try:
        ui = fu.UIManager
        return ui, b.UIDispatcher(ui)
    except Exception:
        return None, None


def show_message(ui, disp, title, text):
    if ui is None:
        return
    try:
        win = disp.AddWindow({'ID': 'Msg', 'WindowTitle': title, 'Geometry': [340, 260, 420, 180]}, [
            ui.VGroup([ui.Label({'Text': text, 'WordWrap': True}),
                       ui.Button({'ID': 'ok', 'Text': 'OK', 'Weight': 0})]),
        ])
        win.On.ok.Clicked = lambda ev: disp.ExitLoop()
        win.On.Msg.Close = lambda ev: disp.ExitLoop()
        win.Show()
        disp.RunLoop()
        win.Hide()
    except Exception:
        pass


def ask_options(ui, disp, cfg):
    """Options window. Returns the updated config, or None if cancelled."""
    win = disp.AddWindow({'ID': 'Options', 'WindowTitle': 'My script', 'Geometry': [300, 200, 360, 140]}, [
        ui.VGroup({'Spacing': 6}, [
            ui.HGroup({'Weight': 0}, [ui.Label({'Text': 'Greeting', 'Weight': 0.4}),
                                      ui.LineEdit({'ID': 'greeting', 'Text': cfg['greeting'], 'Weight': 0.6})]),
            ui.HGroup({'Weight': 0}, [ui.Button({'ID': 'cancel', 'Text': 'Cancel'}),
                                      ui.Button({'ID': 'ok', 'Text': 'OK'})]),
        ]),
    ])
    items = win.GetItems()
    result = {'ok': False}

    def done(ev, ok=False):
        result['ok'] = ok
        disp.ExitLoop()

    win.On.ok.Clicked = lambda ev: done(ev, True)
    win.On.cancel.Clicked = done
    win.On.Options.Close = done
    win.Show()
    disp.RunLoop()
    win.Hide()
    if not result['ok']:
        return None
    out = dict(cfg)
    out['greeting'] = str(items['greeting'].Text)
    return out


# --------------------------------------------------------------------------- what the script does
def run(resolve, cfg):
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        raise Abort('No project is open.')
    pool = project.GetMediaPool()
    folder = pool.GetCurrentFolder() or pool.GetRootFolder()
    timeline = project.GetCurrentTimeline()
    clips = folder.GetClipList() or []
    lines = [
        '%s from Resolve %s' % (cfg['greeting'], resolve.GetVersionString() if hasattr(resolve, 'GetVersionString') else ''),
        'Project: %s' % project.GetName(),
        'Current timeline: %s' % (timeline.GetName() if timeline else 'none'),
        'Open Media Pool bin: %s (%d clips)' % (folder.GetName(), len(clips)),
    ]
    for line in lines:
        log(line)
    return '\n'.join(lines)


def main():
    resolve = get_resolve()
    if resolve is None:
        log('Cannot find Resolve. Run this from Workspace > Scripts inside DaVinci Resolve.')
        return
    ui, disp = get_ui(resolve) if CONFIG.get('show_dialog') else (None, None)
    cfg = dict(CONFIG)
    try:
        if ui is not None:
            cfg = ask_options(ui, disp, cfg)
            if cfg is None:
                log('cancelled')
                return
        show_message(ui, disp, 'My script', run(resolve, cfg))
    except Abort as e:
        log('ERROR:', e)
        show_message(ui, disp, 'My script', str(e))


if __name__ == '__main__' or 'resolve' in globals() or 'app' in globals():
    main()
