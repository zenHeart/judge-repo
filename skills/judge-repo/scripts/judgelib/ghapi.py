"""对 gh CLI 的最小封装：统一错误分类，避免调用方解析 stderr。"""
from __future__ import annotations

import json
import shutil
import subprocess

EXIT_USAGE = 2
EXIT_GH = 3
EXIT_NOT_FOUND = 4


class GhError(Exception):
    def __init__(self, message: str, code: int = EXIT_GH):
        super().__init__(message)
        self.code = code


def run(args: list[str], stdin: str | None = None, timeout: int = 90) -> subprocess.CompletedProcess:
    if not shutil.which("gh"):
        raise GhError("GitHub CLI not found. Install it from https://cli.github.com and run `gh auth login`.")
    try:
        return subprocess.run(["gh", *args], input=stdin, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise GhError(f"gh timed out after {timeout}s: {' '.join(args[:2])}") from exc


def _raise_if_fatal(stderr: str) -> None:
    low = stderr.lower()
    if "rate limit" in low:
        raise GhError("GitHub API rate limit reached. Run `gh api rate_limit` and retry after the reset.")
    if "gh auth login" in low or "http 401" in low:
        raise GhError("gh is not authenticated. Run `gh auth login`.")


def rest_text(path: str, accept: str | None = None) -> str | None:
    """读取 REST 路径。403/404 表示信号不可用，返回 None，由计分层按缺失处理。"""
    args = ["api", path]
    if accept:
        args += ["-H", f"Accept: {accept}"]
    done = run(args)
    if done.returncode == 0:
        return done.stdout
    _raise_if_fatal(done.stderr + done.stdout)
    return None


def rest_json(path: str):
    text = rest_text(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def graphql_repo(query: str, **variables: str) -> dict:
    args = ["api", "graphql", "-f", "query=" + query]
    for key, value in variables.items():
        # 全部用 -f 传字符串，避免 -F 把纯数字仓库名转成整数
        args += ["-f", f"{key}={value}"]
    done = run(args, timeout=120)
    try:
        payload = json.loads(done.stdout or "{}")
    except json.JSONDecodeError:
        payload = {}
    repo = (payload.get("data") or {}).get("repository")
    if repo:
        return repo
    message = json.dumps(payload.get("errors") or done.stderr)[:300]
    _raise_if_fatal(message)
    if "NOT_FOUND" in message or "Could not resolve" in message:
        raise GhError(f"Repository not found or not accessible: {variables.get('owner')}/{variables.get('name')}", EXIT_NOT_FOUND)
    raise GhError(f"GitHub GraphQL request failed: {message}")
