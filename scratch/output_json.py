import sys
import os
import json
import difflib

orig_file = 'test_heal.cpp'
healed_file = 'scratch/healed_test_heal.cpp'

with open(orig_file, 'r') as f:
    original_lines = f.read().splitlines()
with open(healed_file, 'r') as f:
    healed_lines = f.read().splitlines()

# Simple line-by-line diff tracking
original_out = []
healed_out = []
summary = {"errors": 0, "fixed": 0, "inserted": 0, "deleted": 0}

matcher = difflib.SequenceMatcher(None, original_lines, healed_lines)

for tag, i1, i2, j1, j2 in matcher.get_opcodes():
    if tag == 'equal':
        for i in range(i1, i2):
            original_out.append({"n": i + 1, "text": original_lines[i], "highlight": "none"})
            healed_out.append({"n": j1 + (i - i1) + 1, "text": healed_lines[j1 + (i - i1)], "highlight": "none"})
    elif tag == 'replace':
        for i in range(i1, i2):
            original_out.append({"n": i + 1, "text": original_lines[i], "highlight": "error"})
            summary["errors"] += 1
        for j in range(j1, j2):
            healed_out.append({"n": j + 1, "text": healed_lines[j], "highlight": "fixed"})
            summary["fixed"] += 1
    elif tag == 'insert':
        for j in range(j1, j2):
            healed_out.append({"n": j + 1, "text": healed_lines[j], "highlight": "inserted"})
            summary["inserted"] += 1
    elif tag == 'delete':
        for i in range(i1, i2):
            original_out.append({"n": i + 1, "text": original_lines[i], "highlight": "deleted"})
            summary["deleted"] += 1

output = {
    "original": original_out,
    "healed": healed_out,
    "summary": summary
}

print(json.dumps(output, indent=2))
