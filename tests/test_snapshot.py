"""评分回归门禁：冻结指标离线重算，分数变化必须是有意更新。"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "judge-repo" / "scripts"))

from judgelib import score  # noqa: E402

BENCHMARK = ROOT / "tests" / "benchmark"


class SnapshotTests(unittest.TestCase):
    def test_scores_match_golden_values(self):
        metrics = json.loads((BENCHMARK / "snapshot.json").read_text(encoding="utf-8"))["metrics"]
        golden = json.loads((BENCHMARK / "golden-scores.json").read_text(encoding="utf-8"))
        actual = {repo: score.judge(item)["score"] for repo, item in metrics.items()}
        self.assertEqual(actual, golden, "If this change is intended, update golden-scores.json and references/model.md.")


if __name__ == "__main__":
    unittest.main()
