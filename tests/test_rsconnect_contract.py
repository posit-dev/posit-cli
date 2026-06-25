"""Guard tests for the rsconnect-python *internal* API we depend on.

rsconnect's `RSConnectExecutor`/`RSConnectClient` are not a stable public API.
If a version bump changes these, fail here with a clear message rather than at
runtime in `posit connect api`.
"""

import inspect


def test_executor_surface():
    from rsconnect.api import RSConnectClient, RSConnectException, RSConnectExecutor

    assert hasattr(RSConnectExecutor, "setup_client")
    params = inspect.signature(RSConnectExecutor.__init__).parameters
    for expected in ("name", "url", "api_key", "insecure", "cacert"):
        assert expected in params, f"RSConnectExecutor lost __init__ param {expected!r}"

    assert hasattr(RSConnectClient, "request")
    req_params = inspect.signature(RSConnectClient.request).parameters
    for expected in ("method", "path", "query_params", "body", "headers"):
        assert expected in req_params, f"RSConnectClient.request lost {expected!r}"

    # Used for clean error wrapping.
    assert issubclass(RSConnectException, Exception)


def test_http_response_surface():
    from rsconnect.http_support import HTTPResponse

    params = inspect.signature(HTTPResponse.__init__).parameters
    assert {"full_uri", "response", "body", "exception"} <= set(params)
