"""离线回归测试：覆盖指标推导、评分规则、输入校验、反馈闸门和发布清单。"""
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "judge-repo"
sys.path.insert(0, str(SKILL / "scripts"))

import judge  # noqa: E402
from judgelib import __version__, collect, feedback, ghapi, score, signals  # noqa: E402

NOW = datetime(2026, 11, 9, tzinfo=timezone.utc)


def metrics(**extra):
    base = {
        "repo": "o/r", "url": "https://github.com/o/r", "description": "", "stars": 10, "forks": 1, "archived": False,
        "is_fork": False, "license": "MIT", "last_push_days": 1, "commits_365": 300, "releases_365": 4, "response_rate": 0.6,
        "response_median_hours": 24, "issue_sample": 50, "external_merge_rate": 0.6, "reviewed_rate": 0.8, "pr_sample": 50,
        "bus_factor": 5, "active_authors": 30, "has_ci": True, "code_files": 100, "total_files": 150, "test_files": 15,
        "tree_truncated": False, "scorecard": 8, "dependents": 1_000_000, "downloads": None, "star_spike": 2, "readme_flags": [],
        "package": None, "deprecated": None, "weekly_downloads": None, "latest_vulns": None,
    }
    return {**base, **extra}


def iso(days):
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


class ScoreTests(unittest.TestCase):
    def test_perfect_repository_scores_100(self):
        result = score.judge(metrics())
        self.assertEqual((result["score"], result["grade"], result["confidence"]), (100, "A", 1.0))

    def test_same_input_gives_same_output(self):
        self.assertEqual(score.judge(metrics()), score.judge(metrics()))

    def test_caps(self):
        cases = [({"archived": True}, 40), ({"last_push_days": 800}, 45), ({"license": None}, 60)]
        for change, limit in cases:
            self.assertEqual(score.judge(metrics(**change))["score"], limit, change)

    def test_declared_status_caps_and_keeps_evidence(self):
        result = score.judge(metrics(), declared="maintenance", evidence="in maintenance mode")
        self.assertEqual(result["score"], 65)
        self.assertIn("in maintenance mode", result["caps"][0]["reason"])
        self.assertEqual(score.judge(metrics(), declared="deprecated", evidence="x")["score"], 40)

    def test_noassertion_warns_without_cap(self):
        result = score.judge(metrics(license="NOASSERTION"))
        self.assertEqual(result["caps"], [])
        self.assertTrue(any("LICENSE" in w for w in result["warnings"]))

    def test_content_repository_has_no_score(self):
        result = score.judge(metrics(code_files=0, dependents=0))
        self.assertEqual((result["type"], result["score"], result["grade"]), ("content", None, None))

    def test_application_uses_downloads(self):
        result = score.judge(metrics(dependents=1, downloads=100_000))
        self.assertEqual((result["type"], result["score"]), ("application", 100))

    def test_missing_signals_lower_confidence_and_give_range(self):
        result = score.judge(metrics(response_rate=None, response_median_hours=None, external_merge_rate=None, reviewed_rate=None,
                                     scorecard=None, star_spike=None, dependents=None, downloads=None))
        self.assertLess(result["confidence"], 0.7)
        self.assertLess(result["score"], 100)
        self.assertLess(result["range"][0], result["range"][1])

    def test_hiding_response_data_does_not_beat_average_response(self):
        middling = dict(response_rate=0.3, response_median_hours=100, external_merge_rate=0.3, reviewed_rate=0.4)
        hidden = {key: None for key in middling}
        strong = dict(last_push_days=1, commits_365=300, releases_365=4)
        self.assertLessEqual(score.judge(metrics(**strong, **hidden))["score"], score.judge(metrics(**strong, **middling))["score"] + 1)

    def test_star_spike_does_not_change_score(self):
        self.assertEqual(score.judge(metrics(star_spike=500))["score"], score.judge(metrics(star_spike=2))["score"])

    def test_package_downloads_replace_dependents(self):
        result = score.judge(metrics(package="npm:x", weekly_downloads=100_000_000, deprecated=False, latest_vulns=0, dependents=0))
        keys = [i["key"] for d in result["dimensions"] if d["key"] == "adoption" for i in d["indicators"]]
        self.assertEqual((keys, result["type"], result["score"]), (["weekly_downloads"], "library", 100))

    def test_registry_caps(self):
        self.assertEqual(score.judge(metrics(package="npm:x", deprecated=True))["score"], 40)
        self.assertEqual(score.judge(metrics(package="npm:x", deprecated=False, latest_vulns=2))["score"], 60)

    def test_finished_library_is_not_scored_as_abandoned(self):
        quiet = dict(commits_365=2, releases_365=0, package="npm:x", weekly_downloads=5_000_000, latest_vulns=0)
        finished = score.judge(metrics(**quiet, deprecated=False))
        vulnerable = score.judge(metrics(**{**quiet, "latest_vulns": None}, deprecated=False))
        self.assertGreater(finished["raw_score"], vulnerable["raw_score"])
        self.assertTrue(any("finished" in w for w in finished["warnings"]))

    def test_rank_uses_relevance_without_changing_score(self):
        results = [{"input": "a/b", "repo": "a/b", "score": 95}, {"input": "c/d", "repo": "c/d", "score": 70}, {"input": "e/f", "repo": "e/f", "score": 99}]
        ordered = score.rank(results, {"a/b": (0.4, "adjacent"), "c/d": (1.0, "core"), "e/f": (0.0, "unrelated")})
        self.assertEqual([(r["repo"], r["score"], r["rank_score"]) for r in ordered], [("c/d", 70, 70), ("a/b", 95, 38)])

    def test_star_spike_is_never_called_fake(self):
        notes = " ".join(score.judge(metrics(star_spike=99))["warnings"])
        self.assertIn("not proof", notes)


class SignalTests(unittest.TestCase):
    def raw(self, **repo):
        comment = {"createdAt": iso(19), "authorAssociation": "MEMBER", "author": {"login": "m"}}
        issues = [{"createdAt": iso(20), "author": {"login": "u"}, "comments": {"nodes": [comment]}} for _ in range(6)]
        issues.append({"createdAt": iso(1), "author": {"login": "u"}, "comments": {"nodes": []}})
        data = {
            "nameWithOwner": "o/r", "url": "u", "description": None, "stargazerCount": 1, "forkCount": 0, "isArchived": False, "isFork": False,
            "pushedAt": iso(3), "hasIssuesEnabled": True, "licenseInfo": {"spdxId": "MIT"},
            "defaultBranchRef": {"name": "main", "target": {"year": {"totalCount": 8}, "recent": {"nodes": [
                {"author": {"user": {"login": "a"}}}, {"author": {"user": {"login": "a"}}}, {"author": {"user": {"login": "dependabot[bot]"}}}]}}},
            "releases": {"nodes": [{"publishedAt": iso(10), "releaseAssets": {"nodes": [{"downloadCount": 7}]}}]},
            "issues": {"nodes": issues},
            "pullRequests": {"nodes": []},
        }
        data.update(repo)
        return {"repo": data, "paths": [".github/workflows/ci.yml", "index.js", "test.js", "lib/a.ts", "src/b_test.go"],
                "star_history": [{"days": [1, 1, 1, 1, 1, 1, 30]}], "readme": "Now in maintenance mode. New features are closed."}

    def test_derive(self):
        m = signals.derive(self.raw(), NOW)
        self.assertEqual(m["response_rate"], 1.0)
        self.assertEqual(m["issue_sample"], 6)
        self.assertAlmostEqual(m["response_median_hours"], 24.0)
        self.assertEqual((m["bus_factor"], m["active_authors"]), (1, 1))
        self.assertEqual((m["test_files"], m["code_files"], m["has_ci"]), (2, 4, True))
        self.assertEqual((m["star_spike"], m["downloads"], m["releases_365"]), (30.0, 7, 1))
        self.assertEqual(len(m["readme_flags"]), 1)

    def test_small_samples_are_missing(self):
        m = signals.derive(self.raw(issues={"nodes": []}), NOW)
        self.assertIsNone(m["response_rate"])
        self.assertIsNone(m["external_merge_rate"])

    def test_old_issues_and_pulls_are_outside_the_response_window(self):
        comment = {"createdAt": iso(899), "authorAssociation": "MEMBER", "author": {"login": "m"}}
        issues = [{"createdAt": iso(900), "author": {"login": "u"}, "comments": {"nodes": [comment]}} for _ in range(6)]
        pulls = [{"createdAt": iso(900), "state": "MERGED", "mergedAt": iso(899), "authorAssociation": "NONE", "author": {"login": "u"}, "reviews": {"totalCount": 1}} for _ in range(6)]
        m = signals.derive(self.raw(issues={"nodes": issues}, pullRequests={"nodes": pulls}), NOW)
        self.assertEqual((m["response_rate"], m["issue_sample"], m["external_merge_rate"], m["pr_sample"]), (None, 0, None, 0))

    def test_package_license_fills_github_gap(self):
        raw = self.raw(licenseInfo=None)
        raw["package"] = {"ecosystem": "npm", "name": "x", "license": "MIT", "deprecated": False, "weekly_downloads": 9, "vulns": 0}
        m = signals.derive(raw, NOW)
        self.assertEqual((m["license"], m["package"], m["latest_vulns"]), ("MIT", "npm:x", 0))

    def test_readme_flags_strip_terminal_control_sequences(self):
        flags = signals._readme_flags("Project is deprecated \x1b]0;PWNED\x07\x1b[2J\x1b[H now")
        self.assertNotIn("\x1b", flags[0])
        self.assertNotIn("PWNED", flags[0])

    def test_clean_text_removes_invisible_and_c1_characters(self):
        self.assertEqual(signals.clean_text("a\x9b31m\u202eb\u200bc\U000e0041d", 50), "a31mbcd")
        self.assertEqual(signals.clean_text("abcdef", 3), "abc")
        self.assertIsNone(signals.clean_text(None, 3))

    def test_empty_repository_does_not_crash(self):
        m = signals.derive(self.raw(defaultBranchRef=None), NOW)
        self.assertEqual(m["commits_365"], 0)
        self.assertIsNone(m["bus_factor"])


class InputTests(unittest.TestCase):
    def test_accepted_forms(self):
        for text in ("o/r", "https://github.com/o/r", "https://github.com/o/r.git", "git@github.com:o/r.git", "https://github.com/o/r/tree/main"):
            self.assertEqual(collect.parse_repo(text), "o/r", text)

    def test_rejected_forms(self):
        for text in ("a/../b", "nope", "o/r;rm", "--flag/x"[2:] + " y"):
            with self.assertRaises(ghapi.GhError):
                collect.parse_repo(text)

    def test_manifest_name_is_parsed_safely(self):
        self.assertEqual(collect.manifest_name("package.json", '{"name": "vite"}'), "vite")
        self.assertIsNone(collect.manifest_name("package.json", "\n" * 100_000 + "x"))
        self.assertEqual(collect.manifest_name("pyproject.toml", '[project]\nname = "flask"\n'), "flask")

    def test_non_utf8_output_does_not_raise(self):
        with mock.patch("shutil.which", return_value="/bin/gh"), mock.patch("subprocess.run") as run:
            ghapi.run(["api", "x"])
        self.assertEqual((run.call_args.kwargs["encoding"], run.call_args.kwargs["errors"]), ("utf-8", "replace"))

    def test_batch_isolates_unexpected_errors(self):
        with mock.patch.object(judge, "judge_one", side_effect=UnicodeDecodeError("utf-8", b"x", 0, 1, "bad")):
            self.assertEqual(judge.judge_many(["a/b"], "auto")[0]["error"], "Unexpected UnicodeDecodeError")

    def test_package_must_point_back_to_the_repository(self):
        self.assertTrue(collect._points_to("github:moment/moment", "moment/moment"))
        self.assertTrue(collect._points_to("git+https://github.com/vuejs/core.git", "vuejs/core"))
        with mock.patch.object(ghapi, "rest_json", return_value={"full_name": "someone/else"}):
            self.assertFalse(collect._points_to("https://github.com/someone/else", "vuejs/core"))
        self.assertFalse(collect._points_to(None, "vuejs/core"))

    def test_declared_status_requires_evidence(self):
        self.assertEqual(judge.main(["o/r", "--declared-status", "maintenance"]), ghapi.EXIT_USAGE)


class RelevanceInputTests(unittest.TestCase):
    def test_accepts_levels_with_reasons(self):
        self.assertEqual(judge.parse_relevance({"a/b": {"level": 0.8, "reason": "direct"}}, ["a/b"]), {"a/b": (0.8, "direct")})

    def test_rejects_bad_level_missing_reason_or_repo(self):
        good = {"level": 1.0, "reason": "x"}
        for data, repos in (({"a/b": {"level": 0.5, "reason": "x"}}, ["a/b"]), ({"a/b": {"level": 1.0}}, ["a/b"]), ({"a/b": good}, ["a/b", "c/d"]), ([], ["a/b"])):
            with self.assertRaises(ghapi.GhError):
                judge.parse_relevance(data, repos)

    def test_evidence_is_selected_by_number(self):
        self.assertEqual(judge.excerpt(["first", "second"], 2), "second")
        for bad in (0, 3):
            with self.assertRaises(ghapi.GhError):
                judge.excerpt(["first", "second"], bad)

    def test_query_follows_option_terminator(self):
        args = mock.Mock(seed=[], topic=[], query=["--web"], language="go")
        done = mock.Mock(returncode=0, stdout="[]", stderr="")
        with mock.patch.object(ghapi, "run", return_value=done) as run:
            judge.collect_candidates(args, 5)
        command = run.call_args.args[0]
        self.assertLess(command.index("--"), command.index("--web"))
        self.assertLess(command.index("--limit"), command.index("--"))

    def test_candidates_merge_sources_and_report_bad_seeds(self):
        args = mock.Mock(seed=["a/b", "x/y"], topic=["t1,t2"], query=["q"], language=None)
        def rest(path):
            return {"full_name": "a/b", "description": "d", "stargazers_count": 1} if path == "repos/a/b" else None
        with mock.patch.object(ghapi, "rest_json", side_effect=rest), mock.patch.object(judge, "_gh_search", side_effect=[[{"fullName": "A/B"}, {"fullName": "c/d"}], [{"fullName": "e/f"}]]) as search:
            pool, rejected = judge.collect_candidates(args, 10)
        self.assertEqual([(p["repo"], p["sources"]) for p in pool], [("a/b", ["seed", "topic"]), ("c/d", ["topic"]), ("e/f", ["keyword"])])
        self.assertEqual(rejected, ["x/y"])
        self.assertEqual(search.call_args_list[0].args[0][:4], ["--topic", "t1", "--topic", "t2"])


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(feedback, "_gh_version", return_value="gh test")
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, data):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "input.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_submit_requires_the_confirmed_draft(self):
        path = str(self.write({"title": "t", "body": "b"}))
        with mock.patch.object(feedback, "submit", return_value="url") as post, mock.patch("builtins.print"):
            self.assertEqual(judge.main(["feedback", "--input", path, "--submit", "--confirm", "wrong"]), ghapi.EXIT_USAGE)
            post.assert_not_called()
            value = feedback.fingerprint(feedback.build("bug", "t", "b", None))
            self.assertEqual(judge.main(["feedback", "--input", path, "--submit", "--confirm", value]), 0)
        post.assert_called_once()

    def test_rejects_invalid_judged_repository(self):
        path = str(self.write({"title": "t", "body": "b", "repo": "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}))
        self.assertEqual(judge.main(["feedback", "--input", path]), ghapi.EXIT_USAGE)

    def test_rejects_more_credential_forms(self):
        for text in ("AKIA" + "A" * 16, "glpat-" + "a" * 20, "xoxb-" + "1" * 12, "password=" + "a" * 10):
            with self.assertRaises(ghapi.GhError):
                feedback.build("bug", "t", text, None)

    def test_build_redacts_home_and_adds_environment(self):
        draft = feedback.build("bug", "t", f"at {os.path.expanduser('~')}/x", "o/r")
        self.assertEqual(draft["title"], "[bug] t")
        self.assertIn("at ~/x", draft["body"])
        self.assertIn(__version__, draft["body"])

    def test_rejects_credentials(self):
        with self.assertRaises(ghapi.GhError):
            feedback.build("bug", "t", "token ghp_" + "a" * 30, None)

    def test_default_never_creates_an_issue(self):
        with mock.patch.object(feedback, "similar", return_value=[]), mock.patch.object(feedback, "submit") as post, mock.patch("builtins.print"):
            self.assertEqual(judge.main(["feedback", "--input", str(self.write({"title": "t", "body": "b"}))]), 0)
        post.assert_not_called()

    def test_submit_sends_body_through_stdin(self):
        done = mock.Mock(returncode=0, stdout="https://x/1\n", stderr="")
        with mock.patch.object(ghapi, "run", return_value=done) as run:
            self.assertEqual(feedback.submit({"repo": "o/r", "title": "t", "body": "$(whoami)"}), "https://x/1")
        self.assertNotIn("$(whoami)", run.call_args.args[0])
        self.assertEqual(run.call_args.kwargs["stdin"], "$(whoami)")


class PackagingTests(unittest.TestCase):
    def test_versions_match(self):
        plugin = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())
        market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())
        front = (SKILL / "SKILL.md").read_text()
        self.assertEqual(plugin["version"], __version__)
        self.assertEqual(market["plugins"][0]["version"], __version__)
        self.assertIn(f'version: "{__version__}"', front)

    def test_frontmatter_follows_agent_skills_spec(self):
        front = (SKILL / "SKILL.md").read_text().split("---")[1]
        name = re.search(r"^name: (.+)$", front, re.M).group(1)
        description = re.search(r"^description: (.+)$", front, re.M).group(1)
        compatibility = re.search(r"^compatibility: (.+)$", front, re.M).group(1)
        self.assertEqual(name, SKILL.name)
        self.assertRegex(name, r"^[a-z0-9]+(-[a-z0-9]+)*$")
        self.assertLessEqual(len(description), 1024)
        self.assertLessEqual(len(compatibility), 500)

    def test_source_files_stay_under_500_lines(self):
        for path in (SKILL / "scripts").rglob("*.py"):
            self.assertLess(len(path.read_text().splitlines()), 500, path)


if __name__ == "__main__":
    unittest.main()
