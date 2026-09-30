#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copia los scripts de este repo a la carpeta de scripts de DaVinci Resolve.

  python tools/install.py              instala (o actualiza) todos los scripts
  python tools/install.py --list       muestra qué se instalaría y dónde
  python tools/install.py --uninstall  quita los scripts de este repo de Resolve
  python tools/install.py --dest DIR   usa otra carpeta de scripts

Cada script va al menú que indique su cabecera con una línea
"# resolve-menu: Utility" (Utility, Edit, Color, Deliver o Comp). Sin ella va a
Utility, que aparece en todas las páginas. Vuelve a ejecutarlo después de
cambiar o actualizar un script; reinicia Resolve si no aparece en el menú.
"""
import argparse
import os
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MENUS = ('Utility', 'Edit', 'Color', 'Deliver', 'Comp')
SKIP_DIRS = ('tools',)


def scripts_root():
    if sys.platform.startswith('win'):
        base = os.environ.get('APPDATA') or str(Path.home() / 'AppData' / 'Roaming')
        return Path(base) / 'Blackmagic Design' / 'DaVinci Resolve' / 'Support' / 'Fusion' / 'Scripts'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'Blackmagic Design' / 'DaVinci Resolve' / 'Fusion' / 'Scripts'
    return Path.home() / '.local' / 'share' / 'DaVinciResolve' / 'Fusion' / 'Scripts'


def menu_of(path):
    head = path.read_text(encoding='utf-8', errors='replace')[:3000]
    m = re.search(r'resolve-menu:\s*(\w+)', head, re.IGNORECASE)
    if not m:
        return 'Utility'
    wanted = m.group(1).lower()
    for menu in MENUS:
        if menu.lower() == wanted:
            return menu
    print('  aviso: menú "%s" desconocido en %s, uso Utility' % (m.group(1), path.name))
    return 'Utility'


def find_scripts():
    """Scripts live one folder per script; folders starting with _ or . are skipped (e.g. _template)."""
    for folder in sorted(p for p in REPO.iterdir() if p.is_dir()):
        if folder.name.startswith(('.', '_')) or folder.name in SKIP_DIRS:
            continue
        for f in sorted(list(folder.glob('*.py')) + list(folder.glob('*.lua'))):
            if not f.name.startswith(('_', 'test')):
                yield f, menu_of(f)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dest', help='carpeta Scripts de Resolve (por defecto la del usuario)')
    ap.add_argument('--list', action='store_true', help='solo mostrar lo que se haría')
    ap.add_argument('--uninstall', action='store_true', help='quitar los scripts de este repo')
    args = ap.parse_args()

    root = Path(args.dest).expanduser() if args.dest else scripts_root()
    scripts = list(find_scripts())
    if not scripts:
        print('No hay scripts en', REPO)
        return 1
    print('Carpeta de scripts de Resolve:', root)
    names = {}
    for src, menu in scripts:
        if src.name in names:
            print('ERROR: dos scripts se llaman %s (%s y %s); cambia uno de nombre.'
                  % (src.name, names[src.name].parent.name, src.parent.name))
            return 1
        names[src.name] = src

    for src, menu in scripts:
        dst = root / menu / src.name
        rel = '%s/%s' % (src.parent.name, src.name)
        if args.list:
            print('  %-40s -> %s' % (rel, dst))
        elif args.uninstall:
            if dst.exists():
                dst.unlink()
                print('  quitado   ', dst)
            else:
                print('  no estaba ', dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            existed = dst.exists()
            shutil.copy2(str(src), str(dst))
            print('  %s %s -> %s' % ('actualizado' if existed else 'instalado  ', rel, menu))
    if not args.list and not args.uninstall:
        print('Listo. En Resolve: Workspace > Scripts (reinicia Resolve si no aparecen).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
