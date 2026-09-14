"""Check packaged rules and the login window; close only this test process."""

import subprocess
import time
from pathlib import Path

import win32gui
import win32process

ROOT = Path(__file__).resolve().parents[1]


def main():
    folder = ROOT / "dist/technical_platform/ZQ技术平台"
    rules = folder / "_internal/asset_based_agent/technical_platform/review_rules.txt"
    assert (
        rules.read_bytes()
        == (
            ROOT / "src/asset_based_agent/technical_platform/review_rules.txt"
        ).read_bytes()
    )
    process = subprocess.Popen([str(folder / "ZQ技术平台.exe")], cwd=folder)
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            titles = []

            def visit(hwnd, _, titles=titles):
                if win32process.GetWindowThreadProcessId(hwnd)[1] == process.pid:
                    titles.append(win32gui.GetWindowText(hwnd))
                    if win32gui.GetWindowText(hwnd) == "Unhandled exception in script":
                        win32gui.EnumChildWindows(
                            hwnd,
                            lambda child, _: titles.append(
                                win32gui.GetWindowText(child)
                            ),
                            None,
                        )

            win32gui.EnumWindows(visit, None)
            if "Unhandled exception in script" in titles:
                raise RuntimeError(repr(titles))
            if any("登录" in title for title in titles):
                print("PASS: packaged rules match; executable opened login window")
                return
            if process.poll() is not None:
                raise RuntimeError(f"Executable exited: {process.returncode}")
            time.sleep(0.5)
        raise RuntimeError(
            f"Login window not observed within 60 seconds; windows: {titles!r}"
        )
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=10)


if __name__ == "__main__":
    main()
