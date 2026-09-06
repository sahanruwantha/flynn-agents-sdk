"""Check the installed distribution's public package identity."""

from importlib.metadata import metadata

import flynn_agents


def test_package_matches_distribution_metadata() -> None:
    distribution = metadata("flynn-agents-sdk")
    assert distribution["Name"] == "flynn-agents-sdk"
    assert flynn_agents.__version__ == distribution["Version"]
