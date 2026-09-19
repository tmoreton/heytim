from __future__ import annotations

import re
import shlex
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from strands import tool

MAX_ARCHIVE_BYTES = 40_000_000
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
REF_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
GITHUB_ARCHIVE_HOSTS = {"api.github.com", "codeload.github.com"}


class _GitHubRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        if urllib.parse.urlsplit(new_url).hostname not in GITHUB_ARCHIVE_HOSTS:
            raise urllib.error.HTTPError(
                new_url,
                code,
                "GitHub returned an unsafe redirect",
                headers,
                file_pointer,
            )
        return super().redirect_request(
            request, file_pointer, code, message, headers, new_url
        )


def _download_repository_archive(repository: str, ref: str, token: str) -> bytes:
    encoded_repository = "/".join(
        urllib.parse.quote(part, safe="") for part in repository.split("/")
    )
    encoded_ref = urllib.parse.quote(ref, safe="")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{encoded_repository}/tarball/{encoded_ref}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "HeyTim",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        opener = urllib.request.build_opener(_GitHubRedirectHandler())
        with opener.open(request, timeout=30) as response:  # nosec B310
            final_host = urllib.parse.urlsplit(response.geturl()).hostname
            if final_host not in GITHUB_ARCHIVE_HOSTS:
                raise ValueError("GitHub returned an unexpected archive location")
            archive = response.read(MAX_ARCHIVE_BYTES + 1)
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise ValueError("GitHub repository archive is unavailable") from exc
    if len(archive) > MAX_ARCHIVE_BYTES:
        raise ValueError("Repository archive is larger than 40 MB")
    return archive


def _consume_response(response: dict) -> None:
    if response.get("isError"):
        raise RuntimeError("Code Interpreter could not prepare the repository")
    stream = response.get("stream")
    if stream is None:
        return
    for event in stream:
        result = event.get("result") if isinstance(event, dict) else None
        if isinstance(result, dict) and result.get("isError"):
            raise RuntimeError("Code Interpreter could not prepare the repository")


def prepare_repository(
    interpreter: Any,
    credential: Callable[[], str],
    repository: str,
    ref: str = "main",
) -> dict[str, Any]:
    if not isinstance(repository, str) or not REPOSITORY_PATTERN.fullmatch(repository):
        raise ValueError("repository must use the owner/name format")
    if not isinstance(ref, str) or not REF_PATTERN.fullmatch(ref) or ".." in ref:
        raise ValueError("ref is invalid")
    archive = _download_repository_archive(repository, ref, credential())
    session_name, error = interpreter._ensure_session(None)
    if error:
        return error
    session = interpreter._sessions[session_name]
    archive_name = "heytim-repository.tar.gz"
    _consume_response(session.client.upload_file(archive_name, archive))
    workspace = f"workspace/{repository.replace('/', '-')}"
    baseline = f".heytim/baseline/{repository.replace('/', '-')}"
    command = " && ".join(
        [
            f"rm -rf {shlex.quote(workspace)}",
            f"rm -rf {shlex.quote(baseline)}",
            f"mkdir -p {shlex.quote(workspace)}",
            f"mkdir -p {shlex.quote(baseline)}",
            (
                f"tar -xzf {shlex.quote(archive_name)} --strip-components=1 "
                f"-C {shlex.quote(workspace)}"
            ),
            f"cp -a {shlex.quote(workspace)}/. {shlex.quote(baseline)}/",
            f"rm -f {shlex.quote(archive_name)}",
        ]
    )
    _consume_response(session.client.invoke("executeCommand", {"command": command}))
    return {
        "status": "success",
        "content": [
            {
                "text": (
                    f"Prepared {repository} at {workspace}. Inspect and edit files "
                    f"there, run verification, and compare with {baseline} using "
                    "diff -ruN. Then use the GitHub tools to publish the final "
                    "changed files on a branch and open a pull request."
                )
            }
        ],
    }


def repository_workspace_tool(interpreter: Any, credential: Callable[[], str]):
    @tool
    def prepare_repository_workspace(
        repository: str, ref: str = "main"
    ) -> dict[str, Any]:
        """Load a GitHub repository into the secure sandbox for coding and tests."""
        return prepare_repository(interpreter, credential, repository, ref)

    return prepare_repository_workspace
