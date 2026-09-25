#!/usr/bin/env python3
"""
Regression Test: Bug 7.1 - Training data self-contamination.
Ensures:
  1. Default CLI / benchmark runs DO NOT modify data/training_data.json.
  2. Opt-in logging via ENABLE_DATASET_LOGGING=1 or --log-training DOES log to the dataset.
  3. Restores pristine baseline after testing.
"""
import sys
import os
import hashlib
import tempfile
import subprocess
import shutil

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(project_root, "src"))

td_path = os.path.join(project_root, "data", "training_data.json")
pristine_path = os.path.join(project_root, "legacy_artifacts", "training_data_pristine_week1.json")

from dataset_logger import log_example
from models import CompilerError

def get_file_info(path):
    size = os.path.getsize(path)
    md5 = hashlib.md5(open(path, "rb").read()).hexdigest()
    return size, md5

def test_leak_prevention_and_opt_in():
    # Ensure starting from pristine
    shutil.copyfile(pristine_path, td_path)
    initial_size, initial_md5 = get_file_info(td_path)
    print(f"[Bug 7.1 Test] Initial training_data.json size={initial_size}, MD5={initial_md5}")

    test_source = """
int main() {
    int x = 5;
    return 0;
}
"""
    with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False) as f:
        f.write(test_source)
        f_path = f.name

    try:
        # 1. Run 3 passes with default settings (gate OFF) via CLI
        for i in range(1, 4):
            env = os.environ.copy()
            env.pop("ENABLE_DATASET_LOGGING", None)
            proc = subprocess.run(
                [sys.executable, "src/main.py", "benchmark/syntax/sx01_missing_semi_decl.cpp", "-j"],
                capture_output=True,
                text=True,
                cwd=project_root,
                env=env
            )
            size_after, md5_after = get_file_info(td_path)
            assert size_after == initial_size, f"Run {i}: File size changed from {initial_size} to {size_after}"
            assert md5_after == initial_md5, f"Run {i}: MD5 changed from {initial_md5} to {md5_after}"

        print("[Bug 7.1 Test] 3 default runs completed: file remained 100% UNCHANGED.")

        # 2. Test opt-in path: ENABLE_DATASET_LOGGING=1
        err_env = CompilerError(file="test.cpp", line=10, column=5, error_type="error",
                                message="unique_novel_verification_error_cwe_test_xyz", raw="")
        os.environ["ENABLE_DATASET_LOGGING"] = "1"
        log_example(err_env, enabled=False)
        opt_size, opt_md5 = get_file_info(td_path)
        print(f"[Bug 7.1 Test] Opt-in run with ENABLE_DATASET_LOGGING=1: size={opt_size}, MD5={opt_md5}")
        assert opt_size > initial_size and opt_md5 != initial_md5, "Opt-in logging via env failed to append!"

        # 3. Test opt-in flag: enabled=True (--log-training path)
        shutil.copyfile(pristine_path, td_path)
        os.environ.pop("ENABLE_DATASET_LOGGING", None)
        err_flag = CompilerError(file="test.cpp", line=20, column=5, error_type="error",
                                 message="another_unique_novel_verification_error_abc", raw="")
        log_example(err_flag, enabled=True)
        flag_size, flag_md5 = get_file_info(td_path)
        print(f"[Bug 7.1 Test] Opt-in run with enabled=True: size={flag_size}, MD5={flag_md5}")
        assert flag_size > initial_size and flag_md5 != initial_md5, "Opt-in logging via enabled=True failed to append!"

        print("✓ Bug 7.1 Regression Test PASSED.")
    finally:
        # Always restore pristine baseline
        shutil.copyfile(pristine_path, td_path)
        if os.path.exists(f_path):
            os.remove(f_path)

if __name__ == "__main__":
    test_leak_prevention_and_opt_in()
