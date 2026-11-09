#!/usr/bin/env python3
"""judge-repo 命令入口：score（默认）、search、feedback、doctor、version。"""
from __future__ import annotations

import argparse
import json
import platform
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from judgelib import __version__, collect, feedback, ghapi, report, score, signals

SUBCOMMANDS = {"score", "search", "candidates", "feedback", "doctor", "version"}
MAX_WORKERS = 4
MAX_CANDIDATES = 30


def judge_one(name: str, repo_type: str = "auto", declared=None, evidence_id=None) -> dict:
    full = collect.parse_repo(name)
    metrics = signals.derive(collect.fetch(full), datetime.now(timezone.utc))
    return score.judge(metrics, repo_type, declared, excerpt(metrics["readme_flags"], evidence_id) if declared else None)


def excerpt(flags: list[str], evidence_id: int) -> str:
    # 证据由脚本按编号取原文：第三方文本不经过命令行，避免被 shell 展开
    if not 1 <= evidence_id <= len(flags):
        raise ghapi.GhError(f"--evidence-id must be between 1 and {len(flags)}; it refers to a numbered README excerpt.", ghapi.EXIT_USAGE)
    return flags[evidence_id - 1]


def read_json(path: str):
    """读取 Agent 生成的 JSON，只接受文件或 stdin，使文本不经过 shell。"""
    try:
        return json.load(sys.stdin) if path == "-" else json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ghapi.GhError(f"Could not read JSON input: {exc}", ghapi.EXIT_USAGE) from exc


def judge_many(names: list[str], repo_type: str) -> list[dict]:
    def safe(name):
        try:
            return judge_one(name, repo_type)
        except ghapi.GhError as exc:
            # 批量场景下单仓失败不应中断其余结果
            return {"repo": name, "error": str(exc), "score": None}
        except Exception as exc:  # 外部数据异常也只影响该仓库，错误类型保留在结果里
            return {"repo": name, "error": f"Unexpected {type(exc).__name__}", "score": None}
    with ThreadPoolExecutor(MAX_WORKERS) as pool:
        return list(pool.map(safe, names))


def emit(args, payload, markdown: str) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.format == "json" else markdown)


def cmd_score(args) -> int:
    if (args.declared_status is None) != (args.evidence_id is None):
        raise ghapi.GhError("--declared-status and --evidence-id must be used together.", ghapi.EXIT_USAGE)
    if args.declared_status and len(args.repos) != 1:
        raise ghapi.GhError("--declared-status applies to exactly one repository.", ghapi.EXIT_USAGE)
    if args.relevance_file:
        relevance = parse_relevance(read_json(args.relevance_file), args.repos)
        results = [{**r, "input": name} for name, r in zip(args.repos, judge_many(args.repos, args.type))]
        ordered = score.rank(results, relevance)
        emit(args, ordered, report.ranked(ordered))
        return 0
    if len(args.repos) == 1:
        result = judge_one(args.repos[0], args.type, args.declared_status, args.evidence_id)
        emit(args, result, report.single(result))
        return 0
    results = judge_many(args.repos, args.type)
    emit(args, results, report.table(results))
    return 0


def parse_relevance(data, repos: list[str]) -> dict[str, tuple[float, str]]:
    """校验 {"owner/repo": {"level": 1.0, "reason": "..."}}；每个待评仓库都必须有合法档位和理由。"""
    if not isinstance(data, dict) or set(data) != set(repos):
        raise ghapi.GhError("Relevance JSON must cover each repository exactly as given.", ghapi.EXIT_USAGE)
    parsed = {}
    for name, item in data.items():
        level = item.get("level") if isinstance(item, dict) else None
        reason = signals.clean_text(item.get("reason"), 200) if isinstance(item, dict) else None
        if isinstance(level, bool) or level not in score.RELEVANCE_LEVELS or not reason:
            raise ghapi.GhError(f"Invalid relevance for {name!r}. Use level 1.0, 0.8, 0.4, or 0 with a reason.", ghapi.EXIT_USAGE)
        parsed[name] = (float(level), reason)
    return parsed


def _gh_search(arguments: list[str], limit: int) -> list[dict]:
    fields = "fullName,description,stargazersCount"
    done = ghapi.run(["search", "repos", "--limit", str(limit), "--json", fields, *arguments])
    if done.returncode:
        raise ghapi.GhError(f"GitHub search failed: {done.stderr.strip()[:300]}")
    return json.loads(done.stdout or "[]")


def collect_candidates(args, limit: int) -> tuple[list[dict], list[str]]:
    """合并三路候选，顺序为 Agent 指名、topic、关键词；star 只用于在 topic 内取前几名。"""
    found, rejected = {}, []

    def add(name, description, stars, source):
        entry = found.setdefault(name.lower(), {"repo": name, "description": description, "stars": stars, "sources": []})
        if source not in entry["sources"]:
            entry["sources"].append(source)

    for seed in args.seed:
        info = ghapi.rest_json(f"repos/{collect.parse_repo(seed)}")
        if info and info.get("full_name"):
            add(info["full_name"], info.get("description"), info.get("stargazers_count"), "seed")
        else:
            rejected.append(seed)
    language = ["--language", args.language] if args.language else []
    for group in args.topic:
        topics = [flag for topic in group.split(",") for flag in ("--topic", topic.strip())]
        for item in _gh_search([*topics, *language, "--sort", "stars"], limit):
            add(item["fullName"], item.get("description"), item.get("stargazersCount"), "topic")
    # "--" 之后才是查询词，防止查询内容被 gh 当作选项
    for item in _gh_search([*language, "--", *args.query], limit):
        add(item["fullName"], item.get("description"), item.get("stargazersCount"), "keyword")
    return list(found.values())[:limit], rejected


def cmd_candidates(args) -> int:
    pool, rejected = collect_candidates(args, min(MAX_CANDIDATES, max(1, args.candidates)))
    for item in pool:
        item["description"] = signals.clean_text(item["description"], 300)
    print(json.dumps({"candidates": pool, "rejected_seeds": rejected}, ensure_ascii=False, indent=2))
    return 0


def cmd_search(args) -> int:
    limit = max(1, args.limit)
    pool, _ = collect_candidates(args, min(MAX_CANDIDATES, max(limit, args.candidates)))
    names = [item["repo"] for item in pool]
    if not names:
        print("No repositories matched.")
        return 0
    results = sorted(judge_many(names, "auto"), key=lambda x: (x.get("score") is None, -(x.get("score") or 0)))
    emit(args, results[:limit], report.table(results[:limit]))
    return 0


def cmd_feedback(args) -> int:
    data = read_json(args.input)
    if not isinstance(data, dict) or not isinstance(data.get("title"), str) or not isinstance(data.get("body"), str) or data.get("type", "bug") not in feedback.KINDS:
        raise ghapi.GhError('Feedback JSON needs "title" and "body" strings and an optional "type" of bug, idea, or scoring.', ghapi.EXIT_USAGE)
    judged = collect.parse_repo(data["repo"]) if data.get("repo") else None
    draft = feedback.build(data.get("type", "bug"), data["title"], data["body"], judged)
    confirm = feedback.fingerprint(draft)
    if args.submit:
        if args.confirm != confirm:
            raise ghapi.GhError("--confirm does not match this draft. Show the new draft to the user and confirm it again.", ghapi.EXIT_USAGE)
        print(feedback.submit(draft))
        return 0
    payload = {**draft, "confirm": confirm, "similar_open_issues": feedback.similar(data["title"]), "submitted": False}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_doctor(args) -> int:
    done = ghapi.run(["auth", "status"])
    rate = ghapi.rest_json("rate_limit") if done.returncode == 0 else None
    checks = {
        "python": platform.python_version(), "gh_authenticated": done.returncode == 0,
        "graphql_remaining": (rate or {}).get("resources", {}).get("graphql", {}).get("remaining"),
        "core_remaining": (rate or {}).get("resources", {}).get("core", {}).get("remaining"),
    }
    print(json.dumps(checks, indent=2))
    return 0 if checks["gh_authenticated"] else ghapi.EXIT_GH


def add_pool_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("query", nargs="+")
    command.add_argument("--language")
    command.add_argument("--seed", action="append", default=[], metavar="OWNER/REPO", help="repository named for this field")
    command.add_argument("--topic", action="append", default=[], help="GitHub topic; comma-separated topics must all match")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="judge-repo", description="Score GitHub repository health from 0 to 100.")
    sub = root.add_subparsers(dest="command", required=True)
    s = sub.add_parser("score", help="score one repository, or compare several")
    s.add_argument("repos", nargs="+", help="owner/repo or github.com URL")
    s.add_argument("--type", choices=["auto", "library", "application", "content"], default="auto")
    s.add_argument("--format", choices=["md", "json"], default="md")
    s.add_argument("--declared-status", choices=["maintenance", "deprecated"])
    s.add_argument("--evidence-id", type=int, help="number of the README excerpt supporting --declared-status")
    s.add_argument("--relevance-file", metavar="PATH|-", help='JSON {"owner/repo": {"level": 1.0, "reason": "..."}}; rank score = score x level')
    s.set_defaults(func=cmd_score)
    f = sub.add_parser("search", help="search GitHub and rank results by score")
    add_pool_arguments(f)
    f.add_argument("--limit", type=int, default=5, help="results to show (default 5)")
    f.add_argument("--candidates", type=int, default=10, help=f"results to score (default 10, max {MAX_CANDIDATES})")
    f.add_argument("--format", choices=["md", "json"], default="md")
    f.set_defaults(func=cmd_search)
    c = sub.add_parser("candidates", help="list candidate repositories without scoring them")
    add_pool_arguments(c)
    c.add_argument("--candidates", type=int, default=MAX_CANDIDATES, help=f"repositories to list (max {MAX_CANDIDATES})")
    c.set_defaults(func=cmd_candidates)
    b = sub.add_parser("feedback", help="draft an issue; posts only with --submit")
    b.add_argument("--input", required=True, metavar="PATH|-", help='JSON {"type": "bug", "title": "...", "body": "...", "repo": "owner/repo"}')
    b.add_argument("--submit", action="store_true")
    b.add_argument("--confirm", help="confirm value printed with the draft the user approved")
    b.set_defaults(func=cmd_feedback)
    sub.add_parser("doctor", help="check gh, authentication and rate limits").set_defaults(func=cmd_doctor)
    sub.add_parser("version", help="print the version").set_defaults(func=lambda _: print(__version__) or 0)
    return root


def main(argv: list[str]) -> int:
    # 第一个参数不是子命令也不是选项时，按仓库名处理，支持 judge.py owner/repo
    if argv and argv[0] not in SUBCOMMANDS and not argv[0].startswith("-"):
        argv = ["score", *argv]
    args = parser().parse_args(argv)
    try:
        return args.func(args)
    except ghapi.GhError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
