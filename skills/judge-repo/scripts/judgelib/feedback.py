"""构造并提交反馈 Issue。默认只生成草稿，必须显式 --submit 才写入 GitHub。"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re

from . import FEEDBACK_REPO, __version__, ghapi

KINDS = ("bug", "idea", "scoring")
SECRET_RE = re.compile(
    r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY"
    r"|glpat-[A-Za-z0-9_-]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|npm_[A-Za-z0-9]{36}"
    r"|dckr_pat_[A-Za-z0-9_-]{20,}|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}|(?i:(?:password|passwd|secret|api[_-]?key|token)\s*[=:]\s*\S{8,})")


def target() -> str:
    return os.environ.get("JUDGE_REPO_FEEDBACK_REPO", FEEDBACK_REPO)


def sanitize(text: str) -> str:
    if SECRET_RE.search(text):
        raise ghapi.GhError("Feedback appears to contain a credential. Remove it and try again.", ghapi.EXIT_USAGE)
    return text.replace(os.path.expanduser("~"), "~")


def _gh_version() -> str:
    done = ghapi.run(["--version"])
    return done.stdout.splitlines()[0] if done.returncode == 0 and done.stdout else "unknown"


def build(kind: str, title: str, body: str, judged: str | None) -> dict:
    env = f"judge-repo {__version__} · {_gh_version()} · Python {platform.python_version()} · {platform.system()}"
    parts = [sanitize(body).strip(), ""]
    if judged:
        parts += [f"**Repository judged:** {judged}", ""]
    parts += ["---", f"Environment: {env}"]
    return {"repo": target(), "title": f"[{kind}] {sanitize(title).strip()}", "body": "\n".join(parts)}


def similar(title: str) -> list[dict]:
    done = ghapi.run(["search", "issues", "--repo", target(), "--state", "open", "--limit", "5", "--json", "number,title,url", "--", title])
    if done.returncode:
        return []
    return json.loads(done.stdout or "[]")


def fingerprint(draft: dict) -> str:
    """绑定用户确认过的草稿：目标仓库、标题或正文变化都会使确认失效。"""
    return hashlib.sha256(json.dumps(draft, sort_keys=True).encode()).hexdigest()[:16]


def submit(draft: dict) -> str:
    done = ghapi.run(["issue", "create", "--repo", draft["repo"], "--title", draft["title"], "--body-file", "-"], stdin=draft["body"])
    if done.returncode:
        raise ghapi.GhError(f"Could not create the issue: {done.stderr.strip()[:300]}")
    return done.stdout.strip()
