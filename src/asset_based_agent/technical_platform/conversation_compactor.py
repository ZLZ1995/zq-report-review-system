"""Conversation compaction: summaries are leads, never evidence.

A compacted summary is explicitly marked as non-original evidence. Any final
judgment must go back to the original message fragments via
`summary_source_ids`.
"""
from __future__ import annotations

from hashlib import sha256


def compact_messages(messages, *, keep_recent=4, summarizer=None):
    """Fold older messages into one marked summary, keeping the recent tail."""
    if type(keep_recent) is not int or keep_recent < 0:
        raise ValueError('保留轮数必须是非负整数')
    messages = list(messages)
    ids = [item['id'] for item in messages]
    if len(set(ids)) != len(ids):
        raise ValueError('消息标识重复，无法安全压缩')
    if len(messages) <= keep_recent:
        return [{'kind': 'message', **item} for item in messages]
    head, tail = messages[:-keep_recent], messages[-keep_recent:]
    source_ids = [item['id'] for item in head]
    if summarizer is not None:
        text = summarizer([dict(item) for item in head])
    else:
        text = (f'前 {len(head)} 轮对话摘要（非原始证据，最终判断须回查原文）：'
                + '；'.join(f"{item['id']}:{item['text'][:40]}" for item in head))
    summary = {
        'kind': 'summary',
        'id': 'sum-' + sha256('\0'.join(source_ids).encode('utf-8')).hexdigest()[:16],
        'text': text,
        'source_message_ids': source_ids,
        'non_original_evidence': True,
    }
    return [summary] + [{'kind': 'message', **item} for item in tail]


def summary_source_ids(summary) -> list:
    if summary.get('kind') != 'summary' or not summary.get('non_original_evidence'):
        raise ValueError('不是有效的摘要记录')
    return list(summary['source_message_ids'])
