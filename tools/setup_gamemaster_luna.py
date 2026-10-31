#!/usr/bin/env python3
"""Install the scoped bridge into the pinned, ignored Luna checkout."""
import argparse
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PIN = '6e2e3b27c015c61ab3591abb22a1968dd83c0567'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', type=Path, default=ROOT / 'tools/vendor/luna')
    parser.add_argument('--build', choices=('cli', 'gui', 'both'))
    args = parser.parse_args()
    checkout = args.checkout.resolve()
    head = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
    if head != PIN:
        parser.error(f'Expected Luna commit {PIN}; got {head}')
    patch = ROOT / 'tools/patches/luna-gamemaster.patch'
    git = ['git', '-C', str(checkout), 'apply']
    if subprocess.run([*git, '--check', str(patch)], capture_output=True).returncode == 0:
        subprocess.run([*git, str(patch)], check=True)
    elif subprocess.run([*git, '--reverse', '--check', str(patch)], capture_output=True).returncode != 0:
        parser.error('Luna source conflicts with the bridge patch; preserve local changes before retrying')
    shutil.copyfile(ROOT / 'tools/luna_gamemaster.rs', checkout / 'crates/luna-api/src/evermore_gamemaster.rs')
    if args.build:
        packages = ('luna-cli', 'luna-gui') if args.build == 'both' else ('luna-' + args.build,)
        subprocess.run(['cargo', '+stable', 'build', '--manifest-path', str(checkout / 'Cargo.toml'),
                        '--release', '--locked', *[arg for p in packages for arg in ('-p', p)]], check=True)
    print('Scoped gamemaster bridge installed.')


if __name__ == '__main__':
    main()
