"""Read-only COM startup probe; never open files or quit an existing process."""
import json
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def probe(progid):
    import pythoncom
    import pywintypes
    import win32com.client
    import win32process

    before = set(win32process.EnumProcesses())
    app = None
    owned = False
    result = {'progid': progid, 'status': 'unverified', 'opened_documents': False}
    pythoncom.CoInitialize()
    try:
        app = win32com.client.DispatchEx(progid)
        _, pid = win32process.GetWindowThreadProcessId(int(app.Hwnd))
        owned = pid not in before
        count = int(app.Workbooks.Count)
        result.update(new_process=owned, open_workbooks=count)
        result['status'] = 'startup_verified' if owned and count == 0 else 'existing_instance_not_modified'
    except (pywintypes.com_error, pywintypes.error, AttributeError, TypeError, ValueError, OSError) as exc:
        result['error_type'] = type(exc).__name__
    finally:
        if app is not None and owned:
            try:
                if int(app.Workbooks.Count) == 0:
                    app.Quit()
                    result['closed_owned_empty_instance'] = True
                else:
                    result['closed_owned_empty_instance'] = False
            except (pywintypes.com_error, pywintypes.error, AttributeError, TypeError, ValueError, OSError) as exc:
                result['cleanup_error_type'] = type(exc).__name__
        app = None
        pythoncom.CoUninitialize()
    return result


def main():
    import os
    if ROOT.drive.casefold() == os.environ.get('SystemDrive', 'C:').casefold():
        raise ValueError('Probe evidence requires a non-system drive')
    folder = ROOT / 'outputs/nl_acceptance' / f'office-startup-{uuid4().hex}'
    folder.mkdir(parents=True, exist_ok=False)
    results = []
    for progid in ('Excel.Application', 'ket.Application'):
        print('Probing ' + progid, flush=True)
        results.append(probe(progid))
        (folder / 'result.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        print(json.dumps(results[-1]), flush=True)
    print(str(folder), flush=True)
    return 0 if all(item['status'] == 'startup_verified' for item in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
