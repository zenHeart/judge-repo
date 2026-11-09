# judge-repo

**English** | [简体中文](README.zh-CN.md)

> Stars measure attention. `judge-repo` scores signals of project health before you depend on a GitHub project: whether it is maintained, responsive, resilient, and used.
>
> **Preview:** thresholds are uncalibrated, and agreement with developer satisfaction has not been established. Use the score as one input to your decision.

[![CI](https://github.com/zenHeart/judge-repo/actions/workflows/ci.yml/badge.svg)](https://github.com/zenHeart/judge-repo/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Agent Skills](https://img.shields.io/badge/Agent%20Skills-compatible-6f42c1.svg)](https://agentskills.io)

## Install

You need Python 3.9+ and the [GitHub CLI](https://cli.github.com), logged in with `gh auth login`.

```bash
npx skills add zenHeart/judge-repo -g
```

This works with Claude Code, Codex, Cursor, and other [Agent Skills](https://agentskills.io) hosts. Drop `-g` to install into the current project only.

<details>
<summary>Claude Code plugin</summary>

```text
/plugin marketplace add zenHeart/judge-repo
/plugin install judge-repo
```

Plugin skills are namespaced, so the command is `/judge-repo:judge-repo`.
</details>

<details>
<summary>Manual install</summary>

```bash
git clone https://github.com/zenHeart/judge-repo
mkdir -p ~/.claude/skills
cp -R judge-repo/skills/judge-repo ~/.claude/skills/
```
</details>

## Usage

```text
/judge-repo moment/moment
```

```text
moment/moment: 65/100 · C · Review before depending (confidence 100%)

| Dimension              | Score | Max |
|------------------------|------:|----:|
| Maintenance activity   |  17.7 |  25 |
| Responsiveness         |   9.8 |  25 |
| Contributor resilience |   8.5 |  15 |
| Engineering            |  18.1 |  20 |
| Real adoption          |  14.1 |  15 |

Capped at 65: README declares maintenance mode
```

| Command | What it does |
|---|---|
| `/judge-repo owner/repo` | Score one repository |
| `/judge-repo a/b c/d e/f` | Compare repositories, best first |
| `/judge-repo search "http client" --language go` | Find candidates and rank them by score and relevance to your need |
| `/judge-repo feedback <message>` | Draft an issue, then post it after you confirm |
| `/judge-repo doctor` | Check `gh`, login, and rate limits |
| `/judge-repo version` | Print the version |

You can also ask in plain language, such as "Is this repo safe to depend on?" or "Which build tools should I learn?"

The script runs without an agent, and `--format json` gives structured output:

```bash
python3 skills/judge-repo/scripts/judge.py vitejs/vite --format json
```

## How scoring works

| Dimension | Points | Signals |
|---|---:|---|
| Maintenance activity | 25 | Last push, yearly commits, releases |
| Responsiveness | 25 | Maintainer response rate and time, external PR merges, reviews |
| Contributor resilience | 15 | Bus factor, active authors |
| Engineering | 20 | License, CI, tests, OpenSSF Scorecard |
| Real adoption | 15 | Package downloads, or dependents and release downloads |

- **Same data, same score.** A script computes every number. The agent only checks whether README status text really declares the project in maintenance or deprecated.
- **The score does not change with intent.** When you state a need, results sort by score × relevance, and each repository shows why it is relevant.
- **Caps override good metrics.** Archived, abandoned, unlicensed, deprecated, vulnerable, or self-declared maintenance projects have a score ceiling.
- **Missing data is reported.** Each result has a confidence value, and low-confidence results include a range.
- **Content repositories get no total.** Lists and prompt collections have no tests or dependents to measure.

The full model is in [references/model.md](skills/judge-repo/references/model.md).

## Limits

- The score measures project health. It does not review code correctness or fit for your use case.
- It cannot prove fake stars. GitHub limited stargazer identity data to repository admins and collaborators in 2026, so only growth shape is available.
- Finished libraries keep their activity points only when npm or PyPI data shows wide use, no deprecation, and no known vulnerability in the latest release.
- Thresholds are an initial calibration and have not been validated against a labeled benchmark. Disagreements are useful: run `/judge-repo feedback`.

## Data and privacy

- GitHub requests use your existing `gh` login. The token is never read or stored by judge-repo.
- Judged repository and package names are also sent to `api.securityscorecards.dev`, the public GitHub dependents page, `registry.npmjs.org`, `api.npmjs.org`, `pypi.org`, `pypistats.org`, and `api.osv.dev`.
- `feedback` posts only after you confirm the draft. It replaces your home path, refuses text that looks like a credential, and adds the tool, `gh`, Python, and OS versions.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Report vulnerabilities through [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
