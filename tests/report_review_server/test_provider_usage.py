from types import SimpleNamespace

import httpx
import pytest

from asset_based_agent.report_review_server.services.provider_gateway import (
    HttpProviderClient,
    NormalizedUsage,
    ProviderCallError,
    normalize_openai_usage,
)


@pytest.mark.parametrize('value', [True, -1, 1.5, '2', 'bad', None, float('inf')])
def test_invalid_token_counts_are_not_silently_zeroed(value):
    with pytest.raises(ValueError):
        normalize_openai_usage({'prompt_tokens': value, 'completion_tokens': 2})


@pytest.mark.parametrize('usage', [
    {}, {'prompt_tokens': 1},
    {'prompt_tokens': 2, 'completion_tokens': 1, 'prompt_cache_hit_tokens': 3},
    {'prompt_tokens': 2, 'completion_tokens': 1, 'reasoning_tokens': 2},
    {'prompt_tokens': 2, 'completion_tokens': 1, 'total_tokens': 9},
    {'prompt_tokens': 2, 'completion_tokens': 1, 'completion_tokens_details': []},
    {'prompt_tokens': 2, 'completion_tokens': 1, 'reasoning_tokens': 1,
     'completion_tokens_details': {'reasoning_tokens': 0}},
])
def test_incomplete_or_inconsistent_usage_rejected(usage):
    with pytest.raises(ValueError):
        normalize_openai_usage(usage)


@pytest.mark.parametrize('value', [True, 1.5, float('nan')])
def test_normalized_usage_requires_nonnegative_integer(value):
    with pytest.raises(ValueError):
        NormalizedUsage(input_tokens=value)


@pytest.mark.parametrize('body,code', [({'usage': {}}, 'provider_usage_invalid'),
                                      ({}, 'provider_usage_missing')])
def test_bad_usage_is_nonretryable_provider_error(monkeypatch, body, code):
    monkeypatch.setattr(httpx, 'post', lambda *a, **k: httpx.Response(200, json=body))
    cipher = SimpleNamespace(decrypt=lambda *a, **k: 'synthetic-key')
    route = SimpleNamespace(provider_model='model', api_key_ciphertext='cipher', model_id='m',
                            priority=1, base_url='https://example.invalid',
                            provider_type='deepseek', timeout_seconds=1)
    with pytest.raises(ProviderCallError) as caught:
        HttpProviderClient(cipher).call(route, {'messages': []})
    assert caught.value.code == code
    assert not caught.value.retryable and caught.value.usage is None


def test_valid_zero_and_partitioned_usage_are_preserved():
    assert normalize_openai_usage({'prompt_tokens': 0, 'completion_tokens': 0}) == NormalizedUsage()
    assert normalize_openai_usage({'prompt_tokens': 10, 'completion_tokens': 4,
        'prompt_cache_hit_tokens': 3, 'prompt_cache_miss_tokens': 5,
        'completion_tokens_details': {'reasoning_tokens': 2}, 'total_tokens': 14}) == (
            NormalizedUsage(input_tokens=2, cache_hit_tokens=3, cache_miss_tokens=5,
                            output_tokens=2, reasoning_tokens=2))
