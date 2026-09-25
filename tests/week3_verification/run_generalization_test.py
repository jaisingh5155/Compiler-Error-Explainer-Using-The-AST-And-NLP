#!/usr/bin/env python3
"""
Generalization Check for Classifier Dialect Normalization (Section B, Question 6).
Evaluates 5 held-out novel C++ files with unseen variable/function names and structures.
"""
import os
import sys
import subprocess

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(project_root, "src"))

from error_parser import parse_errors
from error_classifier import ErrorClassifier

GEN_FILES = [
    {
        "filename": "gen01_undeclared_func.cpp",
        "expected": "name_resolution",
        "code": (
            "#include <iostream>\n"
            "int main() {\n"
            "    double sensorReading = 42.5;\n"
            "    processTelemetryStream(sensorReading);\n"
            "    return 0;\n"
            "}\n"
        )
    },
    {
        "filename": "gen02_type_ptr_init.cpp",
        "expected": "type_error",
        "code": (
            "int main() {\n"
            "    double velocity = 9.8;\n"
            "    int* ptr = velocity;\n"
            "    return 0;\n"
            "}\n"
        )
    },
    {
        "filename": "gen03_undeclared_loop_var.cpp",
        "expected": "name_resolution",
        "code": (
            "#include <vector>\n"
            "int main() {\n"
            "    std::vector<int> packetQueue = {1, 2, 3};\n"
            "    for (size_t i = 0; i < packetQueue.size(); ++i) {\n"
            "        accumulator += packetQueue[i];\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
    },
    {
        "filename": "gen04_incompat_assign.cpp",
        "expected": "type_error",
        "code": (
            "int main() {\n"
            "    float* fptr = nullptr;\n"
            "    int number = 10;\n"
            "    fptr = number;\n"
            "    return 0;\n"
            "}\n"
        )
    },
    {
        "filename": "gen05_binary_op_mismatch.cpp",
        "expected": "type_error",
        "code": (
            "struct AudioSample {\n"
            "    float amplitude;\n"
            "};\n"
            "int main() {\n"
            "    AudioSample s1{0.5f};\n"
            "    AudioSample s2{0.8f};\n"
            "    auto result = s1 + s2;\n"
            "    return 0;\n"
            "}\n"
        )
    }
]

def run_generalization_test():
    gen_dir = os.path.join(project_root, "tests", "week3_verification", "generalization")
    os.makedirs(gen_dir, exist_ok=True)

    classifier = ErrorClassifier()
    classifier.load()

    results = []
    correct = 0

    print("=" * 80)
    print("CLASSIFIER GENERALIZATION TEST (5 NOVEL HELD-OUT C++ FILES)")
    print("=" * 80)

    for item in GEN_FILES:
        filepath = os.path.join(gen_dir, item["filename"])
        with open(filepath, "w") as f:
            f.write(item["code"])

        # Compile with Apple Clang
        proc = subprocess.run(
            ["clang++", "-std=c++17", "-Wall", "-c", filepath, "-o", "/dev/null"],
            capture_output=True,
            text=True
        )

        compiler_output = proc.stderr
        parsed = parse_errors(compiler_output)

        if not parsed:
            print(f"[-] {item['filename']}: No errors parsed from compiler output!")
            results.append({"file": item["filename"], "expected": item["expected"], "pred": "NONE", "conf": 0.0, "match": False})
            continue

        first_error = parsed[0]
        pred_cat, conf = classifier.predict(first_error.message)
        matched = (pred_cat == item["expected"])
        if matched:
            correct += 1

        results.append({
            "file": item["filename"],
            "raw_msg": first_error.message,
            "expected": item["expected"],
            "pred": pred_cat,
            "conf": conf,
            "match": matched
        })

        status_sym = "✓" if matched else "✗"
        print(f"[{status_sym}] {item['filename']}")
        print(f"    Raw Clang: {first_error.message}")
        print(f"    Expected:  {item['expected']}")
        print(f"    Predicted: {pred_cat} (confidence: {conf:.3f})")
        print()

    accuracy = (correct / len(GEN_FILES)) * 100.0
    print("-" * 80)
    print(f"Generalization Accuracy: {correct}/{len(GEN_FILES)} ({accuracy:.1f}%)")
    print("=" * 80)
    return results, accuracy

if __name__ == "__main__":
    run_generalization_test()
