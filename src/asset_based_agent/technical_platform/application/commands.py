"""Command 对象：UI 意图的唯一入口（View 不直接触达 repo/kernel）。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class SubmitMessage:
    session_id: str
    text: str
    background: bool = False


@dataclass(frozen=True)
class StopOperation:
    operation_id: str


@dataclass(frozen=True)
class SwitchSession:
    session_id: str


@dataclass(frozen=True)
class OpenSession:
    session_id: str


@dataclass(frozen=True)
class SaveDraft:
    session_id: str
    text: str


@dataclass(frozen=True)
class SetPermissionMode:
    session_id: str
    mode: str


@dataclass(frozen=True)
class CreateSession:
    session_id: str
    project_id: str
    owner_id: str
    title: str
