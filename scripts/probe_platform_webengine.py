"""G00 isolated WebEngine/DPAPI probe, with synthetic content and no login."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifact-dir', required=True, type=Path)
    args = parser.parse_args()
    root = args.artifact_dir.resolve()
    if root.drive.casefold() == os.environ.get('SystemDrive', 'C:').casefold():
        parser.error('Probe data must be on a non-system drive')
    if root.exists():
        parser.error('Use a fresh artifact directory to preserve prior evidence')
    root.mkdir(parents=True)
    if os.environ.get('QTWEBENGINE_DISABLE_SANDBOX') or 'no-sandbox' in os.environ.get('QTWEBENGINE_CHROMIUM_FLAGS', ''):
        parser.error('Refusing an environment with disabled browser sandbox')

    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
    from PySide6.QtWidgets import QApplication

    app = QApplication([])
    profile = QWebEngineProfile('zq-synthetic-probe', app)
    profile.setPersistentStoragePath(str(root / 'profile'))
    profile.setCachePath(str(root / 'cache'))
    page = QWebEnginePage(profile)
    result = {'passed': False, 'loaded': False, 'reason': 'timeout',
              'storage': profile.persistentStoragePath(), 'cache': profile.cachePath()}

    def completed(text):
        result.update(passed=text.strip() == 'ZQ browser probe', reason='content_verified')
        app.quit()

    def loaded(ok):
        result['loaded'] = ok
        if ok:
            page.toPlainText(completed)
        else:
            result['reason'] = 'load_failed'
            app.quit()

    page.loadFinished.connect(loaded)
    QTimer.singleShot(20000, app.quit)
    page.setHtml('<!doctype html><html><body>ZQ browser probe</body></html>', QUrl('https://example.invalid/'))
    app.exec()
    # Destroy the page before its profile, including renderer subprocess resources.
    import shiboken6
    shiboken6.delete(page)
    shiboken6.delete(profile)
    (root / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
