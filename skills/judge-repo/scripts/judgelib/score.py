"""确定性评分模型。指标含义与阈值的说明见 references/model.md。"""
from __future__ import annotations

import math

CAP_ARCHIVED = 40
CAP_STALE = 45
CAP_STALE_DAYS = 730
CAP_NO_LICENSE = 60
CAP_MAINTENANCE = 65
CAP_DEPRECATED = 40
CAP_VULNERABLE = 60
FILL_LIMIT = 0.5
FINISHED_DOWNLOADS = 1_000_000
FINISHED_COMMITS = 12
RELEVANCE_LEVELS = (1.0, 0.8, 0.4, 0.0)
LOW_CONFIDENCE = 0.7
SPIKE_WARNING = 20
GRADES = [(85, "A", "Safe to depend on"), (70, "B", "Usable"), (50, "C", "Review before depending"), (0, "D", "Not recommended")]


def linear(value, low, high):
    """把 value 从 [low, high] 映射到 [0, 1]；low 可大于 high，表示越小越好。"""
    if value is None:
        return None
    return max(0.0, min(1.0, (value - low) / (high - low)))


def logscale(value, low, high):
    if value is None:
        return None
    return linear(math.log10(value + 1), math.log10(low + 1), math.log10(high + 1))


def classify(m: dict, override: str = "auto") -> str:
    if override != "auto":
        return override
    code, total = m["code_files"], m["total_files"]
    if total and (code < 3 or code / total < 0.02):
        return "content"
    return "library" if m.get("package") or (m["dependents"] or 0) >= 50 else "application"


def _test_ratio(m: dict):
    if not m["code_files"]:
        return None
    # 约 15% 的代码文件是测试即视为覆盖合理，这是粗粒度启发式，不代表真实覆盖率
    return min(1.0, m["test_files"] / max(m["code_files"] * 0.15, 1))


def _finished(m: dict, declared: str | None) -> bool:
    """成熟稳定的库少提交、少发版是正常状态，不应按停止维护计分。"""
    return (not declared and not m["archived"] and m.get("deprecated") is False and m.get("latest_vulns") == 0
            and (m.get("weekly_downloads") or 0) >= FINISHED_DOWNLOADS
            and m["commits_365"] < FINISHED_COMMITS and m["releases_365"] <= 1)


def _adoption(m: dict, kind: str) -> tuple:
    if m.get("weekly_downloads") is not None:
        return ("weekly_downloads", "Weekly package downloads", 15, logscale(m["weekly_downloads"], 1_000, 100_000_000))
    if kind == "library":
        return ("dependents", "Dependent repositories", 15, logscale(m["dependents"], 50, 1_000_000))
    return ("downloads", "Release downloads", 15, logscale(m["downloads"], 100, 100_000))


def _indicators(m: dict, kind: str, finished: bool) -> list[tuple[str, str, int, list]]:
    license_ok = None if m["license"] == "NOASSERTION" else (1.0 if m["license"] else 0.0)
    commits = None if finished else logscale(m["commits_365"], 4, 300)
    releases = None if finished else linear(m["releases_365"], 0, 4)
    return [
        ("activity", "Maintenance activity", 25, [
            ("last_push_days", "Days since last push", 8, linear(m["last_push_days"], 365, 30)),
            ("commits_365", "Commits in 12 months", 9, commits),
            ("releases_365", "Releases in 12 months", 8, releases),
        ]),
        ("responsiveness", "Responsiveness", 25, [
            ("response_rate", "Maintainer response rate", 10, linear(m["response_rate"], 0.05, 0.6)),
            ("response_median_hours", "Median response hours", 5, logscale(m["response_median_hours"], 720, 24)),
            ("external_merge_rate", "External PR merge rate", 5, linear(m["external_merge_rate"], 0.05, 0.6)),
            ("reviewed_rate", "Merged PRs with review", 5, linear(m["reviewed_rate"], 0, 0.8)),
        ]),
        ("resilience", "Contributor resilience", 15, [
            ("bus_factor", "People behind 50% of commits", 8, linear(m["bus_factor"], 1, 5)),
            ("active_authors", "Authors in last 100 commits", 7, logscale(m["active_authors"], 2, 30)),
        ]),
        ("engineering", "Engineering", 20, [
            ("license", "Clear license", 4, license_ok),
            ("has_ci", "CI configured", 5, None if m["has_ci"] is None else float(m["has_ci"])),
            ("test_files", "Test file presence", 6, _test_ratio(m)),
            ("scorecard", "OpenSSF Scorecard", 5, linear(m["scorecard"], 3, 8)),
        ]),
        ("adoption", "Real adoption", 15, [
            _adoption(m, kind),
        ]),
    ]


def _caps(m: dict, declared: str | None, evidence: str | None) -> list[dict]:
    caps = []
    if m["archived"]:
        caps.append({"reason": "Repository is archived", "limit": CAP_ARCHIVED})
    if m["last_push_days"] > CAP_STALE_DAYS:
        caps.append({"reason": "No push for more than 2 years", "limit": CAP_STALE})
    if not m["license"]:
        caps.append({"reason": "No license detected", "limit": CAP_NO_LICENSE})
    if declared:
        limit = CAP_MAINTENANCE if declared == "maintenance" else CAP_DEPRECATED
        caps.append({"reason": f"README declares {declared}: {evidence}", "limit": limit})
    if m.get("deprecated"):
        caps.append({"reason": f"Package registry marks {m.get('package')} as deprecated", "limit": CAP_DEPRECATED})
    if m.get("latest_vulns"):
        caps.append({"reason": f"Latest release of {m.get('package')} has {m['latest_vulns']} known vulnerabilities (OSV)", "limit": CAP_VULNERABLE})
    return caps


def _warnings(m: dict, finished: bool = False) -> list[str]:
    notes = []
    if finished:
        notes.append("Widely used, not deprecated, no known vulnerabilities in the latest release: low commit and release counts are treated as a finished library.")
    if m["license"] == "NOASSERTION":
        notes.append("License could not be classified by GitHub; read the LICENSE file before depending on it.")
    if m["is_fork"]:
        notes.append("This repository is a fork; signals describe the fork only.")
    if m["tree_truncated"]:
        notes.append("Git tree was truncated by GitHub; file-based signals use a partial listing.")
    if (m["star_spike"] or 0) >= SPIKE_WARNING:
        notes.append("Star growth has an unusual daily peak. This can be a launch or manipulation; it is not proof of fake stars.")
    return notes


def judge(m: dict, repo_type: str = "auto", declared: str | None = None, evidence: str | None = None) -> dict:
    kind = classify(m, repo_type)
    dims, losses, low, missing_weight = [], [], 0.0, 0.0
    finished = _finished(m, declared)
    groups = _indicators(m, kind, finished)
    if kind == "content":
        groups = [g for g in groups if g[0] in ("activity", "responsiveness")]
    for key, label, weight, indicators in groups:
        present = sum(w for _, _, w, v in indicators if v is not None)
        total = sum(w for _, _, w, _ in indicators)
        rows = []
        points = None
        if present:
            # 缺失指标按已有指标均值填补，但不超过 FILL_LIMIT，避免隐藏数据反而占便宜
            ratio = sum(w * v for _, _, w, v in indicators if v is not None) / present
            filled = sum(w * v for _, _, w, v in indicators if v is not None) + (total - present) * min(ratio, FILL_LIMIT)
            points = filled / total * weight
        for ikey, ilabel, iweight, value in indicators:
            scaled = None if value is None else value * iweight
            rows.append({"key": ikey, "label": ilabel, "value": m.get(ikey), "points": scaled, "max": iweight})
            if value is None:
                missing_weight += iweight * weight / total
            else:
                low += scaled * weight / total
                losses.append((iweight * (1 - value) * weight / total, ilabel))
        dims.append({"key": key, "label": label, "score": points, "max": weight, "indicators": rows})
    available = sum(d["max"] for d in dims if d["score"] is not None)
    full = sum(d["max"] for d in dims)
    result = {
        "repo": m["repo"], "url": m["url"], "description": m["description"], "stars": m["stars"], "type": kind,
        "dimensions": dims, "confidence": (full - missing_weight) / full, "readme_flags": m["readme_flags"], "warnings": _warnings(m, finished), "package": m.get("package"),
        "caps": [], "top_losses": [label for _, label in sorted(losses, reverse=True)[:3] if _ > 0.5],
        "score": None, "range": None, "grade": None, "verdict": "Not scored: content repository",
    }
    if kind == "content":
        result["dimension_total"] = round(sum(d["score"] or 0 for d in dims))
        return result
    earned = sum(d["score"] for d in dims if d["score"] is not None)
    raw = earned + (full - available) * min(earned / available, FILL_LIMIT) if available else 0.0
    caps = _caps(m, declared, evidence)
    limit = min([c["limit"] for c in caps], default=100)
    score = min(round(raw), limit)
    grade, verdict = next((g, v) for floor, g, v in GRADES if score >= floor)
    result.update(raw_score=round(raw), score=score, grade=grade, verdict=verdict, caps=caps)
    if result["confidence"] < LOW_CONFIDENCE:
        result["range"] = [min(round(low), limit), min(round(low + missing_weight), limit)]
    return result


def rank(results: list[dict], relevance: dict[str, tuple[float, str]]) -> list[dict]:
    """按意图排序：排序分 = 总分 × 相关性。总分本身不变，相关性为 0 的仓库被过滤。"""
    ranked = []
    for result, (level, reason) in ((r, relevance[r["input"]]) for r in results):
        if level == 0:
            continue
        score_value = result.get("score")
        ranked.append({**result, "relevance": level, "relevance_reason": reason,
                       "rank_score": None if score_value is None else round(score_value * level)})
    return sorted(ranked, key=lambda x: (x["rank_score"] is None, -(x["rank_score"] or 0)))
