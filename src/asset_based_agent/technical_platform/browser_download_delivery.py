"""Conversation download receipts; navigation opens directories, never files."""
import html
from uuid import UUID

from .browser_download_artifacts import DownloadArtifacts, _path, _stamp


def download_links(store, run_id):
    UUID(run_id)
    content = []
    for item in DownloadArtifacts(store).list(run_id):
        UUID(item['id'])
        content.append(
            f'<p>{html.escape(item["name"])} · {item["size"]:,} 字节<br>'
            '下载时完整性已校验；业务内容待核验。 '
            f'<a href="zq-download-folder:{run_id}/{item["id"]}">打开所在文件夹</a></p>'
        )
    return ''.join(content)


def download_folder(store, session_id, run_id, identity):
    """Quick metadata check only: never hash large files on the GUI thread.

    This returns a directory, not permission to execute/open a downloaded file.
    It does not claim that the saved content was business-verified or rehashed.
    """
    UUID(run_id)
    UUID(identity)
    if store.run(run_id)['session'] != session_id:
        raise PermissionError('Download belongs to another conversation')
    item = next((row for row in DownloadArtifacts(store).list(run_id)
                 if row['id'] == identity), None)
    if item is None:
        raise PermissionError('Download receipt missing')
    path = _path(item['path'])
    if _stamp(path.stat()) != item['file_identity']:
        raise ValueError('Download changed since verification')
    return path.parent
