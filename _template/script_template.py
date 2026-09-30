#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# resolve-menu: Utility
"""
Plantilla de script para DaVinci Resolve
========================================
Copia la carpeta _template, cámbiale el nombre (p. ej. mi-script/) y renombra
este archivo (p. ej. mi_script.py): ese nombre es el que verás en
Workspace > Scripts. Tal cual, solo muestra información del proyecto abierto,
así que sirve para comprobar que Resolve ejecuta tus scripts.

Menú: la línea "# resolve-menu:" de arriba decide dónde lo instala
tools/install.py (Utility, Edit, Color, Deliver o Comp).

Mantén el script en un solo archivo: Resolve lo copia y ejecuta suelto, sin el
resto del repo.
"""
import sys

# --------------------------------------------------------------------------- ajustes
CONFIG = {
    'show_dialog': True,   # ventana de opciones (si tu Resolve la admite)
    'greeting': 'Hola',    # ejemplo de opción
}


# --------------------------------------------------------------------------- utilidades
def log(*args):
    print('[mi script]', *args)
    sys.stdout.flush()


class Abort(Exception):
    """Para parar con un mensaje claro para el usuario."""


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
    """Ventana de opciones. Devuelve la configuración cambiada, o None si se cancela."""
    win = disp.AddWindow({'ID': 'Options', 'WindowTitle': 'Mi script', 'Geometry': [300, 200, 360, 140]}, [
        ui.VGroup({'Spacing': 6}, [
            ui.HGroup({'Weight': 0}, [ui.Label({'Text': 'Saludo', 'Weight': 0.4}),
                                      ui.LineEdit({'ID': 'greeting', 'Text': cfg['greeting'], 'Weight': 0.6})]),
            ui.HGroup({'Weight': 0}, [ui.Button({'ID': 'cancel', 'Text': 'Cancelar'}),
                                      ui.Button({'ID': 'ok', 'Text': 'Aceptar'})]),
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


# --------------------------------------------------------------------------- lo que hace el script
def run(resolve, cfg):
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        raise Abort('No hay ningún proyecto abierto.')
    pool = project.GetMediaPool()
    folder = pool.GetCurrentFolder() or pool.GetRootFolder()
    timeline = project.GetCurrentTimeline()
    clips = folder.GetClipList() or []
    lines = [
        '%s desde Resolve %s' % (cfg['greeting'], resolve.GetVersionString() if hasattr(resolve, 'GetVersionString') else ''),
        'Proyecto: %s' % project.GetName(),
        'Timeline actual: %s' % (timeline.GetName() if timeline else 'ninguno'),
        'Carpeta abierta del Media Pool: %s (%d clips)' % (folder.GetName(), len(clips)),
    ]
    for line in lines:
        log(line)
    return '\n'.join(lines)


def main():
    resolve = get_resolve()
    if resolve is None:
        log('No encuentro Resolve. Ejecuta el script desde Workspace > Scripts dentro de DaVinci Resolve.')
        return
    ui, disp = get_ui(resolve) if CONFIG.get('show_dialog') else (None, None)
    cfg = dict(CONFIG)
    try:
        if ui is not None:
            cfg = ask_options(ui, disp, cfg)
            if cfg is None:
                log('cancelado')
                return
        show_message(ui, disp, 'Mi script', run(resolve, cfg))
    except Abort as e:
        log('ERROR:', e)
        show_message(ui, disp, 'Mi script', str(e))


if __name__ == '__main__' or 'resolve' in globals() or 'app' in globals():
    main()
