import pytest


def identity():
    return {'owner': 'alice', 'project_id': 'p', 'session_id': 's', 'task_id': 't', 'request_id': 'r'}


def test_task_identity_is_versioned_and_rejects_unknown_fields():
    from asset_based_agent.technical_platform.execution_contracts import TaskIdentity
    assert TaskIdentity(**identity()).model_dump()['schema_version'] == 1
    with pytest.raises(ValueError):
        TaskIdentity(**identity(), password='never-allowed')
    with pytest.raises(ValueError):
        TaskIdentity(**identity(), schema_version=2)


@pytest.mark.parametrize('value', [True, '1', 0, -1])
def test_event_sequence_is_positive_strict_integer(value):
    from asset_based_agent.technical_platform.execution_contracts import TaskEvent
    with pytest.raises(ValueError):
        TaskEvent(identity=identity(), step_id='step', sequence=value, kind='progress', text='working')


def test_permission_requires_explicit_scope_and_cannot_modify_originals():
    from asset_based_agent.technical_platform.execution_contracts import PermissionGrant
    with pytest.raises(ValueError):
        PermissionGrant(identity=identity(), action='modify_originals', object_ids=['file'],
                        confirmation_id='message', task_revision=1)
    with pytest.raises(ValueError):
        PermissionGrant(identity=identity(), action='create_copy', object_ids=[],
                        confirmation_id='message', task_revision=1)


def test_tool_call_requires_step_and_rejects_unbounded_arguments():
    from asset_based_agent.technical_platform.execution_contracts import ToolCall
    with pytest.raises(ValueError):
        ToolCall(identity=identity(), step_id='', tool='browser.open', arguments={})
    with pytest.raises(ValueError):
        ToolCall(identity=identity(), step_id='step', tool='browser.open', arguments={'text': 'a' * 33000})


def test_artifact_hash_and_owner_identity_are_required():
    from asset_based_agent.technical_platform.execution_contracts import Artifact
    with pytest.raises(ValueError):
        Artifact(identity=identity(), artifact_id='a', step_id='step', file_name='result.docx',
                 sha256='invalid', size_bytes=10)


def test_plan_rejects_duplicate_dependencies_and_self_dependency():
    from asset_based_agent.technical_platform.execution_contracts import PlanStep
    for dependencies in (['a', 'a'], ['step']):
        with pytest.raises(ValueError):
            PlanStep(identity=identity(), step_id='step', tool='read', dependencies=dependencies)


def test_public_error_has_no_free_text_or_secret_field():
    from asset_based_agent.technical_platform.execution_contracts import PublicError
    value = PublicError(identity=identity(), step_id='step', code='network_unavailable')
    assert value.message
    with pytest.raises(ValueError):
        PublicError(identity=identity(), step_id='step', code='network_unavailable', raw_error='secret')


def test_valid_records_roundtrip_without_losing_identity():
    from asset_based_agent.technical_platform.execution_contracts import (
        Artifact,
        PermissionGrant,
        PlanStep,
        TaskEvent,
        ToolCall,
    )
    records = [
        PlanStep(identity=identity(), step_id='s1', tool='read'),
        ToolCall(identity=identity(), step_id='s1', tool='read', arguments={'file_id': 'f'}),
        TaskEvent(identity=identity(), step_id='s1', sequence=1, kind='progress'),
        Artifact(identity=identity(), step_id='s1', artifact_id='a', file_name='synthetic.docx',
                 sha256='a' * 64, size_bytes=10),
        PermissionGrant(identity=identity(), action='create_copy', object_ids=['f'],
                        confirmation_id='user-message', task_revision=1),
    ]
    for record in records:
        restored = type(record).model_validate_json(record.model_dump_json())
        assert restored == record
        assert restored.identity.request_id == 'r'
