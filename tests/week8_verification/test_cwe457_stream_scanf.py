#!/usr/bin/env python3
"""
tests/week8_verification/test_cwe457_stream_scanf.py
────────────────────────────────────────────────────
Regression tests for CWE-457 (Uninitialized Read) false positive fixes:
1. Stream extraction via operator>> on istream (cin >> x, std::cin >> x).
2. Chained stream extraction (cin >> a >> b, std::cin >> a >> b).
3. File stream extraction (ifstream >> x, std::ifstream >> x).
4. C-style scanf family with address-of (&x, &a): scanf, fscanf, sscanf (both global and std::).
5. Stream string extraction via getline(cin, s) and std::getline(std::cin, s).
6. Preserves genuine CWE-457 detection on benchmark/security/sec11 and sec21.
"""

import os
import sys
import tempfile
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from security_analyzer import analyze


def _has_uninit_read(code: str) -> bool:
    with tempfile.NamedTemporaryFile("w", suffix=".cpp") as f:
        f.write(code)
        f.flush()
        findings = analyze(f.name, [])
        return any(
            f.vulnerability_type == "Uninitialized Memory" or "uninitialized" in f.description.lower()
            for f in findings
        )


def test_cin_stream_extraction_using_namespace():
    code = """
    #include <iostream>
    using namespace std;
    int main() {
        int age;
        cin >> age;
        cout << age << endl;
        return 0;
    }
    """
    assert not _has_uninit_read(code), "cin >> age should not be flagged as uninitialized read"


def test_cin_stream_extraction_std_qualified():
    code = """
    #include <iostream>
    int main() {
        int age;
        std::cin >> age;
        std::cout << age << std::endl;
        return 0;
    }
    """
    assert not _has_uninit_read(code), "std::cin >> age should not be flagged as uninitialized read"


def test_cin_chained_stream_extraction_using_namespace():
    code = """
    #include <iostream>
    using namespace std;
    int main() {
        int a, b;
        cin >> a >> b;
        cout << a << b << endl;
        return 0;
    }
    """
    assert not _has_uninit_read(code), "chained cin >> a >> b should not be flagged"


def test_cin_chained_stream_extraction_std_qualified():
    code = """
    #include <iostream>
    int main() {
        int a, b;
        std::cin >> a >> b;
        std::cout << a << b << std::endl;
        return 0;
    }
    """
    assert not _has_uninit_read(code), "chained std::cin >> a >> b should not be flagged"


def test_ifstream_stream_extraction_using_namespace():
    code = """
    #include <fstream>
    #include <iostream>
    using namespace std;
    int main() {
        ifstream infile("data.txt");
        int count;
        infile >> count;
        cout << count << endl;
        return 0;
    }
    """
    assert not _has_uninit_read(code), "ifstream >> count should not be flagged"


def test_ifstream_stream_extraction_std_qualified():
    code = """
    #include <fstream>
    #include <iostream>
    int main() {
        std::ifstream infile("data.txt");
        int count;
        infile >> count;
        std::cout << count << std::endl;
        return 0;
    }
    """
    assert not _has_uninit_read(code), "std::ifstream >> count should not be flagged"


def test_scanf_address_of_variants():
    code_scanf = """
    #include <cstdio>
    int main() {
        int x;
        scanf("%d", &x);
        printf("%d", x);
        return 0;
    }
    """
    assert not _has_uninit_read(code_scanf), "scanf with &x should count as initialized"

    code_std_scanf = """
    #include <cstdio>
    int main() {
        int x;
        std::scanf("%d", &x);
        std::printf("%d", x);
        return 0;
    }
    """
    assert not _has_uninit_read(code_std_scanf), "std::scanf with &x should count as initialized"


def test_fscanf_and_sscanf_variants():
    code_fscanf = """
    #include <cstdio>
    int main() {
        FILE* f = fopen("in.txt", "r");
        int n;
        fscanf(f, "%d", &n);
        printf("%d", n);
        return 0;
    }
    """
    assert not _has_uninit_read(code_fscanf), "fscanf with &n should count as initialized"

    code_sscanf = """
    #include <cstdio>
    int main() {
        const char* buf = "123";
        int val;
        sscanf(buf, "%d", &val);
        printf("%d", val);
        return 0;
    }
    """
    assert not _has_uninit_read(code_sscanf), "sscanf with &val should count as initialized"

    code_std_sscanf = """
    #include <cstdio>
    int main() {
        const char* buf = "123";
        int val;
        std::sscanf(buf, "%d", &val);
        std::printf("%d", val);
        return 0;
    }
    """
    assert not _has_uninit_read(code_std_sscanf), "std::sscanf with &val should count as initialized"


def test_getline_variants():
    code_getline = """
    #include <iostream>
    #include <string>
    using namespace std;
    int main() {
        string line;
        getline(cin, line);
        cout << line << endl;
        return 0;
    }
    """
    assert not _has_uninit_read(code_getline), "getline(cin, line) should count line as initialized"

    code_std_getline = """
    #include <iostream>
    #include <string>
    int main() {
        std::string line;
        std::getline(std::cin, line);
        std::cout << line << std::endl;
        return 0;
    }
    """
    assert not _has_uninit_read(code_std_getline), "std::getline(std::cin, line) should count line as initialized"


def test_genuine_cwe457_detection_preserved():
    sec11_path = os.path.join(BASE_DIR, "benchmark", "security", "sec11_uninit_use.cpp")
    sec21_path = os.path.join(BASE_DIR, "benchmark", "security", "sec21_uninit_branch_leak.cpp")

    f11 = analyze(sec11_path, [])
    u11 = [f for f in f11 if f.vulnerability_type == "Uninitialized Memory" or "uninitialized" in f.description.lower()]
    assert len(u11) >= 1, "sec11_uninit_use.cpp must still trigger CWE-457 finding"

    f21 = analyze(sec21_path, [])
    u21 = [f for f in f21 if f.vulnerability_type == "Uninitialized Memory" or "uninitialized" in f.description.lower()]
    assert len(u21) >= 1, "sec21_uninit_branch_leak.cpp must still trigger CWE-457 finding"
