import httpx
import pytest

from asset_based_agent.technical_platform.release_info import (
    inspect_server,
    local_release,
)


def test_local_release_contains_actual_rule_hash():
    info = local_release()
    assert info["client_version"]
    assert len(info["review_rules_sha256"]) == 64
    assert info["review_skill_version"]


@pytest.mark.parametrize("supported", [True, False])
def test_protocol_check_does_not_invent_server_build_version(supported):
    def handle(request):
        assert str(request.url) == "https://server.test/openapi.json"
        return httpx.Response(200, json={
            "info": {"version": "0.1.0"},
            "components": {"schemas": {"ReviewJobCreateRequest": {"properties": {
                **({"user_request": {"type": "string"}} if supported else {})
            }}}},
        })
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        info = inspect_server("https://server.test/api/v1", client=client)
    assert info["user_request_supported"] is supported
    assert info["server_api_version"] == "0.1.0"
    assert info["server_build"] == "未提供"
