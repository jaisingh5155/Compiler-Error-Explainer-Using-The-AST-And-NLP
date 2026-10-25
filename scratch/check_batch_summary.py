import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

from batch_runner import run_batch

res = run_batch(os.path.join(REPO_ROOT, "benchmark"), apply=False, max_workers=4)
print("BATCH SUMMARY:")
for k, v in res.summary.items():
    print(f"  {k}: {v}")
