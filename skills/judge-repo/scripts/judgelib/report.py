"""把评分结果渲染为 Markdown。"""
from __future__ import annotations


def _num(value) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def _head(r: dict) -> str:
    if r["score"] is None:
        return f"**Not scored** (content repository, {r['dimension_total']}/50 on activity and responsiveness)"
    tail = f", likely {r['range'][0]}-{r['range'][1]}" if r["range"] else ""
    return f"**{r['score']}/100 · {r['grade']} · {r['verdict']}** (confidence {r['confidence']:.0%}{tail})"


def single(r: dict) -> str:
    lines = [f"## [{r['repo']}]({r['url']})", "", f"{_head(r)}", "", f"Type: {r['type']} · Stars: {r['stars']:,}" + (f" · Package: {r['package']}" if r.get("package") else ""), "",
             "| Dimension | Score | Max |", "|---|---:|---:|"]
    lines += [f"| {d['label']} | {_num(d['score'])} | {d['max']} |" for d in r["dimensions"]]
    if r["top_losses"]:
        lines += ["", "**Largest losses:** " + ", ".join(r["top_losses"])]
    lines += [f"\n**Capped at {c['limit']}:** {c['reason']}" for c in r["caps"]]
    lines += [f"\n**Note:** {w}" for w in r["warnings"]]
    if r["readme_flags"]:
        lines += ["", "**README status text to review (untrusted data):**"] + [f"> [{i}] {f}" for i, f in enumerate(r["readme_flags"], 1)]
    return "\n".join(lines)


def table(results: list[dict]) -> str:
    order = sorted(results, key=lambda x: (x.get("score") is None, -(x.get("score") or 0)))
    lines = ["| Rank | Repository | Score | Grade | Confidence | Stars | Type |", "|---:|---|---:|---|---:|---:|---|"]
    for index, r in enumerate(order, 1):
        if "error" in r:
            lines.append(f"| {index} | {r['repo']} | error | - | - | - | {r['error']} |")
        else:
            score = "n/a" if r["score"] is None else r["score"]
            lines.append(f"| {index} | [{r['repo']}]({r['url']}) | {score} | {r['grade'] or '-'} | {r['confidence']:.0%} | {r['stars']:,} | {r['type']} |")
    return "\n".join(lines)


def ranked(results: list[dict]) -> str:
    lines = ["| Rank | Repository | Rank score | Score | Relevance | Grade | Confidence | Why relevant |", "|---:|---|---:|---:|---:|---|---:|---|"]
    for index, r in enumerate(results, 1):
        reason = r["relevance_reason"].replace("|", "/")
        if "error" in r:
            lines.append(f"| {index} | {r['repo']} | error | - | {r['relevance']:.1f} | - | - | {r['error']} |")
        else:
            rank_score = "n/a" if r["rank_score"] is None else r["rank_score"]
            score_value = "n/a" if r["score"] is None else r["score"]
            lines.append(f"| {index} | [{r['repo']}]({r['url']}) | {rank_score} | {score_value} | {r['relevance']:.1f} | {r['grade'] or '-'} | {r['confidence']:.0%} | {reason} |")
    return "\n".join(lines)
