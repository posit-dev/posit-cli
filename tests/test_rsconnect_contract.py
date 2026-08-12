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

    # `posit connect api --include` neutralizes this 2xx-JSON unwrapping (by
    # assigning an identity to the instance) to recover the raw HTTPResponse and
    # its status/headers. If rsconnect renames it, --include silently loses
    # headers -- fail loudly here instead.
    assert hasattr(RSConnectClient, "_tweak_response"), (
        "RSConnectClient lost _tweak_response; `api --include` relies on bypassing it"
    )

    # Used for clean error wrapping.
    assert issubclass(RSConnectException, Exception)


def test_http_response_surface():
    from rsconnect.http_support import HTTPResponse

    params = inspect.signature(HTTPResponse.__init__).parameters
    assert {"full_uri", "response", "body", "exception"} <= set(params)


def test_publisher_service_surface():
    from rsconnect.publisher import (
        CONTENT_TYPES,
        InitRequest,
        PublishRequest,
        initialize_project,
        publish_project,
    )

    assert CONTENT_TYPES
    assert {"project_dir", "content_type", "entrypoint"} <= set(
        inspect.signature(InitRequest).parameters
    )
    assert {
        "project_dir",
        "config_name",
        "deployment_name",
        "server",
        "server_name",
        "api_key",
        "insecure",
        "cacert",
        "verify",
        "metadata",
    } <= set(inspect.signature(PublishRequest).parameters)
    assert callable(initialize_project)
    assert callable(publish_project)
