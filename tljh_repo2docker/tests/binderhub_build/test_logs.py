import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

import pytest
from jupyterhub.tests.utils import async_requests

from tljh_repo2docker.binderhub_log import BinderHubLogsHandler

from ..utils import add_environment, api_request, next_event, wait_for_image


@pytest.mark.asyncio
async def test_stream_simple(app, minimal_repo, image_name, generated_image_name):
    name, ref = image_name.split(":")
    build_response = await add_environment(
        app, repo=minimal_repo, name=name, ref=ref, provider="git"
    )
    uid = build_response.json().get("uid", None)
    assert uid is not None
    r = await api_request(app, "environments", uid, "logs", stream=True)
    r.raise_for_status()

    assert r.headers["content-type"] == "text/event-stream"
    ex = async_requests.executor
    line_iter = iter(r.iter_lines(decode_unicode=True))
    evt = await ex.submit(next_event, line_iter)
    evt = await ex.submit(next_event, line_iter)
    msg = evt.get("message", "")
    assert "Picked Git content provider." in msg

    r.close()
    # BinderHub tags the produced image with a content-hash name (see
    # generated_image_name fixture), not the user-supplied image_name —
    # waiting on the latter would always hit the timeout.
    await wait_for_image(image_name=generated_image_name)


@pytest.mark.asyncio
async def test_bad_uuid(app, image_name, request):
    r = await api_request(app, "environments", "bad-uuid", "logs", stream=True)
    request.addfinalizer(r.close)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_image_not_found(app, image_name, request):
    random_uid = "a025d82f-48a7-4d6b-ba31-e7056c3dbca6"
    r = await api_request(app, "environments", random_uid, "logs", stream=True)
    request.addfinalizer(r.close)
    assert r.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("status, phase", [("built", "built"), ("failed", "error")])
async def test_stream_terminal_event_contains_full_log(monkeypatch, status, phase):
    initial_log = "Starting build\n"
    final_log = initial_log + "Build finished\n"
    manager = SimpleNamespace(
        read=AsyncMock(
            side_effect=[
                SimpleNamespace(status="building", log=initial_log),
                SimpleNamespace(status=status, log=final_log),
            ]
        )
    )
    db_context = MagicMock()
    handler = SimpleNamespace(
        set_header=Mock(),
        get_db_handlers=lambda: (db_context, manager),
        _emit=AsyncMock(),
    )
    monkeypatch.setattr("tljh_repo2docker.binderhub_log.asyncio.sleep", AsyncMock())

    await inspect.unwrap(BinderHubLogsHandler.get)(handler, str(uuid4()))

    assert handler._emit.call_args.args[0] == {
        "phase": phase,
        "message": final_log,
    }
