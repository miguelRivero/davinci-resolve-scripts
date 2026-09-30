#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copy scripts from this Git repository into DaVinci Resolve's scripts folder.

  python tools/install.py              install (or update) every script
  python tools/install.py --list       show what would be installed and where
  python tools/install.py --uninstall  remove this repository's scripts from Resolve
  python tools/install.py --dest DIR   use another scripts folder

Each script goes to the menu named in its header by a line
"# resolve-menu: Utility" (Utility, Edit, Color, Deliver, or Comp). Without it
it goes to Utility, which appears on every page. Run this again after you
change or update a script; restart Resolve if it does not show in the menu.
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
    print('  warning: unknown menu "%s" in %s, using Utility' % (m.group(1), path.name))
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
    ap.add_argument('--dest', help='Resolve Scripts folder (default: the user folder)')
    ap.add_argument('--list', action='store_true', help='only print what would be done')
    ap.add_argument('--uninstall', action='store_true', help='remove this repository\'s scripts from Resolve')
    args = ap.parse_args()

    root = Path(args.dest).expanduser() if args.dest else scripts_root()
    scripts = list(find_scripts())
    if not scripts:
        print('No scripts in', REPO)
        return 1
    print('Resolve scripts folder:', root)
    names = {}
    for src, menu in scripts:
        if src.name in names:
            print('ERROR: two scripts are named %s (%s and %s); rename one.'
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
                print('  removed   ', dst)
            else:
                print('  missing   ', dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            existed = dst.exists()
            shutil.copy2(str(src), str(dst))
            print('  %s %s -> %s' % ('updated   ' if existed else 'installed ', rel, menu))
    if not args.list and not args.uninstall:
        print('Done. In Resolve: Workspace > Scripts (restart Resolve if they do not appear).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
