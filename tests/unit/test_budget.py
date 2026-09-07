import pytest

from flynn_agents_sdk import Budget


@pytest.mark.parametrize("value", [-1, True, 1.5, "2"])
def test_limits_require_nonnegative_integers(value):
    with pytest.raises(ValueError, match="nonnegative integers"):
        Budget(inference_calls=value, tool_calls=1)
