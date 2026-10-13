import collections
import json
import logging
from datetime import datetime
from urllib.parse import quote, quote_plus, unquote, urlparse

from aiodocker import Docker, DockerError
from tornado import web

from .database.schemas import BuildStatusType, DockerImageUpdateSchema

LOG_HEAD_LINES = 10
LOG_TAIL_LINES = 300
MAX_LINE_CHARS = 4096
REDACTED = "[redacted]"


def _redact(line, secrets):
    """Replace each non-empty secret occurrence in ``line`` with [redacted]."""
    if isinstance(line, bytes):
        line = line.decode("utf-8", errors="replace")
    for secret in secrets:
        if secret:
            line = line.replace(secret, REDACTED)
    if len(line) > MAX_LINE_CHARS:
        line = line[:MAX_LINE_CHARS] + "...[line truncated]\n"
    return line


def split_url_credentials(url: str) -> tuple[str, str, str]:
    """Strip and return any user:password embedded in an http(s) URL.

    Returns ``(cleaned_url, username, password)``. ``username`` / ``password``
    are URL-decoded. For non-http(s) URLs or URLs without an embedded
    userinfo block, returns ``(url, "", "")`` unchanged.

    Used to avoid persisting credentials pasted into the repo URL field
    (DB, Docker labels, build logs).
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return url, "", ""
    if not (parsed.username or parsed.password):
        return url, "", ""
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    cleaned = parsed._replace(netloc=host).geturl()
    return (
        cleaned,
        unquote(parsed.username or ""),
        unquote(parsed.password or ""),
    )


def _embed_credentials(repo: str, username: str, password: str) -> str:
    """Return ``repo`` with HTTP basic-auth credentials embedded.

    Used because the upstream ``repo2docker`` image no longer honours the
    ``GIT_CREDENTIAL_ENV`` variable, so the only reliable way to clone a
    private HTTPS repo from inside the build container is to pass the
    token directly in the URL. Returns the URL unchanged for schemes
    other than http(s).
    """
    parsed = urlparse(repo)
    if parsed.scheme not in ("http", "https"):
        return repo
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    netloc = f"{quote(username, safe='')}:{quote(password, safe='')}@{host}"
    return parsed._replace(netloc=netloc).geturl()


def _build_log(head, tail, truncated):
    if not truncated:
        return "".join(list(head) + list(tail))
    return "".join(head) + "\n[...truncated...]\n" + "".join(tail)


def compute_image_name(repo, ref, name):
    """Return the Docker image name derived from repo/ref/name."""
    ref = ref or "HEAD"
    if len(ref) >= 40:
        ref = ref[:7]
    name = name or urlparse(repo).path.strip("/")
    name = name.lower().replace("/", "-")
    # Docker image names must start and end with an alphanumeric character. A
    # trailing slash in the repo URL becomes a trailing "-" here, which
    # repo2docker rejects ("is not a valid docker image name"), so strip any
    # leading/trailing separators.
    name = name.strip("-_.")
    return f"{name}:{ref}", ref, name

logger = logging.getLogger(__name__)


def get_optional_value(object, key):
    labels = object['Labels']
    abskey = f'tljh_repo2docker.opt.provider.{key}'
    if abskey not in labels:
        return None
    return labels[abskey]


def get_spawn_ref(object):
    labels = object['Labels']
    repo = labels["repo2docker.repo"]
    ref = labels["repo2docker.ref"]
    return quote_plus(f'{repo}#{ref}')


async def list_images():
    """
    Retrieve local images built by repo2docker
    """
    async with Docker() as docker:
        r2d_images = await docker.images.list(
            filters=json.dumps({"dangling": ["false"], "label": ["repo2docker.ref"]})
        )
    images = [
        {
            "provider": image["Labels"].get("tljh_repo2docker.opt.provider", None),
            "repo": get_optional_value(image, 'repo') or image["Labels"]["repo2docker.repo"],
            "ref": image["Labels"]["repo2docker.ref"],
            "spawnref": get_spawn_ref(image),
            "image_name": image["Labels"]["tljh_repo2docker.image_name"],
            "display_name": get_optional_value(image, 'display_name') or image["Labels"]["tljh_repo2docker.display_name"],
            "creation_date": image["Labels"].get(
                "tljh_repo2docker.creation_date", "unknow"
            ),
            "owner": image["Labels"].get("tljh_repo2docker.owner", "unknow"),
            "mem_limit": image["Labels"]["tljh_repo2docker.mem_limit"],
            "cpu_limit": image["Labels"]["tljh_repo2docker.cpu_limit"],
            "node_selector": image["Labels"].get("tljh_repo2docker.node_selector", ""),
            "status": "built",
        }
        for image in r2d_images
        if "tljh_repo2docker.image_name" in image["Labels"]
    ]
    return images


async def list_containers():
    """
    Retrieve the list of local images being built by repo2docker.
    Images are built in a Docker container.
    """
    async with Docker() as docker:
        r2d_containers = await docker.containers.list(
            filters=json.dumps({"label": ["repo2docker.ref"]})
        )
    containers = [
        {
            "provider": container["Labels"].get("tljh_repo2docker.opt.provider", None),
            "repo": get_optional_value(container, 'repo') or container["Labels"]["repo2docker.repo"],
            "ref": container["Labels"]["repo2docker.ref"],
            "spawnref": get_spawn_ref(container),
            "image_name": container["Labels"]["repo2docker.build"],
            "display_name": get_optional_value(container, 'display_name') or container["Labels"]["tljh_repo2docker.display_name"],
            "mem_limit": container["Labels"]["tljh_repo2docker.mem_limit"],
            "cpu_limit": container["Labels"]["tljh_repo2docker.cpu_limit"],
            "node_selector": container["Labels"].get(
                "tljh_repo2docker.node_selector", ""
            ),
            "status": "building",
        }
        for container in r2d_containers
        if "repo2docker.build" in container["Labels"]
    ]
    return containers


async def get_image_metadata(image_name):
    """
    Retrieve metadata of a specific locally built Docker image.
    """
    async with Docker() as docker:
        images = await docker.images.list(
            filters=json.dumps({"reference": [image_name]})
        )
        if not images:
            raise web.HTTPError(404, "Image not found")

        image = images[0]
        return {
            "repo": image["Labels"].get("repo2docker.repo", ""),
            "ref": image["Labels"].get("repo2docker.ref", ""),
            "display_name": image["Labels"].get("tljh_repo2docker.display_name", ""),
            "creation_date": image["Labels"].get("tljh_repo2docker.creation_date", ""),
            "owner": image["Labels"].get("tljh_repo2docker.owner", ""),
            "mem_limit": image["Labels"].get("tljh_repo2docker.mem_limit", ""),
            "cpu_limit": image["Labels"].get("tljh_repo2docker.cpu_limit", ""),
            "node_selector": image["Labels"].get("tljh_repo2docker.node_selector", ""),
        }


async def build_image(
    repo,
    ref,
    node_selector={},
    name="",
    owner="",
    memory=None,
    cpu=None,
    git_username=None,
    git_password=None,
    extra_buildargs=None,
    repo2docker_image=None,
    optional_envs=None,
    default_image_name=None,
    optional_labels=None,
    uid=None,
    db_context=None,
    image_db_manager=None,
    reuse_existing=True,
):
    """
    Build an image given a repo, ref and limits.
    When uid/db_context/image_db_manager are provided, logs are streamed to
    the database in real time and the final status (built/failed) is persisted.
    """
    image_name, ref, name = compute_image_name(repo, ref, name)
    if default_image_name is not None:
        image_name = name = default_image_name

    # memory is specified in GB
    memory = f"{memory}G" if memory else ""
    cpu = cpu or ""

    # creation_date
    creation_date = datetime.now().strftime("%d/%m/%Y")

    # repo2docker renders image labels as `LABEL key="value"`, so the value
    # cannot hold a double quote: a repr of strings, not JSON.
    repr_node_selector = {str(k): str(v) for k, v in (node_selector or {}).items()}

    # add extra labels to set additional image properties
    desired_image_labels = {
        "tljh_repo2docker.display_name": name,
        "tljh_repo2docker.image_name": image_name,
        "tljh_repo2docker.creation_date": creation_date,
        "tljh_repo2docker.owner": owner,
        "tljh_repo2docker.node_selector": str(repr_node_selector),
        "tljh_repo2docker.mem_limit": memory,
        "tljh_repo2docker.cpu_limit": cpu,
    }
    optional_label_map = {}
    if optional_labels is not None:
        optional_label_map = {f"tljh_repo2docker.opt.{k}": str(v) for k, v in optional_labels.items()}
        desired_image_labels.update(optional_label_map)

    labels = [f"{key}={value}" for key, value in desired_image_labels.items()]

    builder_labels = {
        "repo2docker.repo": repo,
        "repo2docker.ref": ref,
        "repo2docker.build": image_name,
    }
    builder_labels.update(desired_image_labels)
    builder_labels.update(optional_label_map)

    cmd = [
        "jupyter-repo2docker",
        "--ref",
        ref,
        "--user-name",
        "jovyan",
        "--user-id",
        "1100",
        "--no-run",
        "--image-name",
        image_name,
    ]

    for label in labels:
        cmd += ["--label", label]

    for barg in extra_buildargs or []:
        cmd += ["--build-arg", barg]

    authed_repo = repo
    if git_username and git_password:
        authed_repo = _embed_credentials(repo, git_username, git_password)
    cmd.append(authed_repo)
    envs = [f"{key}={value}" for key, value in (optional_envs or {}).items()]

    config = {
        "Cmd": cmd,
        "Image": repo2docker_image or "quay.io/jupyterhub/repo2docker:2025.12.0",
        "Labels": builder_labels,
        "Volumes": {
            "/var/run/docker.sock": {
                "bind": "/var/run/docker.sock",
                "mode": "rw",
            }
        },
        "Env": envs,
        "HostConfig": {
            "Binds": ["/var/run/docker.sock:/var/run/docker.sock"],
            "SecurityOpt": ["no-new-privileges:true"],
        },
        "Tty": False,
        "AttachStdout": False,
        "AttachStderr": False,
        "OpenStdin": False,
    }

    # NOTE: previous versions exported GIT_CREDENTIAL_ENV here for repo2docker
    # to consume, but upstream removed that integration. Credentials are now
    # embedded in the URL above; nothing else to inject in the container env.
    secrets = [s for s in (git_password, git_username) if s]
    if authed_repo != repo:
        secrets.append(authed_repo)
    # URL-encoding may transform creds (e.g. when they contain special
    # characters such as '@' or ':'); redact the encoded forms too so a
    # partial leak cannot slip through.
    for s in (git_password, git_username):
        if s and quote(s, safe="") != s:
            secrets.append(quote(s, safe=""))

    expected_labels = builder_labels.copy()

    async def ensure_image_labels(docker_client):
        try:
            info = await docker_client.images.inspect(image_name)
        except DockerError as err:
            logger.error("Unable to retrieve cached repo2docker image %s", image_name, exc_info=err)
            raise

        current_labels = (info.get("Config", {}) or {}).get("Labels", {}) or {}
        if all(current_labels.get(key) == value for key, value in expected_labels.items()):
            return

        logger.info("Refreshing labels on cached repo2docker image %s", image_name)

        updated_labels = current_labels.copy()
        updated_labels.update(expected_labels)

        repo_part, tag_part = (image_name.split(":", 1) + ["latest"])[:2]
        container = await docker_client.containers.create({"Image": image_name, "Cmd": ["true"]})
        try:
            await container.commit(repository=repo_part, tag=tag_part, config={"Labels": updated_labels})
        finally:
            try:
                await container.delete(force=True)
            except DockerError as cleanup_err:
                logger.warning("Failed to remove temporary repo2docker container for %s", image_name, exc_info=cleanup_err)

    async with Docker() as docker:
        if reuse_existing:
            # Skip rebuild if the requested image tag already exists
            try:
                await docker.images.get(image_name)
            except DockerError as e:
                if e.status == 404:
                    logger.info(
                        "repo2docker image %s not found locally; building new image", image_name
                    )
                else:
                    logger.exception("Failed to inspect repo2docker image %s", image_name)
                    raise
            else:
                await ensure_image_labels(docker)
                logger.info("Reusing cached repo2docker image %s", image_name)
                if uid and db_context and image_db_manager:
                    async with db_context() as db:
                        await image_db_manager.update(
                            db,
                            DockerImageUpdateSchema(
                                uid=uid, status=BuildStatusType.BUILT,
                                log="Reused cached image.\n",
                            ),
                        )
                return image_name
        container = await docker.containers.run(config=config)

        try:
            if uid and db_context and image_db_manager:
                head_parts = []
                tail_parts = collections.deque(maxlen=LOG_TAIL_LINES)
                line_count = 0
                pending = 0
                async for line in container.log(stdout=True, stderr=True, follow=True):
                    line = _redact(line, secrets)
                    if line_count < LOG_HEAD_LINES:
                        head_parts.append(line)
                    else:
                        tail_parts.append(line)
                    line_count += 1
                    pending += 1
                    if pending >= 10:
                        truncated = line_count > LOG_HEAD_LINES + LOG_TAIL_LINES
                        async with db_context() as db:
                            await image_db_manager.update(
                                db,
                                DockerImageUpdateSchema(
                                    uid=uid,
                                    log=_build_log(head_parts, tail_parts, truncated),
                                ),
                            )
                        pending = 0
                # Flush remaining lines
                if pending:
                    truncated = line_count > LOG_HEAD_LINES + LOG_TAIL_LINES
                    async with db_context() as db:
                        await image_db_manager.update(
                            db,
                            DockerImageUpdateSchema(
                                uid=uid,
                                log=_build_log(head_parts, tail_parts, truncated),
                            ),
                        )

                result = await container.wait()
                exit_code = result.get("StatusCode", -1)
                status = (
                    BuildStatusType.BUILT if exit_code == 0 else BuildStatusType.FAILED
                )
                async with db_context() as db:
                    await image_db_manager.update(
                        db, DockerImageUpdateSchema(uid=uid, status=status)
                    )
            else:
                # No DB context: drain logs to allow the container to finish
                async for _ in container.log(stdout=True, stderr=True, follow=True):
                    pass
                await container.wait()
        finally:
            try:
                await container.delete()
            except DockerError:
                # Container may already be gone if the user deleted the
                # environment mid-build (BuildHandler.delete force-removes
                # the in-flight container). Best-effort cleanup.
                pass
        return image_name
