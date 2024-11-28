def pytest_addoption(parser):
    parser.addoption("--keep-docker-running", action="store_true", help="keep docker image running")
    parser.addoption("--no-docker-setup", action="store_true", help="do not run docker setup, expect a running docker")
    parser.addoption("--docker-port", action="store", default="33031", help="outside docker port to use")
