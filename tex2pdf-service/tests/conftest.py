"""Pytest configuration file."""


def pytest_addoption(parser):
    """Add command line options to pytest."""
    parser.addoption("--keep-docker-running", action="store_true", help="keep docker image running")
    parser.addoption("--no-docker-setup", action="store_true", help="do not run docker setup, expect a running docker")
    parser.addoption(
        "--docker-port-2023", action="store", default="33031", help="outside docker port to use for TL2023"
    )
    parser.addoption(
        "--docker-port-2025", action="store", default="33032", help="outside docker port to use for TL2025"
    )
