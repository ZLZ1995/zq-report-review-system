"""ReviewLlm adapter backed exclusively by the server review-jobs API."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .agent_gateway import (
    AdviceRequest,
    AdviceResult,
    ConversationTurnRequest,
    ConversationTurnResult,
)
from .document_extraction_service import DocumentChunk
from .privacy_filter import ReviewBatch
from .remote_auth_service import (
    InsufficientBalance,
    NetworkUnavailable,
    RemoteAuthenticationError,
    RemoteSessionClient,
)
from .review_llm_client import ReviewNetworkError, ReviewResponseSchemaError
from .rule_registry import IssueCandidate


class RemoteReviewLlm:
    def __init__(
        self,
        client: RemoteSessionClient,
        *,
        model_id: str = "",
        round_number: int = 1,
        client_job_id: str | None = None,
        skill_instructions: str = "",
        user_request: str = "",
        poll_interval: float = 2.0,
        result_wait_seconds: float = 1800.0,
    ) -> None:
        self.client = client
        self.model_id = model_id
        self.round_number = round_number
        self.client_job_id = client_job_id
        self.skill_instructions = skill_instructions
        self.user_request = user_request
        self.poll_interval = poll_interval
        self.result_wait_seconds = result_wait_seconds
        self.cancel_event = None

    def set_model_id(self, model_id: str) -> None:
        if not model_id:
            raise ValueError("model_id is required")
        self.model_id = model_id

    def set_round_number(self, round_number: int) -> None:
        if round_number < 1:
            raise ValueError("round_number must be at least 1")
        self.round_number = round_number

    def set_client_job_id(self, client_job_id: str) -> None:
        if not client_job_id:
            raise ValueError("client_job_id is required")
        self.client_job_id = client_job_id

    def review_batches(
        self,
        batches: list[ReviewBatch],
        progress_callback: Callable[[dict[str, object]], None] | None = None,
    ) -> list[IssueCandidate]:
        if not self.model_id:
            raise ReviewResponseSchemaError("远程审核模型尚未选择。")
        try:
            from .task_cancellation import cancellable_call
            balance = cancellable_call(self.client.get_balance, self.cancel_event)
            try:
                available_balance = Decimal(str(balance["balance"]))
            except (InvalidOperation, KeyError, TypeError) as exc:
                raise ReviewResponseSchemaError("服务端余额格式无效。") from exc
            if not available_balance.is_finite():
                raise ReviewResponseSchemaError("服务端余额格式无效。")
            if available_balance <= 0:
                raise ReviewResponseSchemaError("余额不足，无法开始本轮审核。")
            payload = {
                "client_job_id": self.client_job_id or f"DESKTOP-{uuid.uuid4().hex}",
                "model_id": self.model_id,
                "round_number": self.round_number,
                "chunks": [
                    self._chunk_payload(chunk)
                    for batch in batches
                    for chunk in batch.chunks
                ],
            }
            if self.skill_instructions:
                payload["skill_instructions"] = self.skill_instructions
            if self.user_request:
                payload["user_request"] = self.user_request
            if progress_callback is not None:
                progress_callback(
                    {
                        "state": "requesting",
                        "batch_index": 1,
                        "batch_total": max(1, len(batches)),
                        "attempt": 1,
                        "attempt_total": 1,
                    }
                )
            def create_job():
                value = self.client.create_review_job(payload)
                if (self.cancel_event is not None and self.cancel_event.is_set()
                        and isinstance(value.get('job_id'), str)
                        and hasattr(self.client, 'cancel_review_job')):
                    self.client.cancel_review_job(value['job_id'])
                return value
            created = cancellable_call(create_job, self.cancel_event)
            job_id = created.get("job_id")
            if not isinstance(job_id, str) or not job_id:
                raise ReviewResponseSchemaError("服务端未返回审核任务编号。")
            result = self._execute_with_progress(
                job_id, len(batches), progress_callback
            )
            raw_issues = result.get("issues")
            if not isinstance(raw_issues, list):
                raise ReviewResponseSchemaError("服务端审核结果格式无效。")
            return [self._issue(item) for item in raw_issues]
        except ReviewResponseSchemaError:
            raise
        except InsufficientBalance as exc:
            raise ReviewResponseSchemaError(str(exc)) from exc
        except NetworkUnavailable as exc:
            raise ReviewNetworkError("审核服务网络连接中断。") from exc
        except RemoteAuthenticationError as exc:
            raise ReviewNetworkError("审核服务会话已失效，请重新登录。") from exc

    def generate_advice(self, request: AdviceRequest) -> AdviceResult:
        raise ReviewResponseSchemaError(
            "远程模式的寻求建议接口将在服务端对话模块中启用。"
        )

    def continue_conversation(
        self,
        request: ConversationTurnRequest,
    ) -> ConversationTurnResult:
        raise ReviewResponseSchemaError(
            "远程模式的多轮对话接口将在服务端对话模块中启用。"
        )

    def _execute_with_progress(
        self,
        job_id: str,
        batch_total: int,
        progress_callback: Callable[[dict[str, object]], None] | None,
    ) -> dict[str, object]:
        # Execution acknowledgement is short-lived; durable status and validated
        # batch output are read from the original job without resubmitting it.
        result_holder: list[dict[str, object]] = []
        error_holder: list[BaseException] = []

        def execute() -> None:
            try:
                cancellable = getattr(self.client, 'execute_review_job_cancellable', None)
                result_holder.append(cancellable(job_id, self.cancel_event) if callable(cancellable)
                                     else self.client.execute_review_job(job_id))
            except BaseException as exc:  # noqa: BLE001 - re-raised in caller thread
                error_holder.append(exc)

        import threading

        from .task_cancellation import TaskCancelled, cancellable_call
        if self.cancel_event is not None and self.cancel_event.is_set():
            if hasattr(self.client, 'cancel_review_job'):
                def cancel_before_start():
                    try:
                        self.client.cancel_review_job(job_id)
                    except Exception:  # noqa: BLE001, S110 - best effort; no confirmation claimed
                        pass
                threading.Thread(target=cancel_before_start, daemon=True).start()
            raise TaskCancelled('已停止，不再启动审核')

        worker = threading.Thread(target=execute, daemon=True)
        worker.start()
        deadline = time.monotonic() + self.result_wait_seconds
        result: dict[str, object] = {}
        last_state: dict[str, object] = {}
        delivered = 0

        def emit_output(state):
            nonlocal delivered
            raw = state.get("issues", [])
            if isinstance(raw, list) and len(raw) > delivered:
                validated = [
                    self._issue(item).model_dump(mode="json")
                    for item in raw[delivered:]
                ]
                if progress_callback is not None:
                    progress_callback(
                        {"state": "output", "issues": validated, "job_id": job_id}
                    )
                delivered = len(raw)

        while time.monotonic() < deadline:
            if self.cancel_event is not None and self.cancel_event.is_set():
                if hasattr(self.client, 'cancel_review_job'):
                    def request_stop():
                        try:
                            self.client.cancel_review_job(job_id)
                        except Exception:  # noqa: BLE001, S110 - best effort while disconnected
                            pass  # Offline cancellation cannot guarantee server acknowledgement.
                    threading.Thread(target=request_stop, daemon=True).start()
                raise TaskCancelled('已停止接收；服务端取消请求已发起，当前模型调用可能仍需结算')
            if result_holder:
                acknowledged = result_holder.pop(0)
                last_state = acknowledged
                emit_output(acknowledged)
                if acknowledged.get("status") in {
                    "succeeded", "failed", "cancelled", "expired"
                }:
                    result = acknowledged
                    break
            # A lost execute response does not mean the server stopped working.
            # Only GET the original job: never resubmit an ambiguous paid call.
            try:
                try:
                    state = cancellable_call(lambda: self.client.get_review_job(job_id), self.cancel_event)
                except TaskCancelled:
                    continue  # Top of loop sends the server cancellation request.
            except NetworkUnavailable:
                if progress_callback is not None:
                    progress_callback({"state": "reconnecting", "job_id": job_id})
                if self.cancel_event is not None:
                    self.cancel_event.wait(self.poll_interval)
                else:
                    time.sleep(self.poll_interval)
                continue
            last_state = state
            emit_output(state)
            if state.get("status") in {"succeeded", "failed", "cancelled", "expired"}:
                result = state
                break
            if error_holder and not isinstance(error_holder[0], NetworkUnavailable):
                raise error_holder[0]
            completed = _integer(state.get("completed_batches"), default=0)
            total = max(1, _integer(state.get("batch_count"), default=batch_total))
            if progress_callback is not None:
                progress_callback(
                    {
                        "state": "waiting",
                        "job_id": job_id,
                        "completed_batches": completed,
                        "elapsed_seconds": int(
                            self.result_wait_seconds - (deadline - time.monotonic())
                        ),
                        "batch_index": max(1, min(total, completed or 1)),
                        "batch_total": total,
                        "attempt": 1,
                        "attempt_total": 1,
                    }
                )
            if self.cancel_event is not None:
                self.cancel_event.wait(self.poll_interval)
            else:
                time.sleep(self.poll_interval)
        if not result:
            if last_state.get("heartbeat_status") == "stale":
                raise ReviewNetworkError(
                    f"服务端工作进程心跳超时（任务编号：{job_id}）。任务将由服务端恢复；请勿重复提交。"
                )
            if last_state:
                raise ReviewNetworkError(
                    f"服务端任务仍在执行（任务编号：{job_id}）。可稍后按原任务继续查询；请勿重复提交。"
                )
            raise ReviewNetworkError(
                f"服务端任务状态尚未确认（任务编号：{job_id}）。请勿重复发起审核，以免重复扣费。"
            )
        if result.get("status") != "succeeded":
            error_code = str(result.get("error_code") or "review_failed")
            raise ReviewResponseSchemaError(f"服务端审核未完成：{error_code}")
        if progress_callback is not None:
            progress_callback(
                {
                    "state": "completed",
                    "batch_index": batch_total,
                    "batch_total": batch_total,
                    "attempt": 1,
                    "attempt_total": 1,
                }
            )
        return result

    @staticmethod
    def _chunk_payload(chunk: DocumentChunk) -> dict[str, object]:
        suffix = Path(chunk.source_file_name).suffix.lower()
        file_type = {
            ".doc": "word",
            ".docx": "word",
            ".xls": "excel",
            ".xlsx": "excel",
            ".xlsm": "excel",
            ".pdf": "pdf",
        }.get(suffix)
        if file_type is None:
            raise ReviewResponseSchemaError("存在不支持的审核文件类型。")
        source_location = chunk.location
        sheet_name = source_location.table if file_type == "excel" else None
        location = {
            "chapter": source_location.chapter,
            "page": source_location.page,
            "paragraph": source_location.paragraph,
            "table": source_location.table,
            "cell": source_location.cell,
        }
        return {
            "chunk_id": chunk.chunk_id,
            "source_file_id": chunk.source_file_id,
            "source_file_name": Path(chunk.source_file_name).name,
            "file_type": file_type,
            "role": chunk.role.value,
            "text": chunk.text,
            "location": {
                **location,
                **({"sheet": sheet_name} if sheet_name else {}),
            },
            "reference_only": chunk.reference_only,
            "sheet_name": sheet_name,
            "sheet_state": "visible",
        }

    @staticmethod
    def _issue(value: object) -> IssueCandidate:
        if not isinstance(value, dict):
            raise ReviewResponseSchemaError("服务端审核问题格式无效。")
        try:
            normalized = dict(value)
            location = normalized.get("location")
            if isinstance(location, dict) and location.get("sheet"):
                location = dict(location)
                location.setdefault("table", location["sheet"])
                location.pop("sheet", None)
                normalized["location"] = location
            return IssueCandidate.model_validate(normalized)
        except Exception as exc:
            raise ReviewResponseSchemaError("服务端审核问题格式无效。") from exc


def _integer(value: object, *, default: int) -> int:
    if not isinstance(value, (int, float, str)):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
