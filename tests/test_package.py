import kusum


def test_package_declares_its_version() -> None:
    assert kusum.__version__ == "0.0.1"
