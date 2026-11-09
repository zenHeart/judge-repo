"""从 GitHub 和两个公开数据源采集某仓库的原始数据。"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from . import ghapi

REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
URL_RE = re.compile(r"^(?:https?://github\.com/|git@github\.com:|github\.com/)([^/\s]+/[^/\s#?]+)")
GITHUB_RE = re.compile(r"(?:github\.com[/:]|^github:)([^/\s]+/[^/\s#?]+?)(?:\.git)?(?:[/#?]|$)", re.I)
UA = "judge-repo"
MAX_RESPONSE = 16 * 1024 * 1024
MAX_MANIFEST = 256 * 1024

QUERY = """query($owner:String!,$name:String!,$year:GitTimestamp!){repository(owner:$owner,name:$name){
 nameWithOwner url description stargazerCount forkCount isArchived isFork createdAt pushedAt hasIssuesEnabled
 licenseInfo{spdxId}
 defaultBranchRef{name target{...on Commit{year:history(since:$year){totalCount}
   recent:history(first:100){nodes{author{user{login} name}}}}}}
 releases(first:30,orderBy:{field:CREATED_AT,direction:DESC}){nodes{publishedAt
   releaseAssets(first:20){nodes{downloadCount}}}}
 issues(last:50,orderBy:{field:CREATED_AT,direction:ASC}){nodes{createdAt author{login}
   comments(first:5){nodes{createdAt authorAssociation author{login}}}}}
 pullRequests(last:50,orderBy:{field:CREATED_AT,direction:ASC}){nodes{state mergedAt authorAssociation
   createdAt author{login} reviews(first:1){totalCount}}}
}}"""


def parse_repo(text: str) -> str:
    """把 owner/repo、HTTPS 或 SSH 地址规范化为 owner/repo；非法输入抛错，防止路径注入。"""
    value = text.strip().rstrip("/")
    match = URL_RE.match(value)
    if match:
        value = match.group(1)
    value = re.sub(r"\.git$", "", value)
    if not REPO_RE.match(value) or ".." in value:
        raise ghapi.GhError(f"Not a GitHub repository: {text!r}. Use owner/repo or a github.com URL.", ghapi.EXIT_USAGE)
    return value


def _http_text(url: str) -> str | None:
    # 第三方数据只是可选加分项，任何网络或解析失败都按信号缺失处理
    try:
        request = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.read(MAX_RESPONSE).decode("utf-8", "replace")
    except Exception:
        return None


def _scorecard(full: str) -> float | None:
    text = _http_text(f"https://api.securityscorecards.dev/projects/github.com/{full}")
    try:
        value = json.loads(text).get("score") if text else None
    except (json.JSONDecodeError, AttributeError):
        return None
    return value if isinstance(value, (int, float)) and value >= 0 else None


def _dependents(full: str) -> int | None:
    # GitHub 未提供 dependents API；页面结构变化时退化为缺失，不影响其他信号
    html = _http_text(f"https://github.com/{full}/network/dependents")
    match = re.search(r"([\d,]+)\s+Repositories", html or "")
    return int(match.group(1).replace(",", "")) if match else None


def _http_json(url: str, payload: dict | None = None):
    # 包仓库数据同样是可选信号，失败时返回 None，由计分层按缺失处理
    try:
        body = json.dumps(payload).encode() if payload else None
        request = urllib.request.Request(url, data=body, headers={"User-Agent": UA, "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read(MAX_RESPONSE).decode("utf-8", "replace"))
    except Exception:
        return None


def _points_to(url, canonical: str) -> bool:
    """确认包仓库声明的源码地址就是本仓库，防止同名包被错认。"""
    match = GITHUB_RE.search(url or "") if isinstance(url, str) else None
    if not match:
        return False
    declared = match.group(1)
    if declared.lower() == canonical.lower():
        return True
    # 仓库改名或迁移后，包元数据里的旧地址由 GitHub 重定向到当前仓库
    moved = ghapi.rest_json(f"repos/{declared}") if REPO_RE.match(declared) and ".." not in declared else None
    return bool(moved) and str(moved.get("full_name", "")).lower() == canonical.lower()


def manifest_name(manifest: str, text: str) -> str | None:
    """取包名。清单来自不可信仓库，先限长；package.json 用解析器，避免正则回溯。"""
    text = text[:MAX_MANIFEST]
    if manifest == "package.json":
        try:
            name = json.loads(text).get("name")
        except (json.JSONDecodeError, AttributeError):
            return None
        return name if isinstance(name, str) else None
    match = re.search(r"""^name[ \t]*=[ \t]*["']([^"'\n]+)["']""", text, re.M)
    return match.group(1) if match else None


def _manifest_names(canonical: str, paths: list[str], manifest: str) -> list[str]:
    names = []
    if manifest in paths:
        text = ghapi.rest_text(f"repos/{canonical}/contents/{manifest}", "application/vnd.github.raw") or ""
        name = manifest_name(manifest, text)
        if name:
            names.append(name)
    # monorepo 的根清单通常是私有名，发布名常与仓库名或组织名（去掉 js 后缀）相同；是否属于本仓库由 _points_to 确认
    owner, short = canonical.split("/", 1)
    guesses = [short, owner[:-2] if owner.lower().endswith("js") else owner]
    return names + [guess for guess in guesses if guess not in names]


def _npm(canonical: str, paths: list[str]) -> dict | None:
    for name in _manifest_names(canonical, paths, "package.json"):
        meta = _http_json(f"https://registry.npmjs.org/{quote(name, safe='@/')}/latest")
        repository = (meta or {}).get("repository")
        url = repository.get("url") if isinstance(repository, dict) else repository
        if not meta or not _points_to(url, canonical):
            continue
        spdx = meta.get("license")
        stats = _http_json(f"https://api.npmjs.org/downloads/point/last-week/{quote(name, safe='@/')}") or {}
        return {"ecosystem": "npm", "name": name, "version": meta.get("version"),
                "license": spdx.get("type") if isinstance(spdx, dict) else spdx,
                "deprecated": bool(meta.get("deprecated")), "weekly_downloads": stats.get("downloads")}
    return None


def _pypi(canonical: str, paths: list[str]) -> dict | None:
    for name in _manifest_names(canonical, paths, "pyproject.toml"):
        meta = _http_json(f"https://pypi.org/pypi/{quote(name, safe='')}/json")
        info = (meta or {}).get("info") or {}
        urls = list((info.get("project_urls") or {}).values()) + [info.get("home_page")]
        if not info or not any(_points_to(u, canonical) for u in urls):
            continue
        classifiers = info.get("classifiers") or []
        named = [c.rsplit(" :: ", 1)[-1] for c in classifiers if c.startswith("License :: ")]
        short = info.get("license") if len(info.get("license") or "") < 40 else None
        stats = _http_json(f"https://pypistats.org/api/packages/{quote(name, safe='')}/recent") or {}
        return {"ecosystem": "PyPI", "name": name, "version": info.get("version"),
                "license": info.get("license_expression") or short or (named[0] if named else None),
                "deprecated": "Development Status :: 7 - Inactive" in classifiers,
                "weekly_downloads": (stats.get("data") or {}).get("last_week")}
    return None


def _package(canonical: str, paths: list[str]) -> dict | None:
    if "package.json" in paths:
        found = _npm(canonical, paths)
    elif any(p in paths for p in ("pyproject.toml", "setup.py", "setup.cfg")):
        found = _pypi(canonical, paths)
    else:
        found = None
    if found:
        osv = _http_json("https://api.osv.dev/v1/query", {"package": {"name": found["name"], "ecosystem": found["ecosystem"]},
                                                         "version": found["version"]})
        found["vulns"] = None if osv is None else sum(1 for v in osv.get("vulns", []) if not v.get("withdrawn"))
    return found


def fetch(full: str) -> dict:
    owner, name = full.split("/", 1)
    year = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")
    repo = ghapi.graphql_repo(QUERY, owner=owner, name=name, year=year)
    canonical = repo["nameWithOwner"]
    branch = (repo.get("defaultBranchRef") or {}).get("name")
    tree = ghapi.rest_json(f"repos/{canonical}/git/trees/{quote(branch, safe='')}?recursive=1") if branch else None
    history = ghapi.rest_json(f"repos/{canonical}/stargazers/history")
    paths = [item["path"] for item in (tree or {}).get("tree", []) if item.get("type") == "blob"]
    return {
        "repo": repo,
        "paths": paths,
        "tree_truncated": bool((tree or {}).get("truncated")),
        "star_history": history if isinstance(history, list) else None,
        "readme": ghapi.rest_text(f"repos/{canonical}/readme", "application/vnd.github.raw"),
        "scorecard": _scorecard(canonical),
        "dependents": _dependents(canonical),
        "package": _package(canonical, paths),
    }
