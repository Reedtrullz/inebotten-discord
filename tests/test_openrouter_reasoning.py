"""Keep optional reasoning explicit without expanding the reply budget."""
import os
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ai.openrouter_connector import create_openrouter_connector
from ai.result_schema import AIResult
from core.config import Config
from core.request_context import RequestContext


@pytest.mark.asyncio
@pytest.mark.parametrize('enabled', [None, False, True])
async def test_factory_keeps_reasoning_selection_and_reply_budget(enabled):
    connector = create_openrouter_connector(SimpleNamespace(
        OPENROUTER_API_KEY='synthetic-key',
        OPENROUTER_MODEL='dots-studio/dots-3-note-preview:free',
        OPENROUTER_MAX_TOKENS=600,
        OPENROUTER_REASONING_ENABLED=enabled,
    ))
    captured = []

    async def request(endpoint, method='POST', payload=None):
        captured.append(payload)
        return AIResult('success', 'Hei. Hva kan jeg hjelpe deg med?',
                        'openrouter', connector.model)

    connector._make_request = request
    result = await connector.generate_reply(
        RequestContext('synthetic', 'user', 'channel', 'guild', 'no', 'guild'),
        'Hei', deadline=time.monotonic() + 1,
    )
    assert result.status == 'success'
    assert captured[0]['max_tokens'] == 600
    if enabled is None:
        assert 'reasoning' not in captured[0]
    else:
        assert captured[0]['reasoning'] == {'enabled': enabled}


@pytest.mark.parametrize('value, expected', [(None, None), ('false', False), ('true', True)])
def test_config_preserves_unset_or_explicit_reasoning(value, expected, tmp_path):
    env = {'HERMES_HOME': str(tmp_path), 'DISCORD_USER_TOKEN': 'synthetic-token'}
    if value is not None:
        env['OPENROUTER_REASONING_ENABLED'] = value
    with patch.dict(os.environ, env, clear=True):
        config = Config()
    assert config.OPENROUTER_REASONING_ENABLED is expected
