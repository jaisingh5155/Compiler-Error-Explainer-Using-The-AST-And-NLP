log_path = "/Users/jaisinghsaini/.gemini/antigravity-ide/brain/788263de-e242-422a-85da-f1ac50d61aa9/.system_generated/tasks/task-2169.log"
with open(log_path, "r", encoding="utf-8") as f:
    lines = [line.strip() for line in f if "::" in line]

files = {}
for line in lines:
    fpath = line.split("::")[0]
    files[fpath] = files.get(fpath, 0) + 1

total = sum(files.values())
print(f"Total tests collected: {total}\n")
print("| Directory / Test File | Test Count |")
print("|---|---|")
for fpath, count in sorted(files.items()):
    print(f"| `{fpath}` | {count} |")
print(f"| **TOTAL** | **{total}** |")
