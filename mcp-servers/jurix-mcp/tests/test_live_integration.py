import os

import pytest

from jurixmcp.config import get_settings
from jurixmcp.jurix_http import JurixHttpClient


pytestmark = pytest.mark.live


@pytest.mark.skipif(os.getenv("JURIX_ENABLE_LIVE") != "1", reason="Set JURIX_ENABLE_LIVE=1 to run live integration tests")
def test_live_bootstrap_csrf():
    settings = get_settings()
    client = JurixHttpClient(settings.jurix_base_url, settings.default_user_agent)
    session = client.new_session()
    token = client.bootstrap_csrf(session)
    assert isinstance(token, str)
    assert len(token) >= 8
