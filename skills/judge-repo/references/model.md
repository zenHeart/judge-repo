# Scoring model

Every indicator maps linearly (or on a log scale, marked *log*) from its 0-point value to its full-point value.

| Dimension | Max | Indicator | Points | 0 points → full points |
|---|---:|---|---:|---|
| Maintenance activity | 25 | Days since last push | 8 | 365 → 30 |
| | | Commits in 12 months | 9 | 4 → 300, *log* |
| | | Releases in 12 months | 8 | 0 → 4 |
| Responsiveness | 25 | Maintainer response rate | 10 | 5% → 60% |
| | | Median first response | 5 | 720 h → 24 h, *log* |
| | | External PR merge rate | 5 | 5% → 60% |
| | | Merged PRs with a review | 5 | 0% → 80% |
| Contributor resilience | 15 | People behind 50% of recent commits | 8 | 1 → 5 |
| | | Authors in last 100 commits | 7 | 2 → 30, *log* |
| Engineering | 20 | Clear license | 4 | absent → present |
| | | CI configured | 5 | absent → present |
| | | Test file presence | 6 | none → 15% of code files |
| | | OpenSSF Scorecard | 5 | 3 → 8 |
| Real adoption | 15 | Weekly package downloads; without a package, dependents (library) or release downloads (application) | 15 | 1,000 → 100,000,000, or 50 → 1,000,000, or 100 → 100,000, *log* |

Issues and pull requests use the 50 most recent items, limited to the last 24 months. Issues younger than 7 days are excluded. Rates need at least 5 items. Bot accounts are excluded from authorship and response signals.

The star peak is reported as a note and does not change the score.

## Package data

A package counts only when its registry metadata points back to the repository. npm and PyPI are supported. Package data provides weekly downloads, the license when GitHub has none, the registry deprecation status, and known vulnerabilities in the latest release from OSV.

A **finished library** is widely used (at least 1,000,000 weekly downloads), not deprecated, has no known vulnerability in its latest release, has fewer than 12 commits in 12 months, and has at most 1 release in 12 months. Its commit and release indicators count as missing.

## Repository types

- **library**: a verified package, or at least 50 dependent repositories.
- **application**: code repository with fewer dependents. A small new library lands here until dependents accumulate; correct it with `--type library`.
- **content**: fewer than 3 code files, or code under 2% of files. Only activity and responsiveness are reported, with no overall score.

## Missing data

A missing indicator is filled with the average of the other indicators in its dimension, up to 50%. A wholly missing dimension is filled the same way from the other dimensions. `confidence` is the share of total weight actually observed. Below 70%, a range is printed: the low end counts missing signals as zero and the high end as full marks.

`NOASSERTION` licenses count as missing and add a note, because GitHub uses that value for custom and mixed licenses.

## Caps

| Condition | Maximum score |
|---|---:|
| Archived | 40 |
| README declares the project deprecated | 40 |
| Package registry marks the package deprecated | 40 |
| No push for over 2 years | 45 |
| No license | 60 |
| Latest release has a known vulnerability (OSV) | 60 |
| README declares maintenance mode | 65 |

## Grades

| Score | Grade | Meaning |
|---:|---|---|
| 85-100 | A | Safe to depend on |
| 70-84 | B | Usable |
| 50-69 | C | Review before depending |
| 0-49 | D | Not recommended |

## Intent ranking

The score never depends on intent. When the user states a need, the agent assigns each candidate a relevance level with a one-line reason, and results sort by `rank score = score × relevance`.

| Relevance | Meaning |
|---:|---|
| 1.0 | Representative of the category |
| 0.8 | Direct member of the category |
| 0.4 | Adjacent or derivative |
| 0 | Unrelated; removed from results |

## Known limits

- Thresholds were tuned on a small set of repositories and have not been validated against a labeled benchmark.
- The score measures project health. Agreement with developer satisfaction has not been established.
- Relevance levels, new caps, and download thresholds are initial values and need calibration against a labeled intent set.
- Vulnerability caps do not consider severity.
- Package data covers npm and PyPI only. A monorepo package is found only when its name matches the root manifest, the repository, or the owner without a `js` suffix.
- GitHub restricted stargazer identity data to repository admins and collaborators in 2026, so account-level fake-star detection is unavailable. Growth shape is a weak signal.
- Finished, low-churn libraries lose activity points.
- The dependents count is parsed from a GitHub web page and becomes missing if the page changes.
- Test presence counts files. It does not measure coverage.
