# Changelog

## 0.1.0 (unreleased)

- Score repositories from 0 to 100 across five dimensions, with caps and confidence.
- Compare repositories, search GitHub by score, draft and submit feedback, and run `doctor`.
- Rank repositories for a stated need by score × relevance; the score itself does not change with intent.
- Use npm and PyPI downloads, deprecation status, and OSV vulnerabilities in scoring.
- Limit response signals to the last 24 months, remove star peaks from the score, and select README evidence by excerpt number.
- Read relevance and feedback input from JSON, and bind feedback submission to the confirmed draft.
