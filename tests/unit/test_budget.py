import pytest

from flynn_agents_sdk import RunLimits


@pytest.mark.parametrize("value", [-1, True, 1.5, "2", 2**63])
def test_limits_require_nonnegative_sqlite_integers(value):
    with pytest.raises(ValueError):
        RunLimits(value, 1, 1)
    with pytest.raises(ValueError):
        RunLimits(1, value, 1)
    with pytest.raises(ValueError):
        RunLimits(1, 1, value)
    with pytest.raises(ValueError):
        RunLimits(1, 1, 1, output_tokens=value)


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_wall_time_requires_finite_positive_value(value):
    with pytest.raises(ValueError):
        RunLimits(1, 1, 1, value)
