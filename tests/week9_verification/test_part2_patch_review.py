import os
import sys
import shutil
import tempfile
import pytest

# Ensure repo root and src/ are in sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_DIR = os.path.join(REPO_ROOT, "src")
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from patch_review import PatchReviewSession, ReviewablePatch, PatchStatus, InvalidTransitionError
from diagnostic import Patch, Diagnostic, VerifyResult
from planner import Planner, run_planner


def test_state_machine_transitions():
    """Verify valid transitions (pending -> accepted/rejected, undo) and rejection of illegal ones."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_file = os.path.join(tmpdir, "test.cpp")
        orig_content = "int main() { return 0; }\n"
        with open(tmp_file, "w") as f:
            f.write(orig_content)

        patch1 = Patch(
            original_file=tmp_file,
            patched_source="int main() { return 1; }\n",
            safety_level="S0",
        )
        patch1.gate_results = [{"gate": "gate1_recompile", "passed": True}]
        patch1.verify_result = VerifyResult(passed=True)

        patch2 = Patch(
            original_file=tmp_file,
            patched_source="int main() { return 2; }\n",
            safety_level="S0",
        )
        patch2.gate_results = [{"gate": "gate1_recompile", "passed": True}]
        patch2.verify_result = VerifyResult(passed=True)

        session = PatchReviewSession(tmp_file, [patch1, patch2])
        rp1 = session.get_patch(1)
        rp2 = session.get_patch(2)

        assert rp1.status == PatchStatus.PENDING
        assert rp2.status == PatchStatus.PENDING

        # Valid accept
        session.accept(1)
        assert rp1.status == PatchStatus.ACCEPTED
        with open(tmp_file) as f:
            assert f.read() == "int main() { return 1; }\n"

        # Illegal: accepting already accepted patch
        with pytest.raises(InvalidTransitionError):
            session.accept(1)

        # Illegal: rejecting accepted patch
        with pytest.raises(InvalidTransitionError):
            session.reject(1)

        # Valid reject on pending patch 2
        session.reject(2)
        assert rp2.status == PatchStatus.REJECTED

        # Illegal: accepting rejected patch
        with pytest.raises(InvalidTransitionError):
            session.accept(2)

        # Illegal: rejecting already rejected patch
        with pytest.raises(InvalidTransitionError):
            session.reject(2)

        # Undo on accepted patch 1
        undone = session.undo()
        assert undone.patch_id == 1
        assert rp1.status == PatchStatus.PENDING
        with open(tmp_file) as f:
            assert f.read() == orig_content

        # Illegal: undo when stack is now empty
        with pytest.raises(IndexError):
            session.undo()


def test_cannot_accept_s2_or_gate_failed():
    """Safety invariant: Gate-failed patches must never be accepted, while verified S2 can be explicitly accepted in review fixes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_file = os.path.join(tmpdir, "safety.cpp")
        with open(tmp_file, "w") as f:
            f.write("void f();\n")

        # Verified S2 patch
        s2_patch = Patch(
            original_file=tmp_file,
            patched_source="void f() { int x = 0; }\n",
            safety_level="S2",
        )
        s2_patch.gate_results = [{"gate": "gate1_recompile", "passed": True}]
        s2_patch.verify_result = VerifyResult(passed=True)

        # Gate-failed patch
        fail_patch = Patch(
            original_file=tmp_file,
            patched_source="void f() { return 42; }\n",
            safety_level="S0",
        )
        fail_patch.gate_results = [{"gate": "gate1_recompile", "passed": False, "reason": "type error"}]
        fail_patch.verify_result = VerifyResult(passed=False, failing_gate="gate1_recompile")

        session = PatchReviewSession(tmp_file, [s2_patch, fail_patch])
        rp_s2 = session.get_patch(1)
        rp_fail = session.get_patch(2)

        # Precondition check: verified S2 can now be explicitly accepted by user in review fixes
        can_s2, reason_s2 = rp_s2.can_accept()
        assert can_s2

        # Gate-failed patch cannot be accepted
        can_fail, reason_fail = rp_fail.can_accept()
        assert not can_fail
        assert "gate" in reason_fail.lower()

        # Accepting verified S2 writes to disk
        session.accept(1)
        assert rp_s2.status == PatchStatus.ACCEPTED
        with open(tmp_file) as f:
            assert "int x = 0;" in f.read()

        # Enforced transition failure on gate-failed patch
        with pytest.raises(InvalidTransitionError, match="gate"):
            session.accept(2)


def test_reject_leaves_file_untouched():
    """Rejecting a patch must leave the source file on disk 100% byte-for-byte identical."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_file = os.path.join(tmpdir, "untouched.cpp")
        initial_bytes = b"// Original file content\nint a = 10;\n"
        with open(tmp_file, "wb") as f:
            f.write(initial_bytes)

        patch = Patch(
            original_file=tmp_file,
            patched_source="// Patched\nint a = 20;\n",
            safety_level="S0",
        )
        patch.verify_result = VerifyResult(passed=True)

        session = PatchReviewSession(tmp_file, [patch])
        session.reject(1)

        assert session.get_patch(1).status == PatchStatus.REJECTED
        with open(tmp_file, "rb") as f:
            assert f.read() == initial_bytes


def test_undo_restores_exact_bytes_after_1_and_3_patches():
    """Undo must restore exact pre-patch bytes after 1 and after 3 accepted patches in LIFO order."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_file = os.path.join(tmpdir, "multi_undo.cpp")
        bytes_v0 = b"int a = 0;\n"
        bytes_v1 = b"int a = 10;\n"
        bytes_v2 = b"int a = 10;\nint b = 20;\n"
        bytes_v3 = b"int a = 10;\nint b = 20;\nint c = 30;\n"

        with open(tmp_file, "wb") as f:
            f.write(bytes_v0)

        p1 = Patch(original_file=tmp_file, patched_source=bytes_v1.decode("utf-8"), safety_level="S0")
        p1.verify_result = VerifyResult(passed=True)

        p2 = Patch(original_file=tmp_file, patched_source=bytes_v2.decode("utf-8"), safety_level="S0")
        p2.verify_result = VerifyResult(passed=True)

        p3 = Patch(original_file=tmp_file, patched_source=bytes_v3.decode("utf-8"), safety_level="S0")
        p3.verify_result = VerifyResult(passed=True)

        # Test single accept & undo
        session1 = PatchReviewSession(tmp_file, [p1])
        session1.accept(1)
        with open(tmp_file, "rb") as f:
            assert f.read() == bytes_v1

        session1.undo()
        with open(tmp_file, "rb") as f:
            assert f.read() == bytes_v0

        # Test sequence of 3 accepted patches and 3 undos
        session3 = PatchReviewSession(tmp_file, [p1, p2, p3])
        session3.accept(1)
        with open(tmp_file, "rb") as f:
            assert f.read() == bytes_v1

        session3.accept(2)
        with open(tmp_file, "rb") as f:
            assert f.read() == bytes_v2

        session3.accept(3)
        with open(tmp_file, "rb") as f:
            assert f.read() == bytes_v3

        # LIFO Undo 3
        session3.undo()
        with open(tmp_file, "rb") as f:
            assert f.read() == bytes_v2
        assert session3.get_patch(3).status == PatchStatus.PENDING

        # LIFO Undo 2
        session3.undo()
        with open(tmp_file, "rb") as f:
            assert f.read() == bytes_v1
        assert session3.get_patch(2).status == PatchStatus.PENDING

        # LIFO Undo 1
        session3.undo()
        with open(tmp_file, "rb") as f:
            assert f.read() == bytes_v0
        assert session3.get_patch(1).status == PatchStatus.PENDING


def test_review_mode_benchmark_parity():
    """Verify review_mode yields identical proposed patches to auto mode while leaving file untouched."""
    test_files = [
        os.path.join(REPO_ROOT, "benchmark", "name_resolution", "nr04_keyword_cosnt.cpp"),
        os.path.join(REPO_ROOT, "benchmark", "syntax", "sx01_missing_semi_decl.cpp"),
        os.path.join(REPO_ROOT, "benchmark", "multi_error", "me06_cascade_semicolons.cpp"),
    ]

    for src_file in test_files:
        assert os.path.exists(src_file), f"Benchmark file missing: {src_file}"

        with tempfile.TemporaryDirectory() as tmpdir:
            file_auto = os.path.join(tmpdir, "auto_" + os.path.basename(src_file))
            file_review = os.path.join(tmpdir, "review_" + os.path.basename(src_file))

            shutil.copyfile(src_file, file_auto)
            shutil.copyfile(src_file, file_review)

            with open(src_file, "rb") as f:
                orig_bytes = f.read()

            res_auto = run_planner(file_auto, review_mode=False, apply_to_disk=True)
            res_review = run_planner(file_review, review_mode=True)

            # In review mode, file must remain completely untouched on disk
            with open(file_review, "rb") as f:
                review_disk_bytes = f.read()
            assert review_disk_bytes == orig_bytes, f"Review mode altered file on disk: {src_file}"

            # Both runs report same final status
            assert res_auto.status == res_review.status

            # Compare proposed patches
            auto_patches = [p.patched_source for p in res_auto.patches_applied]
            review_patches = [p.patched_source for p in res_review.pending_patches]

            assert len(auto_patches) == len(review_patches), (
                f"Patch count mismatch for {src_file}: auto={len(auto_patches)}, review={len(review_patches)}"
            )
            assert auto_patches == review_patches, f"Proposed patch content differs for {src_file}"


def test_gui_offscreen_review_page_smoke():
    """Construct PatchReviewPage and AppGUI in offscreen Qt mode to confirm no crashes."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    try:
        from PyQt6.QtWidgets import QApplication
        import gui
    except (ImportError, Exception) as e:
        pytest.skip(f"PyQt6 not available: {e}")

    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_target = os.path.join(tmpdir, "review_gui.cpp")
        with open(tmp_target, "w") as f:
            f.write("int x = 1;\n")

        p_safe = Patch(original_file=tmp_target, patched_source="int x = 10;\n", safety_level="S0")
        p_safe.verify_result = VerifyResult(passed=True)

        p_s2 = Patch(original_file=tmp_target, patched_source="int x = 20;\n", safety_level="S2")
        p_s2.verify_result = VerifyResult(passed=True)

        page = gui.PatchReviewPage(file_path_getter=lambda: tmp_target)
        page.load_patches(tmp_target, [p_safe, p_s2])

        assert len(page.card_widgets) == 2
        card0 = page.card_widgets[0]
        card1 = page.card_widgets[1]

        # Card 0 (S0, verified) can be accepted
        assert card0.btn_accept.isEnabled()

        # Under universal review, verified S2 patches also require user review and can be accepted
        assert card1.btn_accept.isEnabled()

        # Accept card 0
        card0.btn_accept.click()
        assert not card0.btn_accept.isEnabled()
        assert card0.btn_undo.isEnabled()

        # Undo card 0
        card0.btn_undo.click()
        assert card0.btn_accept.isEnabled()
        assert not card0.btn_undo.isEnabled()

        # Full GUI smoke test
        win = gui.AppGUI()
        assert hasattr(win, "review_page")
        assert hasattr(win, "btn_review")
        win.switch_to_review()
        assert win.stack.currentIndex() == 7
