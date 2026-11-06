"""Run with: python3 scripts/test_ledger.py"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import ledger  # noqa: E402
import measure  # noqa: E402
import transcripts  # noqa: E402

SCRIPT = Path(__file__).resolve().parent / "ledger.py"
SECRET = "SECRET-PROMPT-TEXT"
OPUS = "claude-opus-5-5"


def stamp(seconds):
    return f"2026-11-02T10:{seconds // 60:02d}:{seconds % 60:02d}.000Z"


def human(uid, at, cwd):
    return {"type": "user", "uuid": uid, "timestamp": stamp(at), "cwd": cwd, "origin": {"kind": "human"},
            "message": {"role": "user", "content": SECRET}}


def tool_result(at, cwd):
    return {"type": "user", "uuid": f"t{at}", "timestamp": stamp(at), "cwd": cwd,
            "message": {"role": "user", "content": [{"type": "tool_result"}]}}


def call(msg, at, cwd, model=OPUS, usage=None, tools=(), **line):
    base = {"input_tokens": 10, "output_tokens": 100, "cache_read_input_tokens": 1000,
            "output_tokens_details": {"thinking_tokens": 40},
            "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 200}}
    content = [{"type": "tool_use", "name": tool, "input": {"file_path": SECRET}} for tool in tools]
    return {"type": "assistant", "uuid": f"a{msg}{at}", "timestamp": stamp(at), "cwd": cwd, "effort": "high",
            "message": {"id": msg, "model": model, "usage": {**base, **(usage or {})},
                        "content": content or [{"type": "text", "text": SECRET}]}, **line}


def turn(at, ms, cwd):
    return {"type": "system", "subtype": "turn_duration", "durationMs": ms, "timestamp": stamp(at), "cwd": cwd}


class LedgerCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.tmp = Path(os.path.realpath(temp.name))
        self.root = self.tmp / "work" / "app"
        (self.root / "ledger").mkdir(parents=True)
        self.config = self.tmp / "config"
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.config)
        self.addCleanup(os.environ.pop, "CLAUDE_CONFIG_DIR", None)
        self.cwd = str(self.root)

    def transcript(self, lines, session="s1", cwd=None):
        path = self.config / "projects" / transcripts.encode_path(cwd or self.cwd) / f"{session}.jsonl"
        self.write_lines(path, lines)

    def subagent(self, lines, session="s1"):
        base = self.config / "projects" / transcripts.encode_path(self.cwd) / session / "subagents"
        self.write_lines(base / "agent-1.jsonl", lines)

    @staticmethod
    def write_lines(path, lines):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")

    def sync(self, session=None):
        return ledger.sync(self.root, session)[1]


class Attribution(LedgerCase):
    def test_one_record_per_question_with_calls_in_the_right_one(self):
        self.transcript([human("q1", 0, self.cwd), call("m1", 5, self.cwd), tool_result(6, self.cwd),
                         call("m2", 7, self.cwd), human("q2", 20, self.cwd), call("m3", 25, self.cwd)])
        doc = self.sync()
        self.assertEqual([q["id"] for q in doc["questions"]], ["q1", "q2"])
        self.assertEqual([q["models"][0]["calls"] for q in doc["questions"]], [2, 1])

    def test_repeated_message_lines_count_once_and_keep_the_last_usage(self):
        self.transcript([human("q1", 0, self.cwd), call("m1", 1, self.cwd, usage={"output_tokens": 1}),
                         call("m1", 2, self.cwd, usage={"output_tokens": 100})])
        model = self.sync()["questions"][0]["models"][0]
        self.assertEqual((model["calls"], model["output_tokens"]), (1, 100))

    def test_subagent_calls_count_in_the_question_that_launched_them(self):
        self.transcript([human("q1", 0, self.cwd), human("q2", 50, self.cwd)])
        self.subagent([call("sub", 10, self.cwd)])
        doc = self.sync()
        self.assertEqual([len(q["models"]) for q in doc["questions"]], [1, 0])

    def test_totals_equal_the_sum_of_questions(self):
        self.transcript([human("q1", 0, self.cwd), call("m1", 1, self.cwd), human("q2", 9, self.cwd),
                         call("m2", 10, self.cwd)])
        doc = self.sync()
        self.assertEqual(doc["totals"]["questions"], 2)
        self.assertEqual(doc["totals"]["calls"], 2)
        self.assertAlmostEqual(doc["totals"]["usd"], sum(q["usd"] for q in doc["questions"]), places=4)

    def test_question_id_is_the_prompt_id_so_saved_records_are_not_duplicated(self):
        prompt = {**human("line-uuid", 0, self.cwd), "promptId": "prompt-1"}
        self.transcript([prompt, call("m1", 1, self.cwd)])
        (self.root / "ledger" / "usage.json").write_text(json.dumps({"questions": [
            {"id": "prompt-1", "session": "s1", "asked_at": stamp(0), "feature": "F0", "phase": "plan",
             "models": [], "usd": 0, "active_seconds": 0}]}), encoding="utf-8")
        doc = self.sync()
        self.assertEqual([q["id"] for q in doc["questions"]], ["prompt-1"])
        self.assertEqual(doc["questions"][0]["feature"], "F0")
        self.assertEqual(doc["totals"]["calls"], 1)

    def test_two_lines_of_one_prompt_are_one_question(self):
        first = {**human("u1", 0, self.cwd), "promptId": "p"}
        second = {**human("u2", 1, self.cwd), "promptId": "p"}
        self.transcript([first, second, call("m1", 2, self.cwd)])
        self.assertEqual(self.sync()["totals"]["questions"], 1)

    def test_calls_before_any_prompt_are_not_lost(self):
        self.transcript([call("m1", 1, self.cwd)], session="headless")
        self.assertEqual(self.sync()["questions"][0]["id"], "headless")

    def test_transcripts_without_origin_fall_back_to_typed_prompts(self):
        prompt = human("q1", 0, self.cwd)
        del prompt["origin"]
        self.transcript([prompt, tool_result(1, self.cwd), call("m1", 2, self.cwd)])
        self.assertEqual([q["id"] for q in self.sync()["questions"]], ["q1"])

    def test_a_resumed_copy_does_not_double_count(self):
        lines = [human("q1", 0, self.cwd), call("m1", 1, self.cwd)]
        self.transcript(lines, session="s1")
        self.transcript(lines, session="s2")
        self.assertEqual(self.sync()["totals"]["calls"], 1)


class ProjectScope(LedgerCase):
    def test_sibling_folder_with_same_prefix_is_excluded(self):
        other = self.cwd + "-other"
        self.transcript([human("q1", 0, self.cwd)])
        self.transcript([human("q2", 0, other), call("m9", 1, other)], session="s2", cwd=other)
        self.assertEqual([q["id"] for q in self.sync()["questions"]], ["q1"])

    def test_subdirectory_of_the_project_is_included(self):
        sub = self.cwd + "/packages/ui"
        self.transcript([human("q1", 0, sub), call("m1", 1, sub)], cwd=sub)
        self.assertEqual(self.sync()["totals"]["calls"], 1)

    def test_former_path_counts_only_after_alias(self):
        old = str(self.tmp / "old" / "app")
        self.transcript([human("q1", 0, old), call("m1", 1, old)], cwd=old)
        self.assertEqual(self.sync()["totals"]["questions"], 0)
        ledger.main(["--root", self.cwd, "alias", old + "/"])
        self.assertEqual(self.sync()["totals"]["questions"], 1)

    def test_git_worktree_elsewhere_is_included(self):
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        for args in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "x"],
                     ["worktree", "add", "-q", str(self.tmp / "tree"), "-b", "w"]):
            subprocess.run(["git", "-C", self.cwd, *args], check=True, env=env)
        tree = str(self.tmp / "tree")
        self.transcript([human("q1", 0, self.cwd)])
        self.transcript([human("q2", 0, tree), call("m1", 1, tree)], session="s2", cwd=tree)
        self.assertEqual(self.sync()["totals"]["questions"], 2)


class Cost(LedgerCase):
    def usd(self, model=OPUS, usage=None):
        self.transcript([human("q1", 0, self.cwd), call("m1", 1, self.cwd, model=model, usage=usage)])
        return self.sync()["questions"][0]["usd"]

    def test_opus_list_price(self):
        expected = (10 * 4 + 100 * 20 + 1000 * 0.2 + 200 * 8) / 1_000_000
        self.assertAlmostEqual(self.usd(), expected, places=4)

    def test_thinking_is_not_added_on_top_of_output(self):
        plain = self.usd(usage={"output_tokens_details": {}})
        self.assertAlmostEqual(plain, self.usd(), places=6)

    def test_haiku_tier_counts_cache_in_the_prompt(self):
        usage = {"input_tokens": 1, "output_tokens": 0, "cache_read_input_tokens": 100_000,
                 "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}
        self.assertAlmostEqual(self.usd("claude-haiku-5-5", usage), (0.5 + 100_000 * 0.05) / 1_000_000, places=4)

    def test_haiku_at_the_threshold_keeps_the_low_tier(self):
        usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 100_000,
                 "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}
        self.assertAlmostEqual(self.usd("claude-haiku-5-5", usage), 100_000 * 0.01 / 1_000_000, places=4)

    def test_fast_mode_doubles_opus(self):
        usage = {"input_tokens": 1_000_000, "speed": "fast"}
        expected = 2 * (4.0 + (100 * 20 + 1000 * 0.2 + 200 * 8) / 1_000_000)
        self.assertAlmostEqual(self.usd(usage=usage), expected, places=4)

    def test_us_inference_adds_ten_percent(self):
        self.assertAlmostEqual(self.usd(usage={"input_tokens": 1_000_000, "inference_geo": "us"}),
                               1.1 * (4.0 + (100 * 20 + 1000 * 0.2 + 200 * 8) / 1_000_000), places=4)

    def test_model_names_are_normalized_for_pricing(self):
        self.assertEqual(measure.normalize_model("claude-opus-5-5[1m]"), OPUS)
        self.assertEqual(measure.normalize_model("claude-haiku-4-5-20251001"), "claude-haiku-4-5")
        self.assertEqual(measure.normalize_model("us.anthropic.claude-opus-5-5-v1:0"), OPUS)

    def test_unknown_model_warns_and_invents_no_price(self):
        self.transcript([human("q1", 0, self.cwd), call("m1", 1, self.cwd, model="claude-new-9")])
        err = io.StringIO()
        with redirect_stderr(err):
            doc = self.sync()
        self.assertEqual(doc["questions"][0]["usd"], 0)
        self.assertIn("claude-new-9", err.getvalue())


class ActiveTime(LedgerCase):
    def test_turn_duration_wins_over_event_gaps(self):
        self.transcript([human("q1", 0, self.cwd), call("m1", 900, self.cwd), turn(901, 564491, self.cwd)])
        self.assertEqual(self.sync()["questions"][0]["active_seconds"], 564)

    def test_gaps_are_capped_without_turn_duration(self):
        self.transcript([human("q1", 0, self.cwd), call("m1", 10, self.cwd), call("m2", 1800, self.cwd)])
        self.assertEqual(self.sync()["questions"][0]["active_seconds"], 310)


class Persistence(LedgerCase):
    def test_record_survives_when_its_transcript_is_gone(self):
        self.transcript([human("q1", 0, self.cwd), call("m1", 1, self.cwd)])
        self.sync()
        self.transcript([human("q2", 0, self.cwd), call("m2", 1, self.cwd)], session="s1")
        self.assertEqual([q["id"] for q in self.sync()["questions"]], ["q1", "q2"])

    def test_a_shrunken_transcript_does_not_lower_a_saved_record(self):
        self.transcript([human("q1", 0, self.cwd), call("m1", 1, self.cwd), call("m2", 2, self.cwd)])
        self.sync()
        self.transcript([human("q1", 0, self.cwd), call("m1", 1, self.cwd)])
        self.assertEqual(self.sync()["totals"]["calls"], 2)

    def test_no_prompt_text_or_paths_reach_the_files(self):
        self.transcript([human("q1", 0, self.cwd), call("m1", 1, self.cwd)])
        self.sync()
        for name in ("ledger/usage.json", "LEDGER.md"):
            text = (self.root / name).read_text(encoding="utf-8")
            self.assertNotIn(SECRET, text)
            self.assertNotIn(self.cwd, text)

    def test_nothing_is_rewritten_when_nothing_changed(self):
        self.transcript([human("q1", 0, self.cwd), call("m1", 1, self.cwd)])
        self.sync()
        path = self.root / "ledger" / "usage.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["generated_at"] = "2000-01-01T00:00:00Z"
        path.write_text(json.dumps(doc), encoding="utf-8")
        self.sync()
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["generated_at"], "2000-01-01T00:00:00Z")

    def test_record_fields_stay_inside_schema_two(self):
        self.transcript([human("q1", 0, self.cwd), call("m1", 1, self.cwd)])
        doc = self.sync()
        record = doc["questions"][0]
        self.assertEqual(doc["schema"], 2)
        self.assertEqual(set(record), {"id", "session", "asked_at", "feature", "phase", "kind", "category", "models",
                                       "usd", "active_seconds"})
        self.assertEqual(set(record["models"][0]), {"model", "effort", "calls", "usd", *measure.TOKEN_FIELDS})


class Phases(LedgerCase):
    def test_latest_row_before_the_question_wins(self):
        ledger.main(["--root", self.cwd, "phase", "F1", "plan", "--at", stamp(0)])
        ledger.main(["--root", self.cwd, "phase", "F2", "build", "--at", stamp(30)])
        self.transcript([human("q1", 10, self.cwd), human("q2", 40, self.cwd)])
        doc = self.sync()
        self.assertEqual([(q["feature"], q["phase"]) for q in doc["questions"]], [("F1", "plan"), ("F2", "build")])

    def test_saved_attribution_stays_without_a_covering_row(self):
        self.transcript([human("q1", 0, self.cwd)])
        self.sync()
        path = self.root / "ledger" / "usage.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["questions"][0].update(feature="F0", phase="plan")
        path.write_text(json.dumps(doc), encoding="utf-8")
        self.assertEqual(self.sync()["questions"][0]["feature"], "F0")

    def test_question_with_no_phase_is_unassigned(self):
        self.transcript([human("q1", 0, self.cwd)])
        self.assertEqual(self.sync()["questions"][0]["feature"], common.UNASSIGNED)


class Kind(LedgerCase):
    def kinds(self):
        return [q["kind"] for q in self.sync()["questions"]]

    def test_a_turn_that_edits_files_is_work_and_one_that_only_reads_is_a_question(self):
        self.transcript([human("q1", 0, self.cwd), call("m1", 1, self.cwd, tools=["Read", "Edit"]),
                         human("q2", 10, self.cwd), call("m2", 11, self.cwd, tools=["Read", "Grep"])])
        self.assertEqual(self.kinds(), ["work", "question"])

    def test_an_edit_in_an_earlier_line_of_the_same_message_still_counts(self):
        self.transcript([human("q1", 0, self.cwd), call("m1", 1, self.cwd, tools=["Write"]),
                         call("m1", 2, self.cwd)])
        self.assertEqual(self.kinds(), ["work"])

    def test_a_subagent_edit_makes_the_question_work(self):
        self.transcript([human("q1", 0, self.cwd), call("m1", 1, self.cwd, tools=["Agent"])])
        self.subagent([call("sub", 5, self.cwd, tools=["Edit"])])
        self.assertEqual(self.kinds(), ["work"])

    def test_bash_alone_is_a_question(self):
        self.transcript([human("q1", 0, self.cwd), call("m1", 1, self.cwd, tools=["Bash"])])
        self.assertEqual(self.kinds(), ["question"])

    def test_a_saved_record_from_schema_one_reads_as_unknown(self):
        (self.root / "ledger" / "usage.json").write_text(json.dumps({"questions": [
            {"id": "old", "session": "s0", "asked_at": stamp(0), "feature": "F0", "phase": "plan",
             "models": [], "usd": 0, "active_seconds": 0}]}), encoding="utf-8")
        record = self.sync()["questions"][0]
        self.assertEqual((record["kind"], record["category"]), ("unknown", None))

    def test_tool_input_never_reaches_the_files(self):
        self.transcript([human("q1", 0, self.cwd), call("m1", 1, self.cwd, tools=["Edit"])])
        self.sync()
        for name in ("ledger/usage.json", "LEDGER.md"):
            self.assertNotIn(SECRET, (self.root / name).read_text(encoding="utf-8"))


class Categories(LedgerCase):
    def ledger(self, *args):
        return ledger.main(["--root", self.cwd, *args])

    def categories(self):
        return [q["category"] for q in self.sync()["questions"]]

    def test_a_category_lasts_until_the_next_category(self):
        self.ledger("category", "review", "--at", stamp(10))
        self.ledger("category", "tooling", "--at", stamp(30))
        self.transcript([human("q0", 0, self.cwd), human("q1", 20, self.cwd), human("q2", 40, self.cwd)])
        self.assertEqual(self.categories(), [None, "review", "tooling"])

    def test_a_phase_row_ends_the_category(self):
        self.ledger("category", "review", "--at", stamp(10))
        self.ledger("phase", "F1", "build", "--at", stamp(30))
        self.transcript([human("q1", 20, self.cwd), human("q2", 40, self.cwd)])
        self.assertEqual(self.categories(), ["review", None])

    def test_none_clears_the_category(self):
        self.ledger("category", "review", "--at", stamp(10))
        self.ledger("category", "none", "--at", stamp(30))
        self.transcript([human("q1", 20, self.cwd), human("q2", 40, self.cwd)])
        self.assertEqual(self.categories(), ["review", None])

    def test_saved_category_stays_without_a_covering_row(self):
        self.transcript([human("q1", 0, self.cwd)])
        self.sync()
        path = self.root / "ledger" / "usage.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["questions"][0]["category"] = "review"
        path.write_text(json.dumps(doc), encoding="utf-8")
        self.assertEqual(self.categories(), ["review"])

    def test_a_comma_is_rejected(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(self.ledger("category", "a,b"), 1)
        self.assertFalse((self.root / "ledger" / "categories.csv").exists())


class HookAndInit(LedgerCase):
    def run_hook(self, payload, cwd=None):
        return subprocess.run([sys.executable, str(SCRIPT), "hook"], input=payload, text=True,
                              capture_output=True, cwd=cwd or self.cwd,
                              env={**os.environ, "CLAUDE_CONFIG_DIR": str(self.config)})

    def test_hook_saves_only_its_own_session(self):
        (self.root / "ledger" / "usage.json").write_text("{}", encoding="utf-8")
        self.transcript([human("q1", 0, self.cwd), call("m1", 1, self.cwd)], session="s1")
        self.transcript([human("q2", 0, self.cwd), call("m2", 1, self.cwd)], session="s2")
        done = self.run_hook(json.dumps({"cwd": self.cwd + "/deep/dir", "session_id": "s2"}))
        self.assertEqual(done.returncode, 0)
        doc = json.loads((self.root / "ledger" / "usage.json").read_text(encoding="utf-8"))
        self.assertEqual([q["id"] for q in doc["questions"]], ["q2"])

    def test_hook_does_nothing_outside_a_ledger_project(self):
        outside = self.tmp / "plain"
        outside.mkdir()
        done = self.run_hook(json.dumps({"cwd": str(outside), "session_id": "s1"}), cwd=str(outside))
        self.assertEqual(done.returncode, 0)
        self.assertFalse((outside / "ledger").exists())

    def test_hook_never_blocks_on_bad_input(self):
        (self.root / "ledger" / "usage.json").write_text("not json", encoding="utf-8")
        self.assertEqual(self.run_hook("garbage").returncode, 0)
        self.assertEqual(self.run_hook(json.dumps({"cwd": self.cwd})).returncode, 0)

    def test_hook_warns_when_a_phase_was_set_after_the_prompt(self):
        (self.root / "ledger" / "usage.json").write_text("{}", encoding="utf-8")
        ledger.main(["--root", self.cwd, "phase", "F1", "plan", "--at", stamp(0)])
        self.transcript([human("q1", 10, self.cwd), call("m1", 11, self.cwd)])
        ledger.main(["--root", self.cwd, "phase", "F1", "build", "--at", stamp(12)])
        done = self.run_hook(json.dumps({"cwd": self.cwd, "session_id": "s1"}))
        message = json.loads(done.stdout)["systemMessage"]
        self.assertEqual(done.returncode, 0)
        self.assertIn("phase F1 build", message)
        self.assertIn("stays F1 plan", message)
        self.assertIn(f"--at {stamp(10)[:19]}Z", message)

    def test_hook_is_quiet_when_every_row_predates_the_prompt(self):
        (self.root / "ledger" / "usage.json").write_text("{}", encoding="utf-8")
        ledger.main(["--root", self.cwd, "phase", "F1", "plan", "--at", stamp(0)])
        ledger.main(["--root", self.cwd, "category", "review", "--at", stamp(5)])
        self.transcript([human("q1", 10, self.cwd), call("m1", 11, self.cwd)])
        done = self.run_hook(json.dumps({"cwd": self.cwd, "session_id": "s1"}))
        self.assertEqual(done.stdout, "")

    def test_hook_warns_about_a_late_category_too(self):
        (self.root / "ledger" / "usage.json").write_text("{}", encoding="utf-8")
        self.transcript([human("q1", 10, self.cwd), call("m1", 11, self.cwd)])
        ledger.main(["--root", self.cwd, "category", "review", "--at", stamp(12)])
        done = self.run_hook(json.dumps({"cwd": self.cwd, "session_id": "s1"}))
        self.assertIn("category review", json.loads(done.stdout)["systemMessage"])

    def test_init_leaves_settings_alone_because_the_plugin_owns_the_hook(self):
        ledger.main(["--root", self.cwd, "init"])
        self.assertTrue((self.root / "ledger" / "phases.csv").exists())
        self.assertFalse((self.root / ".claude").exists())

    def test_init_shared_enables_the_plugin_keeps_settings_and_is_idempotent(self):
        settings = self.root / ".claude" / "settings.json"
        settings.parent.mkdir()
        settings.write_text('{"permissions": {"allow": ["Bash(go version *)"]}}', encoding="utf-8")
        for _ in range(2):
            ledger.main(["--root", self.cwd, "init", "--shared"])
        data = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual(data["permissions"]["allow"], ["Bash(go version *)"])
        self.assertEqual(data["enabledPlugins"], {ledger.PLUGIN_ID: True})
        source = data["extraKnownMarketplaces"][ledger.MARKETPLACE]["source"]
        self.assertEqual(source, {"source": "github", "repo": ledger.MARKETPLACE_REPO})
        self.assertNotIn("hooks", data)



class Board(LedgerCase):
    def board(self):
        out = io.StringIO()
        with redirect_stdout(out):
            ledger.main(["--root", self.cwd, "report"])
        return out.getvalue()

    def test_features_lead_with_their_phases_most_expensive_first(self):
        ledger.main(["--root", self.cwd, "phase", "cheap", "plan", "--at", stamp(0)])
        ledger.main(["--root", self.cwd, "phase", "big", "build", "--at", stamp(30)])
        self.transcript([human("q1", 10, self.cwd), call("m1", 11, self.cwd),
                         human("q2", 40, self.cwd), call("m2", 41, self.cwd), call("m3", 42, self.cwd)])
        self.sync()
        lines = self.board().split("\n\n")[1].splitlines()[1:]
        self.assertEqual([line.split()[0] for line in lines], ["big", "build", "question", "cheap", "plan", "question"])

    def test_board_splits_each_phase_by_kind_and_category(self):
        ledger.main(["--root", self.cwd, "phase", "F1", "build", "--at", stamp(0)])
        ledger.main(["--root", self.cwd, "category", "review", "--at", stamp(20)])
        self.transcript([human("q1", 10, self.cwd), call("m1", 11, self.cwd, tools=["Edit"]),
                         human("q2", 30, self.cwd), call("m2", 31, self.cwd)])
        self.sync()
        text = self.board()
        self.assertIn("    work ", text)
        self.assertIn("    question/review ", text)
        kinds = text.split("\n\n")[2].splitlines()
        self.assertEqual(kinds[0].split()[0:3], ["Kind", "/", "category"])
        self.assertEqual(sorted(line.split()[0] for line in kinds[1:]), ["question/review", "work"])
        ledger_md = (self.root / "LEDGER.md").read_text(encoding="utf-8")
        self.assertIn("| F1 | build | question/review |", ledger_md)

    def test_board_totals_match_the_ledger_and_hold_no_prompt_text(self):
        self.transcript([human("q1", 0, self.cwd), call("m1", 1, self.cwd)])
        doc = self.sync()
        text = self.board()
        self.assertIn(f"{doc['totals']['usd']:.2f} USD", text.splitlines()[0])
        self.assertIn("100%", text)
        self.assertNotIn(SECRET, text)

    def test_empty_ledger_says_so(self):
        self.sync()
        self.assertIn("No questions recorded yet.", self.board())


if __name__ == "__main__":
    unittest.main()
