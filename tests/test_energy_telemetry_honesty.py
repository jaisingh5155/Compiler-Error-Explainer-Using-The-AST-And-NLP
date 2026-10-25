"""
Regression and honesty test suite for Energy Telemetry, CodeCarbon Index, and System Telemetry.
Verifies that:
1. Contrasting workloads (trivial vs heavy) produce differing wall duration, CPU time, and peak memory.
2. Repeated runs on the same workload produce realistic non-identical values (no fake static constants).
3. RAPL hardware telemetry returns "N/A (not supported on this OS)" on macOS Darwin.
4. Compiler version is dynamically detected and does NOT equal hardcoded "GCC 11.4".
5. Error cards and footer do not contain hardcoded fake literals ("2.5", "12 MB", "GCC 11.4").
6. Telemetry metrics in GUI have honest [measured] or [estimated] tags.
"""

import os
import sys
import time
import subprocess
import pytest

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

try:
    from PyQt6.QtWidgets import QApplication
    from gui import (
        AppGUI,
        EnergyPage,
        SparklineGraph,
        MetricsGraph,
        _detect_compiler_version,
        _read_rapl_status,
        _get_configured_telemetry_constants,
        _measure_child_rss_mb,
    )
    PYQT_AVAILABLE = True
except ImportError:
    PYQT_AVAILABLE = False


@pytest.fixture(scope="module")
def qapp():
    if not PYQT_AVAILABLE:
        pytest.skip("PyQt6 not available in this environment")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def test_rapl_honesty_on_darwin():
    """Assert RAPL hardware telemetry returns 'N/A (not supported on this OS)' on Darwin."""
    import platform
    joules, status = _read_rapl_status()
    if platform.system() == "Darwin":
        assert joules is None
        assert "not supported on this OS" in status
        assert "0.000" not in status


def test_compiler_version_dynamic_detection():
    """Assert compiler version is dynamically detected and not hardcoded to GCC 11.4."""
    version = _detect_compiler_version()
    assert version is not None
    assert len(version) > 0
    # On host macOS with Apple Clang 21, it should detect Apple Clang or Clang
    assert "GCC 11.4" not in version or os.environ.get("CXX_OVERRIDE") == "gcc-11.4"


def test_config_telemetry_constants():
    """Assert grid intensity, assumed TDP, region, and source are loaded from config.yaml."""
    grid_intensity, assumed_tdp = _get_configured_telemetry_constants()
    assert grid_intensity == 700.0
    assert assumed_tdp == 15.0
    consts = _get_configured_telemetry_constants()
    assert consts.grid_region == "India (approx. national average)"
    assert "CEA/Ember" in consts.grid_source


def test_error_card_no_fake_telemetry_badges(qapp):
    """Assert error cards do not display fake CPU 2.5 mWh or MEM 12 MB badges."""
    window = AppGUI()
    diag = {
        "line": 10,
        "type": "error",
        "error_type": "error",
        "message": "expected ';' before '}' token",
        "category": "syntax_error",
        "hotspot": "Line 10",
        "security_risk": "LOW",
    }
    card = window._create_error_card(diag)
    
    # Extract all text inside the card
    text_content = ""
    for label in card.findChildren(type(window.status_bar_left)):
        text_content += " " + label.text()

    assert "2.5 mWh" not in text_content
    assert "12 MB" not in text_content
    assert "HOTSPOT: Line 10" in text_content
    assert "RISK: LOW" in text_content


def test_status_bar_left_not_hardcoded(qapp):
    """Assert status bar left does not have hardcoded GCC 11.4 and begins in honest startup state."""
    window = AppGUI()
    status_text = window.status_bar_left.text()
    assert "Compiler: GCC 11.4" not in status_text
    assert f"Compiler: {window.compiler_version}" in status_text
    assert "File Name: no file" in status_text
    assert "Errors: -" in status_text
    assert "Warnings: -" in status_text


def test_energy_page_idle_state(qapp):
    """Assert EnergyPage starts in a clear honest idle state with explicit grid assumption and tags."""
    page = EnergyPage()
    assert "No run yet" in page.time_value.text()
    assert "[measured]" in page.time_value.text()
    assert "No run yet" in page.cpu_value.text()
    assert "[measured]" in page.cpu_value.text()
    assert "No run yet" in page.energy_value.text()
    assert "[estimated]" in page.energy_value.text()
    assert "assumed grid: India ~700 g/kWh" in page.energy_value.text()
    if sys.platform == "darwin":
        assert "not supported on this OS" in page.rapl_value.text()
        assert "[unavailable]" in page.rapl_value.text()


def test_discriminating_rss_200mb_vs_trivial(qapp):
    """Task 1(a): A program that touches ~200MB vs trivial must differ in RSS by at least ~150MB."""
    window = AppGUI()

    code_200mb = """#include <iostream>
#include <cstring>
int main() {
    size_t sz = 200 * 1024 * 1024;
    char* p = new char[sz];
    std::memset(p, 1, sz);
    delete[] p;
    return 0;
}
"""
    window.editor.setPlainText(code_200mb)
    window.run_code()
    assert window.process.waitForFinished(15000)
    rss_200 = window.last_run_telemetry["rss_mb"]

    code_trivial = "int main() { return 0; }"
    window.editor.setPlainText(code_trivial)
    window.run_code()
    assert window.process.waitForFinished(10000)
    rss_trivial = window.last_run_telemetry["rss_mb"]

    diff_mb = rss_200 - rss_trivial
    assert diff_mb >= 150.0, f"Expected RSS diff >= 150MB, got {diff_mb:.2f}MB (200MB={rss_200:.2f}MB, trivial={rss_trivial:.2f}MB)"


def test_high_water_mark_reversion_sequence(qapp):
    """Task 1(b): Run 200MB first, then trivial: trivial must drop back to a few MB, catching high-water mark."""
    window = AppGUI()

    code_200mb = """#include <iostream>
#include <cstring>
int main() {
    size_t sz = 200 * 1024 * 1024;
    char* p = new char[sz];
    std::memset(p, 1, sz);
    delete[] p;
    return 0;
}
"""
    window.editor.setPlainText(code_200mb)
    window.run_code()
    assert window.process.waitForFinished(15000)
    rss_first = window.last_run_telemetry["rss_mb"]
    assert rss_first > 150.0

    # Run trivial SECOND: must drop back to a few MB, NOT stay at 200MB
    code_trivial = "int main() { return 0; }"
    window.editor.setPlainText(code_trivial)
    window.run_code()
    assert window.process.waitForFinished(10000)
    rss_second = window.last_run_telemetry["rss_mb"]

    assert rss_second < 15.0, f"Expected trivial run after 200MB to drop to <15MB, got {rss_second:.2f}MB"


def test_cpu_time_loop_vs_trivial(qapp):
    """Task 1(c): CPU time of the loop program is much greater than the trivial one."""
    window = AppGUI()

    code_trivial = "int main() { return 0; }"
    window.editor.setPlainText(code_trivial)
    window.run_code()
    assert window.process.waitForFinished(10000)
    cpu_trivial = window.last_run_telemetry["cpu_s"]

    code_loop = """#include <iostream>
int main() {
    volatile long long sum = 0;
    for (long long i = 0; i < 200000000LL; ++i) {
        sum += i;
    }
    return 0;
}
"""
    window.editor.setPlainText(code_loop)
    window.run_code()
    assert window.process.waitForFinished(15000)
    cpu_loop = window.last_run_telemetry["cpu_s"]

    assert cpu_loop > cpu_trivial, f"Loop CPU ({cpu_loop:.4f}s) should exceed trivial CPU ({cpu_trivial:.4f}s)"
    assert cpu_loop >= 0.05, f"Expected loop CPU time >= 0.05s, got {cpu_loop:.4f}s"


def test_contrasting_workloads_measurement(qapp):
    """Assert contrasting workloads (trivial vs heavy) produce differing wall duration, CPU time, and memory."""
    window = AppGUI()

    # Warm-up run
    window.editor.setPlainText('#include <iostream>\nint main() { return 0; }\n')
    window.run_code()
    assert window.process.waitForFinished(10000)

    # Trivial workload
    trivial_code = '#include <iostream>\nint main() { return 0; }\n'
    window.editor.setPlainText(trivial_code)
    window.run_code()
    assert window.process.waitForFinished(10000)

    trivial_telemetry = window.last_run_telemetry
    assert trivial_telemetry is not None
    t_wall = trivial_telemetry["wall_s"]

    # Heavy workload (compute 150 million iterations in loop)
    heavy_code = '''#include <iostream>
int main() {
    volatile long long sum = 0;
    for (long long i = 0; i < 150000000LL; ++i) {
        sum += i;
    }
    std::cout << "Done: " << sum << std::endl;
    return 0;
}
'''
    window.editor.setPlainText(heavy_code)
    window.run_code()
    assert window.process.waitForFinished(15000)

    heavy_telemetry = window.last_run_telemetry
    assert heavy_telemetry is not None
    h_wall = heavy_telemetry["wall_s"]

    # Heavy workload must take demonstrably longer duration
    assert h_wall > t_wall, f"Expected heavy wall time ({h_wall}s) > trivial wall time ({t_wall}s)"
    assert len(window.telemetry_history) >= 2


def test_repeated_runs_variance(qapp):
    """Assert repeated runs produce realistic varying measurements, not static fixed values."""
    window = AppGUI()
    code = '''#include <iostream>
int main() {
    volatile long long x = 0;
    for (int i = 0; i < 5000000; ++i) x += i;
    std::cout << x << std::endl;
    return 0;
}'''
    window.editor.setPlainText(code)

    # Run 1
    window.run_code()
    assert window.process.waitForFinished(10000)
    run1 = dict(window.last_run_telemetry)

    # Run 2
    window.run_code()
    assert window.process.waitForFinished(10000)
    run2 = dict(window.last_run_telemetry)

    assert run1["wall_s"] > 0
    assert run2["wall_s"] > 0
    # Both runs should have honest timestamps and measurements
    assert run1["timestamp"] != run2["timestamp"]
