"""
tests/week9_verification/test_feedback_store.py
────────────────────────────────────────────────
Week 9 Part 5 — Verification suite for the feedback store.

V1  Atomic write resilience (simulated crash).
V2  Unreviewed feedback exclusion from --include-feedback.
V3  Deduplication at merge time.
V4  Test-set leakage guard (message-level, case-insensitive).
V5  Silent write-back audit (grep-equivalent in code).
"""

import json
import os
import sys
import shutil
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "src"))

import feedback_store as fs
from train_classifier_v2 import load_reviewed_feedback, merge_feedback_into_train


def _make_diag(msg, cat="type_error"):
    return {"message": msg, "category": cat, "confidence": 0.85, "line": 10}


def _write_n(feedback_file, n, cat="type_error"):
    for i in range(n):
        fs.record_feedback(_make_diag(f"error message {i}"), cat, feedback_file=feedback_file)


# ── V1: Atomic write resilience ─────────────────────────────────────────────

class TestAtomicWrite(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.fb = os.path.join(self.d, "confirmed_feedback.json")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_valid_json_after_appends(self):
        for i in range(10):
            fs.record_feedback(_make_diag(f"msg {i}"), "type_error", feedback_file=self.fb)
        with open(self.fb) as f:
            data = json.load(f)
        self.assertEqual(len(data), 10)

    def test_no_orphaned_tmp_files(self):
        _write_n(self.fb, 5)
        tmps = [x for x in os.listdir(self.d) if x.startswith("feedback_") and x.endswith(".tmp")]
        self.assertEqual(tmps, [])

    def test_simulated_crash_leaves_original_intact(self):
        _write_n(self.fb, 3)
        original = fs.load_feedback(self.fb)
        self.assertEqual(len(original), 3)

        real_replace = os.replace
        def _crash(src, dst):
            raise OSError("Simulated crash during atomic rename")
        os.replace = _crash
        try:
            with self.assertRaises(OSError):
                fs.record_feedback(_make_diag("new"), "syntax_error", feedback_file=self.fb)
        finally:
            os.replace = real_replace

        surviving = fs.load_feedback(self.fb)
        self.assertEqual(len(surviving), 3,
                         "Original file corrupted by simulated crash")

    def test_tmp_cleaned_up_on_failure(self):
        real_replace = os.replace
        def _crash(src, dst):
            raise OSError("Simulated crash")
        os.replace = _crash
        try:
            with self.assertRaises(OSError):
                fs.save_feedback_atomic([{"test": 1}], self.fb)
        finally:
            os.replace = real_replace
        tmps = [x for x in os.listdir(self.d) if x.endswith(".tmp")]
        self.assertEqual(tmps, [])


    def test_simulated_crash_during_fsync_leaves_original_intact(self):
        """Second crash scenario: failure during fsync before file rename."""
        _write_n(self.fb, 3)
        original = fs.load_feedback(self.fb)
        self.assertEqual(len(original), 3)

        real_fsync = os.fsync
        def _crash(fd):
            raise OSError("Simulated crash during fsync before rename")
        os.fsync = _crash
        try:
            with self.assertRaises(OSError):
                fs.record_feedback(_make_diag("fsync_crash_test"), "syntax_error", feedback_file=self.fb)
        finally:
            os.fsync = real_fsync

        surviving = fs.load_feedback(self.fb)
        self.assertEqual(len(surviving), 3,
                         "Original file corrupted by simulated fsync crash")
        tmps = [x for x in os.listdir(self.d) if x.endswith(".tmp")]
        self.assertEqual(tmps, [], "Orphaned tmp file left behind after fsync failure")


# ── V2: Unreviewed exclusion ─────────────────────────────────────────────────

class TestUnreviewedExclusion(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.fb = os.path.join(self.d, "confirmed_feedback.json")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_only_reviewed_returned(self):
        _write_n(self.fb, 5)
        fs.mark_feedback_reviewed([1, 3], approved=True, feedback_file=self.fb)
        reviewed = load_reviewed_feedback(self.fb)
        self.assertEqual(len(reviewed), 2)
        self.assertTrue(all(r["reviewed_for_merge"] for r in reviewed))

    def test_category_present_but_unreviewed_excluded(self):
        """confirmed_category alone is not enough — needs reviewed_for_merge=True."""
        fs.record_feedback(_make_diag("special error"), "missing_include", feedback_file=self.fb)
        records = fs.load_feedback(self.fb)
        self.assertFalse(records[0]["reviewed_for_merge"])
        reviewed = load_reviewed_feedback(self.fb)
        self.assertEqual(len(reviewed), 0)

    def test_approve_then_reject_correct(self):
        _write_n(self.fb, 3)
        fs.mark_feedback_reviewed([0, 1], approved=True, feedback_file=self.fb)
        fs.mark_feedback_reviewed([0], approved=False, feedback_file=self.fb)
        reviewed = load_reviewed_feedback(self.fb)
        self.assertEqual(len(reviewed), 1)


# ── V3: Deduplication ───────────────────────────────────────────────────────

class TestDeduplication(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.fb = os.path.join(self.d, "confirmed_feedback.json")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_same_message_twice_merges_once(self):
        msg = "use of undeclared identifier 'x'"
        for _ in range(2):
            fs.record_feedback(_make_diag(msg), "name_resolution", feedback_file=self.fb)
        fs.mark_feedback_reviewed([0, 1], approved=True, feedback_file=self.fb)
        merged, stats = merge_feedback_into_train([], [], feedback_file=self.fb, verbose=False)
        self.assertEqual(stats["merged"], 1)
        self.assertEqual(stats["skipped_train_duplicate"], 1)

    def test_already_in_train_deduped(self):
        msg = "no matching function for call to 'foo'"
        existing = [{"message": msg, "category": "type_error", "split": "train",
                     "provenance": "codenet_dedup", "ast_node": "", "ast_fallback": None,
                     "symbol_signal": "unknown"}]
        fs.record_feedback(_make_diag(msg), "type_error", feedback_file=self.fb)
        fs.mark_feedback_reviewed([0], approved=True, feedback_file=self.fb)
        merged, stats = merge_feedback_into_train(existing, [], feedback_file=self.fb, verbose=False)
        self.assertEqual(stats["skipped_train_duplicate"], 1)
        self.assertEqual(stats["merged"], 0)
        self.assertEqual(len(merged), len(existing))


# ── V4: Test-set leakage guard ───────────────────────────────────────────────

class TestLeakageGuard(unittest.TestCase):
    """
    Policy: Program/file-identity-based exclusion consistent with Week 6 program splits.
    If feedback diagnostic originates from any program in the test split, it is blocked.
    If originating from a DIFFERENT program with coincidentally identical message text,
    it is NOT falsely excluded.
    """

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.fb = os.path.join(self.d, "confirmed_feedback.json")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_different_programs_same_message_not_excluded(self):
        """
        Two DIFFERENT programs producing the same error message text:
        One in test split, one submitted via feedback for train.
        Confirm the corrected guard does NOT falsely exclude the train one.
        """
        shared_msg = "expected ';' at end of declaration"
        test_rows = [{
            "message": shared_msg,
            "category": "syntax",
            "split": "test",
            "program_id": "prog_test_submission_999",
            "template_id": "prog_test_submission_999",
        }]
        # Feedback from a distinct program
        fs.record_feedback(
            {"message": shared_msg, "program_id": "prog_train_submission_111"},
            "syntax",
            feedback_file=self.fb
        )
        fs.mark_feedback_reviewed([0], approved=True, feedback_file=self.fb)

        merged, stats = merge_feedback_into_train([], test_rows, feedback_file=self.fb, verbose=False)
        self.assertEqual(stats["skipped_test_leakage"], 0,
                         "Corrected guard falsely excluded train feedback from different program")
        self.assertEqual(stats["merged"], 1)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["message"], shared_msg)

    def test_same_program_in_test_is_excluded(self):
        """
        Feedback from a program that belongs to the test split must be blocked
        even if the message is novel.
        """
        test_rows = [{
            "message": "original error",
            "category": "syntax",
            "split": "test",
            "program_id": "prog_test_submission_999",
        }]
        fs.record_feedback(
            {"message": "novel error from same program", "program_id": "prog_test_submission_999"},
            "syntax",
            feedback_file=self.fb
        )
        fs.mark_feedback_reviewed([0], approved=True, feedback_file=self.fb)

        merged, stats = merge_feedback_into_train([], test_rows, feedback_file=self.fb, verbose=False)
        self.assertEqual(stats["skipped_test_leakage"], 1,
                         "Guard failed to block feedback originating from test program")
        self.assertEqual(stats["merged"], 0)

    def test_test_message_blocked_untracked_fallback(self):
        """When program_id is untracked, fallback to message-level check blocks test message."""
        leaky = "expected ';' after expression"
        safe  = "undeclared variable 'y'"
        for msg in [leaky, safe]:
            fs.record_feedback(_make_diag(msg), "syntax_error", feedback_file=self.fb)
        fs.mark_feedback_reviewed([0, 1], approved=True, feedback_file=self.fb)
        test_rows = [{"message": leaky, "category": "syntax_error", "split": "test"}]
        merged, stats = merge_feedback_into_train([], test_rows, feedback_file=self.fb, verbose=False)
        self.assertEqual(stats["skipped_test_leakage"], 1)
        self.assertEqual(stats["merged"], 1)
        self.assertNotIn(leaky, [r["message"] for r in merged])
        self.assertIn(safe, [r["message"] for r in merged])

    def test_safe_message_passes(self):
        fs.record_feedback(_make_diag("unique feedback only"), "type_error", feedback_file=self.fb)
        fs.mark_feedback_reviewed([0], approved=True, feedback_file=self.fb)
        test_rows = [{"message": "different test message", "split": "test", "category": "syntax_error"}]
        merged, stats = merge_feedback_into_train([], test_rows, feedback_file=self.fb, verbose=False)
        self.assertEqual(stats["merged"], 1)
        self.assertEqual(stats["skipped_test_leakage"], 0)


# ── V5: Silent write-back audit ──────────────────────────────────────────────

class TestSilentWriteBackAudit(unittest.TestCase):

    DEDICATED = frozenset({
        "build_dataset_from_tests.py", "prepare_training_data.py",
        "train_classifier_v2.py", "feedback_store.py",
    })

    def _violations(self):
        import re, glob
        hits = []
        for path in glob.glob(os.path.join(_ROOT, "src", "*.py")):
            if os.path.basename(path) in self.DEDICATED:
                continue
            with open(path, errors="ignore") as f:
                lines = f.readlines()
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if (re.search(r"open\s*\(.*training_data", line)
                        and re.search(r'''["'][wa]["']''', line)):
                    hits.append((os.path.basename(path), i, line.rstrip()))
                if "json.dump" in line and "training_data" in line:
                    hits.append((os.path.basename(path), i, line.rstrip()))
        return hits

    def test_no_write_violations(self):
        v = self._violations()
        self.assertEqual(v, [],
            "Silent write-back violations:\n" + "\n".join(f"  {f}:{l}: {ln}" for f,l,ln in v))

    def test_dataset_logger_gated(self):
        p = os.path.join(_ROOT, "src", "dataset_logger.py")
        if not os.path.exists(p):
            self.skipTest("dataset_logger.py not present")
        self.assertIn("ENABLE_DATASET_LOGGING", open(p).read())

    def test_main_requires_opt_in(self):
        p = os.path.join(_ROOT, "src", "main.py")
        if not os.path.exists(p):
            self.skipTest("main.py not present")
        self.assertIn("--log-training", open(p).read())

    def test_gui_no_training_data_write(self):
        p = os.path.join(_ROOT, "src", "gui.py")
        if not os.path.exists(p):
            self.skipTest("gui.py not present")
        content = open(p).read()
        self.assertIn("record_feedback", content)
        for i, line in enumerate(content.splitlines(), 1):
            if "json.dump" in line and "training_data" in line:
                self.fail(f"gui.py:{i}: {line.strip()}")


# ── CLI helper smoke tests ────────────────────────────────────────────────────

class TestCLIHelper(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.fb = os.path.join(self.d, "fb.json")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_list_unreviewed_count(self):
        _write_n(self.fb, 4)
        fs.mark_feedback_reviewed([0], approved=True, feedback_file=self.fb)
        unreviewed = fs.list_unreviewed_feedback(self.fb)
        self.assertEqual(len(unreviewed), 3)

    def test_approve_all(self):
        _write_n(self.fb, 5)
        count = fs.approve_all_feedback(self.fb)
        self.assertEqual(count, 5)
        self.assertEqual(len(load_reviewed_feedback(self.fb)), 5)

    def test_approve_all_idempotent(self):
        _write_n(self.fb, 3)
        fs.approve_all_feedback(self.fb)
        self.assertEqual(fs.approve_all_feedback(self.fb), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
