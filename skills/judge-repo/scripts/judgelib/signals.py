"""把原始数据推导成扁平指标。纯函数，可用固定输入回归测试。"""
from __future__ import annotations

import re
import statistics
import unicodedata
from datetime import datetime, timedelta

MAINTAINERS = {"OWNER", "MEMBER", "COLLABORATOR"}
MIN_SAMPLE = 5
BOT_RE = re.compile(r"(\[bot\]$|-bot$|^dependabot|^renovate|^github-actions)", re.I)
CODE_EXT = {"js", "jsx", "mjs", "cjs", "ts", "tsx", "py", "go", "rs", "c", "h", "cc", "cpp", "hpp", "java", "kt", "swift",
            "rb", "php", "cs", "scala", "ex", "exs", "zig", "lua", "vue", "svelte", "dart", "sh"}
TEST_RE = re.compile(r"(^|/)(tests?|__tests__|specs?)(/|$)|(^|/)test[._-]|[._-](test|spec)[._-]|[._-](test|spec)\.|_test\.", re.I)
# 响应类指标只看近两年，避免冷清仓库用多年前的行为代表现在
RESPONSE_WINDOW = timedelta(days=730)
CONTROL_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
STATUS_RE = re.compile(r"maintenance mode|no longer (?:actively )?maintained|unmaintained|deprecated|legacy project|abandoned|archived", re.I)


def clean_text(text, limit: int) -> str | None:
    """净化第三方文本：去掉终端控制序列和不可见格式字符（Cf），并限长。"""
    if not isinstance(text, str):
        return None
    return "".join(c for c in CONTROL_RE.sub("", text) if unicodedata.category(c) != "Cf")[:limit]


def ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _login(node: dict | None) -> str:
    return ((node or {}).get("author") or {}).get("login") or ""


def _bus_factor(names: list[str]) -> tuple[int | None, int]:
    counts: dict[str, int] = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1
    if not counts:
        return None, 0
    total, covered, people = sum(counts.values()), 0, 0
    for value in sorted(counts.values(), reverse=True):
        covered += value
        people += 1
        if covered * 2 >= total:
            break
    return people, len(counts)


def _issues(nodes: list[dict], now: datetime) -> tuple[float | None, float | None, int]:
    hours, sample = [], 0
    for issue in nodes:
        created = ts(issue["createdAt"])
        # 新 Issue 还没来得及响应，计入会系统性低估维护者
        if now - created < timedelta(days=7) or now - created > RESPONSE_WINDOW:
            continue
        sample += 1
        author = _login(issue)
        for comment in issue["comments"]["nodes"]:
            login = _login(comment)
            if login != author and comment["authorAssociation"] in MAINTAINERS and not BOT_RE.search(login):
                hours.append((ts(comment["createdAt"]) - created).total_seconds() / 3600)
                break
    if sample < MIN_SAMPLE:
        return None, None, sample
    return len(hours) / sample, statistics.median(hours) if hours else None, sample


def _prs(nodes: list[dict], now: datetime) -> tuple[float | None, float | None, int]:
    closed = [p for p in nodes if p["state"] != "OPEN" and now - ts(p["createdAt"]) <= RESPONSE_WINDOW]
    external = [p for p in closed if p["authorAssociation"] not in MAINTAINERS and not BOT_RE.search(_login(p))]
    merged = [p for p in closed if p.get("mergedAt")]
    ext_rate = sum(1 for p in external if p.get("mergedAt")) / len(external) if len(external) >= MIN_SAMPLE else None
    reviewed = sum(1 for p in merged if p["reviews"]["totalCount"]) / len(merged) if len(merged) >= MIN_SAMPLE else None
    return ext_rate, reviewed, len(closed)


def _star_spike(history: list[dict] | None) -> float | None:
    days = [day for week in history or [] for day in week.get("days", [])]
    if not days or sum(days) == 0:
        return None
    return max(days) / max(statistics.median(days), 1)


def _readme_flags(readme: str | None) -> list[str]:
    flags, last_end = [], -1
    # README 不可信，先剥离控制序列，防止摘录操纵用户终端
    readme = clean_text(readme, len(readme or "")) or ""
    for match in STATUS_RE.finditer(readme):
        # 跳过落在上一段摘录内的命中，避免同一句话重复出现
        if match.start() < last_end:
            continue
        start, last_end = max(match.start() - 70, 0), min(match.end() + 70, len(readme))
        flags.append(re.sub(r"\s+", " ", readme[start:last_end]).strip())
        if len(flags) == 3:
            break
    return flags


def derive(raw: dict, now: datetime) -> dict:
    repo = raw["repo"]
    branch = repo.get("defaultBranchRef") or {}
    target = branch.get("target") or {}
    names = []
    for commit in (target.get("recent") or {}).get("nodes", []):
        author = commit.get("author") or {}
        name = (author.get("user") or {}).get("login") or author.get("name") or ""
        if name and not BOT_RE.search(name):
            names.append(name)
    bus, authors = _bus_factor(names)
    releases = repo["releases"]["nodes"]
    recent = [r for r in releases if r.get("publishedAt") and now - ts(r["publishedAt"]) < timedelta(days=365)]
    assets = [a["downloadCount"] for r in releases for a in r["releaseAssets"]["nodes"]]
    enabled = repo.get("hasIssuesEnabled", True)
    rate, median, sample = _issues(repo["issues"]["nodes"], now) if enabled else (None, None, 0)
    ext, reviewed, pr_sample = _prs(repo["pullRequests"]["nodes"], now)
    paths = raw.get("paths") or []
    code = [p for p in paths if p.rsplit(".", 1)[-1].lower() in CODE_EXT and "." in p.rsplit("/", 1)[-1]]
    tests = [p for p in code if TEST_RE.search(p)]
    package = raw.get("package") or {}
    # GitHub 未识别 license 时以包仓库声明为准，避免误触无 license 封顶
    spdx = (repo.get("licenseInfo") or {}).get("spdxId") or package.get("license")
    return {
        "repo": repo["nameWithOwner"], "url": repo["url"], "description": clean_text(repo.get("description"), 300),
        "stars": repo["stargazerCount"], "forks": repo["forkCount"],
        "archived": repo["isArchived"], "is_fork": repo["isFork"], "license": spdx,
        "last_push_days": (now - ts(repo["pushedAt"])).days,
        "commits_365": target.get("year", {}).get("totalCount", 0), "releases_365": len(recent),
        "response_rate": rate, "response_median_hours": median, "issue_sample": sample,
        "external_merge_rate": ext, "reviewed_rate": reviewed, "pr_sample": pr_sample,
        "bus_factor": bus, "active_authors": authors,
        "has_ci": None if not paths else any(p.startswith(".github/workflows/") for p in paths) or any(
            p in paths for p in (".gitlab-ci.yml", ".circleci/config.yml", ".travis.yml", "azure-pipelines.yml")),
        "code_files": len(code), "total_files": len(paths), "test_files": len(tests), "tree_truncated": raw.get("tree_truncated", False),
        "scorecard": raw.get("scorecard"), "dependents": raw.get("dependents"),
        "downloads": sum(assets) if assets else None, "star_spike": _star_spike(raw.get("star_history")),
        "readme_flags": _readme_flags(raw.get("readme")),
        "package": f"{package['ecosystem']}:{package['name']}" if package else None,
        "deprecated": package.get("deprecated"), "weekly_downloads": package.get("weekly_downloads"), "latest_vulns": package.get("vulns"),
    }
