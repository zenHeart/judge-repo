#!/usr/bin/env python3
"""联网重录指标快照并更新黄金分数。只在有意更换快照时运行。"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "skills" / "judge-repo" / "scripts"))
from judgelib import collect, signals  # noqa: E402

SNAPSHOT = HERE / "snapshot.json"


def main() -> None:
    now = datetime.now(timezone.utc)
    repos = sorted(json.loads(SNAPSHOT.read_text(encoding="utf-8"))["metrics"])
    metrics = {}
    for repo in repos:
        item = signals.derive(collect.fetch(repo), now)
        item.update(description=None, readme_flags=[])  # 快照不保存第三方文本
        metrics[repo] = item
    SNAPSHOT.write_text(json.dumps({"as_of": now.date().isoformat(), "metrics": metrics}, indent=0, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
