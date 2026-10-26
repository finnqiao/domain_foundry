"""Unpriced paid search must fail before any network request."""
import httpx
import pytest

from domain_foundry_core.foundry.research import BraveSearchProvider, ResearchUnavailable


def test_brave_cannot_spend_even_with_key(monkeypatch):
    calls = []
    monkeypatch.setattr(httpx, 'get', lambda *a, **k: calls.append(a))
    provider = BraveSearchProvider(api_key='synthetic-key-not-real')
    with pytest.raises(ResearchUnavailable, match='disabled pending verified'):
        provider.search('synthetic research', count=10)
    assert calls == []
