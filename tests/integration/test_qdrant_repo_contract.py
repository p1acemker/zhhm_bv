import os

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="Set RUN_INTEGRATION_TESTS=1 to run live Qdrant contract tests.",
)


def test_integration_gate_is_enabled_explicitly() -> None:
    assert os.getenv("RUN_INTEGRATION_TESTS") == "1"
