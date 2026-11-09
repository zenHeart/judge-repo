# judge-repo

Agent skill that scores GitHub repositories. The installable unit is `skills/judge-repo/`, so anything needed at runtime must live inside that directory.

- Test: `python3 -m unittest discover -s tests`
- `scripts/judgelib/score.py` owns scoring. `references/model.md` documents it and must change in the same commit.
- Standard library only. Keep each source file under 500 lines.
- `feedback` writes to GitHub only with `--submit`, after the user confirms the draft.
