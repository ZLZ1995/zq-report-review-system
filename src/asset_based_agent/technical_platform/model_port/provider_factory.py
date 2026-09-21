"""S14 生产 provider 接线：把业务 Skill 的模型链路接到现有服务端客户端。

- REVIEW → RemoteReviewLlm（report_review_app 既有远程审核实现）；
- DETAIL（自动资料识别）→ MaterialAnalysisProvider；
- 无已登录客户端或模型选择时直接拒绝（不得静默退化为无模型执行）。
"""
from __future__ import annotations

from ..skills import REVIEW


def production_provider_factory(client, model_id):
    if client is None:
        raise ValueError('生产接线需要已登录的服务端客户端')
    if not isinstance(model_id, str) or not model_id.strip():
        raise ValueError('生产接线需要已选择的模型')
    model_id = model_id.strip()

    def factory(skill_id, instructions):
        if skill_id == REVIEW.id:
            from ...report_review_app.services.remote_review_llm import (
                RemoteReviewLlm,
            )
            return RemoteReviewLlm(client, model_id=model_id,
                                   skill_instructions=str(instructions))
        from ..material_analysis import MaterialAnalysisProvider
        return MaterialAnalysisProvider(client, model_id, str(instructions))

    return factory


def wire_business_service(store, session_id, *, client, model_id):
    """构造接入生产模型链路的 BusinessRunService。"""
    from ..business_tools.service import BusinessRunService
    return BusinessRunService(
        store, session_id,
        provider_factory=production_provider_factory(client, model_id))
