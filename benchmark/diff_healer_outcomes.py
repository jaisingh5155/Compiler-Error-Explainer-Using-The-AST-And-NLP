#!/usr/bin/env python3
"""
diff_healer_outcomes.py
───────────────────────
Compares heal_outcome between BENCHMARK_RESULTS_WEEK7.csv and BENCHMARK_RESULTS_WEEK8.csv
and prints every file whose outcome changed.
"""
import csv
import os
import sys

BENCHMARK_DIR = os.path.dirname(os.path.abspath(__file__))
WEEK7_CSV = os.path.join(BENCHMARK_DIR, "BENCHMARK_RESULTS_WEEK7.csv")
WEEK8_CSV = os.path.join(BENCHMARK_DIR, "BENCHMARK_RESULTS_WEEK8.csv")

def read_outcomes(csv_path):
    outcomes = {}
    with open(csv_path, mode="r", newline="") as f:
        reader = csv.reader(f)
        header = None
        for row in reader:
            if not row or row[0].startswith("#"):
                continue
            if header is None:
                header = row
                filepath_idx = header.index("filepath")
                heal_idx = header.index("heal_outcome")
                continue
            if len(row) > max(filepath_idx, heal_idx):
                outcomes[row[filepath_idx]] = row[heal_idx]
    return outcomes

def main():
    w7 = read_outcomes(WEEK7_CSV)
    w8 = read_outcomes(WEEK8_CSV)

    all_keys = sorted(set(w7.keys()) | set(w8.keys()))
    diffs = []
    for k in all_keys:
        o7 = w7.get(k, "<missing>")
        o8 = w8.get(k, "<missing>")
        if o7 != o8:
            diffs.append((k, o7, o8))

    print(f"Total files compared: {len(all_keys)}")
    print(f"Files with changed heal_outcome: {len(diffs)}\n")
    print(f"{'Filepath':<55} | {'Week 7':<18} | {'Week 8':<18}")
    print("-" * 97)
    for k, o7, o8 in diffs:
        print(f"{k:<55} | {o7:<18} | {o8:<18}")

if __name__ == "__main__":
    main()
