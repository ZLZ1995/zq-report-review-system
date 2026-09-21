"""Build the isolated browser probe using the client's sanitized Windows PATH."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    environment = os.environ.copy()
    environment['PATH'] = os.pathsep.join([
        str(Path(sys.executable).parent),
        str(Path(os.environ['WINDIR']) / 'System32'), os.environ['WINDIR'],
    ])
    return subprocess.run([
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
        '--name', 'zq_webengine_probe', '--distpath', 'build/browser_probe_clean/dist',
        '--workpath', 'build/browser_probe_clean/work', '--specpath', 'build/browser_probe_clean',
        'scripts/probe_platform_webengine.py',
    ], cwd=ROOT, env=environment, check=False).returncode


if __name__ == '__main__':
    raise SystemExit(main())
