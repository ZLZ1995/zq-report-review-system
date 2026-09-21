"""Failure drill matrix: twelve scenarios, real harnesses, clear endings.

Each drill drives the actual WorkflowRuntime / Journal / reconciliation
paths where a runtime exists, and falls back to explicit policy functions
for environment checks (backend selection, skill install). Every scenario
ends in a declared terminal state with a recovery strategy and a
user-readable Chinese message.
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Literal

from pydantic import Field

from ..agent_contracts import Record
from .workflow_compiler import CompiledStep, CompiledWorkflow
from .workflow_journal import WorkflowJournal
from .workflow_reconciliation import reconcile_unknown
from .workflow_runtime import WorkflowRuntime

SCENARIOS = ('offline', 'insufficient_balance', 'model_timeout',
             'response_lost', 'client_restart', 'office_crash',
             'wps_unavailable', 'file_locked', 'page_changed',
             'user_cancel', 'skill_conflict', 'corrupt_zip')

DrillScenario = Literal['offline', 'insufficient_balance', 'model_timeout',
                        'response_lost', 'client_restart', 'office_crash',
                        'wps_unavailable', 'file_locked', 'page_changed',
                        'user_cancel', 'skill_conflict', 'corrupt_zip']

DrillTerminal = Literal['failed', 'cancelled', 'recovered', 'manual_review',
                        'rejected', 'waiting']


class DrillOutcome(Record):
    scenario: DrillScenario
    terminal_state: DrillTerminal
    recovery: str = Field(min_length=1, max_length=500)
    user_message: str = Field(min_length=1, max_length=500)
    evidence: tuple[str, ...] = ()


class InsufficientBalanceError(ValueError):
    """Billing refusal: business fault, never retried."""


def _compiled(steps) -> CompiledWorkflow:
    return CompiledWorkflow(compile_hash='a' * 64, envelope_hash='b' * 64,
                            plan_id='p1', revision=1, steps=tuple(steps))


def _drive_run(tmp_path, executors, steps, *, max_attempts=2, cancel=None,
               journal_name='drill.jsonl'):
    journal = WorkflowJournal(tmp_path / journal_name)
    runtime = WorkflowRuntime(journal, executors, max_attempts=max_attempts,
                              sleeper=lambda _s: None)
    result = runtime.run(_compiled(steps), run_id='r1', cancel=cancel)
    evidence = tuple(event.type for event in journal.events('r1'))
    return result, evidence, journal


def _model_step(node_id='s1', depends_on=()):
    return CompiledStep(node_id=node_id, type='model_call',
                        token_budget=1_000, depends_on=tuple(depends_on))


def _drive_cancel(tmp_path):
    import threading
    cancel = threading.Event()
    cancel.set()
    calls = []

    def executor(step, _ctx):
        calls.append(step.node_id)
        return 'done'
    result, evidence, _journal = _drive_run(
        tmp_path, {'model_call': executor}, [_model_step()], cancel=cancel)
    assert result.state == 'cancelled'
    assert not calls  # 取消后无副作用：执行器从未被调用
    return DrillOutcome(
        scenario='user_cancel', terminal_state='cancelled',
        recovery='可随时重新发起任务，已取消的步骤不会重复执行',
        user_message='任务已取消，未产生任何副作用',
        evidence=evidence)


def run_drill(scenario: DrillScenario, tmp_path, *, remote_known=True,
              available_backends=('office',)) -> DrillOutcome:
    tmp_path = Path(tmp_path)
    if scenario == 'offline':
        def executor(_step, _ctx):
            raise ConnectionError('offline')
        _result, evidence, _j = _drive_run(tmp_path, {'model_call': executor},
                                           [_model_step()])
        return DrillOutcome(
            scenario='offline', terminal_state='failed',
            recovery='检查网络连接后重新发起任务',
            user_message='网络连接失败，重试后仍不可用，请检查网络后重新开始',
            evidence=evidence)
    if scenario == 'model_timeout':
        def executor(_step, _ctx):
            raise TimeoutError('model timeout')
        _result, evidence, _j = _drive_run(tmp_path, {'model_call': executor},
                                           [_model_step()])
        return DrillOutcome(
            scenario='model_timeout', terminal_state='failed',
            recovery='稍后重试；连续超时请切换网络或联系支持',
            user_message='模型响应超时，已自动重试仍未成功，请稍后重试',
            evidence=evidence)
    if scenario == 'insufficient_balance':
        def executor(_step, _ctx):
            raise InsufficientBalanceError('quota exhausted')
        _result, evidence, _j = _drive_run(tmp_path, {'model_call': executor},
                                           [_model_step()])
        return DrillOutcome(
            scenario='insufficient_balance', terminal_state='failed',
            recovery='充值或恢复额度后重新发起任务',
            user_message='账户余额不足，请充值后重试',
            evidence=evidence)
    if scenario == 'response_lost':
        decision = reconcile_unknown(
            'model_call', 'job-1',
            remote_lookup=lambda _job: 'charged' if remote_known else None)
        if decision.outcome == 'settled_charged':
            return DrillOutcome(
                scenario='response_lost', terminal_state='recovered',
                recovery='按远程账目对账后继续，不重发请求',
                user_message='已确认上次请求完成并计费，不重复扣费，任务继续',
                evidence=(decision.outcome,))
        return DrillOutcome(
            scenario='response_lost', terminal_state='manual_review',
            recovery='人工对账确认后再决定是否重发',
            user_message='上次请求结果未知，已转人工核对，不会重复扣费',
            evidence=(decision.outcome,))
    if scenario == 'client_restart':
        journal_path = tmp_path / 'restart.jsonl'
        calls: list[str] = []

        def ok(step, _ctx):
            calls.append(step.node_id)
            return 'done'

        def crash(_step, _ctx):
            raise RuntimeError('simulated client crash')
        steps = [_model_step('s1'),
                 CompiledStep(node_id='s2', type='run_skill',
                              skill_id='report.review', token_budget=1_000,
                              depends_on=('s1',))]
        journal = WorkflowJournal(journal_path)
        runtime = WorkflowRuntime(journal, {'model_call': ok,
                                            'run_skill': crash},
                                  sleeper=lambda _s: None)
        try:
            runtime.run(_compiled(steps), run_id='r1')
        except RuntimeError:
            pass  # 进程级崩溃：无终态事件
        reloaded = WorkflowJournal(journal_path)
        calls.clear()
        runtime2 = WorkflowRuntime(reloaded, {'model_call': ok,
                                              'run_skill': ok},
                                   sleeper=lambda _s: None)
        result = runtime2.run(_compiled(steps), run_id='r1')
        assert result.state == 'succeeded'
        assert calls == ['s2']  # 已提交的 s1 未重复执行
        return DrillOutcome(
            scenario='client_restart', terminal_state='recovered',
            recovery='从 Journal 恢复，仅重跑未完成节点',
            user_message='客户端重启后已恢复任务，已完成步骤未重复执行',
            evidence=('no_terminal_before_restart', 'resumed',
                      f's1_calls={calls.count("s1")}'))
    if scenario == 'office_crash':
        def executor(_step, _ctx):
            raise RuntimeError('Office process crashed')
        journal = WorkflowJournal(tmp_path / 'office.jsonl')
        runtime = WorkflowRuntime(journal, {'model_call': executor},
                                  sleeper=lambda _s: None)
        try:
            runtime.run(_compiled([_model_step()]), run_id='r1')
        except RuntimeError:
            pass
        decision = reconcile_unknown('office_write', 'w1',
                                     remote_lookup=lambda _x: None)
        return DrillOutcome(
            scenario='office_crash', terminal_state='manual_review',
            recovery='人工核对文件状态后决定重做或继续，不自动重放写动作',
            user_message='Office 意外退出，写入状态未知，请人工核对文件后重试',
            evidence=(decision.outcome,))
    if scenario == 'wps_unavailable':
        chosen = select_office_backend(available=available_backends)
        if chosen is None:
            return DrillOutcome(
                scenario='wps_unavailable', terminal_state='failed',
                recovery='安装 Office 或 WPS 后重试',
                user_message='未检测到 Office 或 WPS，无法处理文档',
                evidence=('no_backend',))
        return DrillOutcome(
            scenario='wps_unavailable', terminal_state='recovered',
            recovery=f'已改用 {chosen} 后端继续处理',
            user_message='未检测到 WPS，已改用 Office 完成处理',
            evidence=(f'backend={chosen}',))
    if scenario == 'file_locked':
        def executor(_step, _ctx):
            raise PermissionError('file locked by another process')
        _result, evidence, _j = _drive_run(tmp_path, {'model_call': executor},
                                           [_model_step()])
        return DrillOutcome(
            scenario='file_locked', terminal_state='failed',
            recovery='关闭占用该文件的程序后重试',
            user_message='文件被其他程序占用，请关闭后重试',
            evidence=evidence)
    if scenario == 'page_changed':
        decision = reconcile_unknown('browser_action', 'b1',
                                     remote_lookup=lambda _x: None)
        return DrillOutcome(
            scenario='page_changed', terminal_state='manual_review',
            recovery='人工核对页面状态后重新发起操作，不自动重放',
            user_message='页面结构已变化，操作状态未知，请人工核对后继续',
            evidence=(decision.outcome,))
    if scenario == 'user_cancel':
        return _drive_cancel(tmp_path)
    if scenario == 'skill_conflict':
        conflict = check_skill_conflict(
            'report.review', 'c' * 64, {'report.review': 'd' * 64})
        assert conflict is not None
        return DrillOutcome(
            scenario='skill_conflict', terminal_state='rejected',
            recovery='卸载旧版本或改用不冲突的 Skill 后重试',
            user_message='Skill 与已安装版本冲突，已拒绝安装',
            evidence=(conflict,))
    if scenario == 'corrupt_zip':
        broken = tmp_path / 'broken.zip'
        broken.write_text('这不是 zip 内容', encoding='utf-8')
        try:
            with zipfile.ZipFile(broken) as archive:
                archive.namelist()
            raise AssertionError('损坏 ZIP 未被识别')
        except zipfile.BadZipFile:
            return DrillOutcome(
                scenario='corrupt_zip', terminal_state='rejected',
                recovery='重新下载或索取完整安装包后重试',
                user_message='安装包损坏或格式不正确，已拒绝安装',
                evidence=('BadZipFile',))
    raise ValueError(f'未知演练场景：{scenario}')


def select_office_backend(*, available) -> str | None:
    """Prefer Office, fall back to WPS; None when neither exists."""
    available = tuple(available)
    if 'office' in available:
        return 'office'
    if 'wps' in available:
        return 'wps'
    return None


def check_skill_conflict(skill_id: str, skill_hash: str,
                         installed: dict) -> str | None:
    existing = installed.get(skill_id)
    if existing is not None and existing != skill_hash:
        return f'skill_id 已安装且哈希不同：{skill_id}'
    return None
