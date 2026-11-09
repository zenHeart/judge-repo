# Contributing

The project uses the Python standard library only. Python 3.9+ and an authenticated `gh` are required to run it.

```bash
python3 -m unittest discover -s tests
python3 skills/judge-repo/scripts/judge.py vitejs/vite
```

Before opening a pull request:

- Add or update a test in `tests/test_judge.py` for any behavior change.
- When changing a weight, threshold, or cap, update `references/model.md` and `tests/benchmark/golden-scores.json`, and include before and after scores for at least five repositories.
- Keep every number in the script. `SKILL.md` covers routing and how to report results.
- When releasing, update the version in `judgelib/__init__.py`, `SKILL.md`, and both files in `.claude-plugin/`.
