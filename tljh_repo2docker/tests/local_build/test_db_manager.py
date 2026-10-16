from tljh_repo2docker.database.model import DockerImageSQL
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from tljh_repo2docker import docker as docker_module
import inspect
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from tornado.httputil import HTTPServerRequest
from tornado.web import Application
from tljh_repo2docker import launcher

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tljh_repo2docker.database.manager import ImagesDatabaseManager
from tljh_repo2docker.database.model import BaseSQL
from tljh_repo2docker.database.schemas import (
    BuildStatusType,
    DockerImageCreateSchema,
    DockerImageUpdateSchema,
    ImageMetadataType,
)


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(BaseSQL.metadata.create_all)
    maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    async with maker() as session:
        yield session
    await engine.dispose()


def _make_schema(uid=None, name="test-image:HEAD", status=BuildStatusType.BUILDING):
    return DockerImageCreateSchema(
        uid=uid or uuid4(),
        name=name,
        status=status,
        log="",
        image_meta=ImageMetadataType(
            display_name="test-image",
            repo="https://github.com/test/test",
            ref="HEAD",
            creation_date="01/01/2025",
            owner="admin",
            cpu_limit="",
            mem_limit="",
            node_selector={},
        ),
    )


async def test_create_and_read(db_session):
    manager = ImagesDatabaseManager()
    schema = _make_schema()
    created = await manager.create(db_session, schema)

    assert created.uid == schema.uid
    assert created.status == BuildStatusType.BUILDING.value
    assert created.name == "test-image:HEAD"

    fetched = await manager.read(db_session, schema.uid)
    assert fetched is not None
    assert fetched.uid == schema.uid


async def test_read_by_image_name(db_session):
    manager = ImagesDatabaseManager()
    schema = _make_schema(name="unique-image:abc")
    await manager.create(db_session, schema)

    result = await manager.read_by_image_name(db_session, "unique-image:abc")
    assert result is not None
    assert result.uid == schema.uid


async def test_read_by_image_name_not_found(db_session):
    manager = ImagesDatabaseManager()
    result = await manager.read_by_image_name(db_session, "no-such-image:xyz")
    assert result is None


async def test_read_all(db_session):
    manager = ImagesDatabaseManager()
    for i in range(3):
        await manager.create(db_session, _make_schema(name=f"img-{i}:HEAD"))

    all_images = await manager.read_all(db_session)
    assert len(all_images) == 3


async def test_update_status(db_session):
    manager = ImagesDatabaseManager()
    schema = _make_schema()
    await manager.create(db_session, schema)

    await manager.update(
        db_session,
        DockerImageUpdateSchema(uid=schema.uid, status=BuildStatusType.BUILT),
    )
    updated = await manager.read(db_session, schema.uid)
    assert updated is not None
    assert updated.status == BuildStatusType.BUILT.value


async def test_update_log(db_session):
    manager = ImagesDatabaseManager()
    schema = _make_schema()
    await manager.create(db_session, schema)

    await manager.update(
        db_session,
        DockerImageUpdateSchema(uid=schema.uid, log="some log content"),
    )
    updated = await manager.read(db_session, schema.uid)
    assert updated is not None
    assert updated.log == "some log content"


async def test_update_log_accumulation(db_session):
    manager = ImagesDatabaseManager()
    schema = _make_schema()
    await manager.create(db_session, schema)

    await manager.update(
        db_session,
        DockerImageUpdateSchema(uid=schema.uid, log="line1\nline2\n"),
    )
    await manager.update(
        db_session,
        DockerImageUpdateSchema(uid=schema.uid, log="line1\nline2\nline3\n"),
    )
    updated = await manager.read(db_session, schema.uid)
    assert updated is not None
    assert "line3" in updated.log


async def test_update_missing_returns_none(db_session):
    """Updating a deleted row must not resurrect it from a partial payload."""
    manager = ImagesDatabaseManager()
    missing_uid = uuid4()

    result = await manager.update(
        db_session,
        DockerImageUpdateSchema(uid=missing_uid, log="late log line"),
    )

    assert result is None
    # The row must not have been recreated with NULL name/status.
    assert await manager.read(db_session, missing_uid) is None


async def test_delete(db_session):
    manager = ImagesDatabaseManager()
    schema = _make_schema()
    await manager.create(db_session, schema)

    deleted = await manager.delete(db_session, schema.uid)
    assert deleted is True

    result = await manager.read(db_session, schema.uid)
    assert result is None


async def test_delete_nonexistent(db_session):
    manager = ImagesDatabaseManager()
    deleted = await manager.delete(db_session, uuid4())
    assert deleted is False


async def test_failed_image_has_log(db_session):
    manager = ImagesDatabaseManager()
    schema = _make_schema(status=BuildStatusType.FAILED)
    schema_with_log = DockerImageCreateSchema(
        **{**schema.model_dump(), "log": "Error: build failed"}
    )
    await manager.create(db_session, schema_with_log)

    fetched = await manager.read(db_session, schema.uid)
    assert fetched is not None
    assert fetched.status == BuildStatusType.FAILED.value
    assert "Error" in fetched.log


async def test_read_legacy_metadata(db_session):

    uid = uuid4()
    db_session.add(DockerImageSQL(
        uid=uid, name="legacy:HEAD", status="built", log="old log",
        image_meta={
            "display_name": "legacy", "repo": "https://example.org/repo",
            "ref": "HEAD", "cpu_limit": "", "mem_limit": "",
        },
    ))
    await db_session.commit()
    entry = await ImagesDatabaseManager().read(db_session, uid)
    assert entry.image_meta.creation_date == ""
    assert entry.image_meta.owner == ""
    assert entry.image_meta.node_selector == {}
    assert entry.log == "old log"


@pytest.mark.parametrize("reuse_existing", [True, False])
async def test_cached_build_status_and_explicit_rebuild(db_session, monkeypatch, reuse_existing):

    @asynccontextmanager
    async def db_context():
        yield db_session

    async def logs(**kwargs):
        yield "build completed\n"

    docker = MagicMock()
    docker.images.get = AsyncMock()
    docker.images.inspect = AsyncMock(return_value={"Config": {"Labels": {}}})
    container = MagicMock()
    container.commit = AsyncMock()
    container.delete = AsyncMock()
    container.wait = AsyncMock(return_value={"StatusCode": 0})
    container.log = logs
    docker.containers.create = AsyncMock(return_value=container)
    docker.containers.run = AsyncMock(return_value=container)
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=docker)
    client.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(docker_module, "Docker", lambda: client)
    manager = ImagesDatabaseManager()
    schema = _make_schema(name="rdm:fullref")
    await manager.create(db_session, schema)

    result = await docker_module.build_image(
        repo="https://example.org/repo", ref="fullref", owner="admin",
        default_image_name="rdm:fullref", optional_envs={"RDM_TOKEN": "secret"},
        optional_labels={"provider": "rdm"},
        uid=schema.uid, db_context=db_context, image_db_manager=manager,
        reuse_existing=reuse_existing,
    )
    assert result == "rdm:fullref"
    entry = await manager.read(db_session, schema.uid)
    assert entry.status == "built"
    if reuse_existing:
        docker.containers.run.assert_not_awaited()
        assert entry.log == "Reused cached image.\n"
        labels = container.commit.call_args.kwargs["config"]["Labels"]
        assert labels["tljh_repo2docker.opt.provider"] == "rdm"
    else:
        docker.images.get.assert_not_awaited()
        config = docker.containers.run.call_args.kwargs["config"]
        assert config["Env"] == ["RDM_TOKEN=secret"]
        assert config["Labels"]["tljh_repo2docker.opt.provider"] == "rdm"
        assert entry.log == "build completed\n"


async def test_launch_redirects_before_build_and_reuses_database_entry(db_session, tmp_path, monkeypatch):

    @asynccontextmanager
    async def db_context():
        yield db_session

    manager = ImagesDatabaseManager()
    app = Application(
        log=logging.getLogger(__name__), service_prefix="/services/tljh_repo2docker/",
        db_context=db_context, image_db_manager=manager,
    )
    request = HTTPServerRequest(method="GET", uri="/hub/build/git/repo/ref", connection=Mock())
    handler = launcher.LaunchHandler(
        app, request, repo_providers={}, token_store_path=str(tmp_path / "tokens.sqlite"),
    )
    handler.fetch_user = AsyncMock(return_value=SimpleNamespace(name="admin", admin=True))
    provider = Mock()
    provider.get_repo_url.return_value = "https://example.org/repo"
    provider.get_resolved_ref = AsyncMock(return_value="a" * 40)
    provider.get_build_slug.return_value = "repo"
    provider.get_optional_envs.return_value = {}
    handler._get_provider = Mock(return_value=provider)
    handler.redirect = Mock()
    builds = []

    async def build(**kwargs):
        handler.redirect.assert_called_with('/services/tljh_repo2docker/environments')
        entry = await manager.read(db_session, kwargs['uid'])
        assert entry.status == "building"
        assert entry.image_meta.owner == "admin"
        assert kwargs['owner'] == "admin"
        assert kwargs['ref'] == "a" * 40
        builds.append(kwargs['uid'])
        await manager.update(db_session, DockerImageUpdateSchema(uid=kwargs['uid'], status="built"))

    monkeypatch.setattr(launcher, 'build_image', build)
    get = inspect.unwrap(launcher.LaunchHandler.get)
    await get(handler, 'git')
    await get(handler, 'git')
    assert len(builds) == 2
    assert builds[0] == builds[1]
    assert len(await manager.read_all(db_session)) == 1
    handler.token_store.conn.close()
