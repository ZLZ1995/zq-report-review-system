import pytest


def completed_run(store):
    session = store.create_session(store.create_project("one"))
    run = store.start_run(session, {"skill_id": "report.review"})
    store.transition(run, "running", "start")
    store.transition(run, "validating", "validate")
    store.transition(run, "succeeded", "done")
    return run


def test_ignore_is_not_promoted_and_false_positive_creates_candidate_only(tmp_path):
    from asset_based_agent.technical_platform.feedback_service import FeedbackService
    from asset_based_agent.technical_platform.skill_improvement import (
        SkillImprovementService,
    )
    from asset_based_agent.technical_platform.store import PlatformStore

    store = PlatformStore(tmp_path / "state.sqlite", "alice")
    run = completed_run(store)
    feedback = FeedbackService(store)
    ignored = feedback.record(
        run_id=run,
        kind="ignored_issue",
        summary="Not relevant now",
        evidence_refs=["issue-1"],
    )
    assert ignored.proposal_id is None
    candidate = feedback.record(
        run_id=run,
        kind="false_positive",
        summary="Synthetic false positive",
        evidence_refs=["issue-2"],
    )
    assert candidate.proposal_id
    proposal = SkillImprovementService(store).get(candidate.proposal_id)
    assert proposal.status == "candidate"
    assert proposal.feedback_kind == "false_positive"
    assert proposal.evidence_refs == ("issue-2",)
    assert not hasattr(SkillImprovementService(store), "publish")


def test_proposal_validation_requires_evidence_and_passing_tests(tmp_path):
    from asset_based_agent.technical_platform.feedback_service import FeedbackService
    from asset_based_agent.technical_platform.skill_improvement import (
        SkillImprovementService,
    )
    from asset_based_agent.technical_platform.store import PlatformStore

    store = PlatformStore(tmp_path / "state.sqlite", "alice")
    run = completed_run(store)
    feedback = FeedbackService(store)
    with pytest.raises(ValueError, match="evidence"):
        feedback.record(
            run_id=run,
            kind="missed_issue",
            summary="Missing evidence",
            evidence_refs=[],
        )
    proposal_id = feedback.record(
        run_id=run,
        kind="missed_issue",
        summary="Synthetic miss",
        evidence_refs=["issue-3"],
    ).proposal_id
    service = SkillImprovementService(store)
    with pytest.raises(ValueError, match="tests"):
        service.validate(proposal_id, test_ids=[], tests_passed=True)
    with pytest.raises(ValueError, match="pass"):
        service.validate(proposal_id, test_ids=["test_synthetic"], tests_passed=False)
    validated = service.validate(
        proposal_id, test_ids=["test_synthetic"], tests_passed=True
    )
    assert validated.status == "validated"
    assert validated.test_ids == ("test_synthetic",)
    assert service.get(proposal_id).status == "validated"


def test_feedback_and_proposals_are_owner_scoped_and_do_not_change_skills(tmp_path):
    from asset_based_agent.technical_platform.feedback_service import FeedbackService
    from asset_based_agent.technical_platform.skill_improvement import (
        SkillImprovementService,
    )
    from asset_based_agent.technical_platform.skill_installation import (
        SkillInstallation,
    )
    from asset_based_agent.technical_platform.store import PlatformStore

    path = tmp_path / "state.sqlite"
    store = PlatformStore(path, "alice")
    run = completed_run(store)
    before = SkillInstallation(store).list_versions()
    proposal_id = (
        FeedbackService(store)
        .record(
            run_id=run,
            kind="preference",
            summary="Prefer concise explanations",
            evidence_refs=["message-1"],
        )
        .proposal_id
    )
    assert SkillInstallation(store).list_versions() == before
    with pytest.raises(PermissionError):
        SkillImprovementService(PlatformStore(path, "bob")).get(proposal_id)
