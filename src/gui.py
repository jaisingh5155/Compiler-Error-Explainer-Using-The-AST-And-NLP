import sys
import os

if "QT_PLUGIN_PATH" not in os.environ:
    try:
        import PyQt6
        _qt_plugin_path = os.path.join(os.path.dirname(PyQt6.__file__), "Qt6", "plugins")
        if os.path.exists(_qt_plugin_path):
            os.environ["QT_PLUGIN_PATH"] = _qt_plugin_path
    except Exception:
        pass

import subprocess
import json
import re
import html
import time
import math
import random
from typing import Any, Optional, List, Dict
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QSplitter, QPlainTextEdit, QTextEdit,
                             QPushButton, QFileDialog, QMessageBox, QLabel, QFrame,
                             QCheckBox, QDialog, QTreeWidget, QTreeWidgetItem, QLineEdit,
                             QGraphicsOpacityEffect, QGraphicsDropShadowEffect, QScrollArea, QSizePolicy, QTextBrowser,
                             QProgressBar, QStyleFactory, QComboBox,
                             QStackedWidget, QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsLineItem, QGraphicsTextItem, QGraphicsItem)
from PyQt6.QtCore import Qt, QRect, QSize, QThread, pyqtSignal, QTimer, QVariantAnimation, QProcess, QPropertyAnimation, QRectF, QPointF, QObject, QByteArray
from PyQt6.QtGui import QFont, QColor, QPainter, QTextFormat, QTextCharFormat, QSyntaxHighlighter, QTextCursor, QPainterPath, QPen, QLinearGradient, QBrush
import platform
import socket
import tempfile
import selectors
import threading
try:
    import resource
except ImportError:
    resource = None
try:
    from codecarbon import EmissionsTracker
    CODECARBON_AVAILABLE = True
except ImportError:
    CODECARBON_AVAILABLE = False
try:
    from heal_loop import HealWorker
    HEALER_AVAILABLE = True
except ImportError:
    HEALER_AVAILABLE = False

try:
    from error_classifier import ErrorClassifier
except ImportError:
    ErrorClassifier = None

from ast_extractor import extract_ast, extract_node_near_line, parse_ast_to_tree
from security_analyzer import analyze as analyze_security, format_security_report, get_cwe_for_vulnerability
try:
    from root_cause_grouper import group_view_model, Group
except ImportError:
    group_view_model = lambda diags: []
    Group = None

try:
    from trace_view import format_trace_html, format_trace_text, summarize_trace
except ImportError:
    format_trace_html = lambda x: "<pre>" + str(x) + "</pre>"
    format_trace_text = lambda x: str(x)
    summarize_trace = lambda x: {"total_steps": len(x), "patches_applied": 0, "patches_rolled_back": 0, "patches_pending": 0, "stop_reason": "done"}

try:
    from patch_review import PatchReviewSession, ReviewablePatch, PatchStatus, InvalidTransitionError
except ImportError:
    PatchReviewSession = None
    ReviewablePatch = None
    PatchStatus = None
    InvalidTransitionError = Exception

try:
    import feedback_store as _feedback_store
    from error_classifier import ALL_CATEGORIES as _ALL_CATEGORIES
    _FEEDBACK_STORE_AVAILABLE = True
except ImportError:
    _feedback_store = None
    _ALL_CATEGORIES = [
        "syntax_error", "type_error", "name_resolution", "missing_include",
        "redefinition", "access_error", "return_type_error", "unused_variable",
        "linker_error", "other"
    ]
    _FEEDBACK_STORE_AVAILABLE = False

BG_COLOR = "#f4f7f9"          
PANE_BG = "#ffffff"           
HEADER_BG = "#f4f7f9"         
BORDER_COLOR = "#e6ebf1"      
PINK = "#5469d4"  
TEXT_MAIN = "#1a1f36"         
TEXT_DIM = "#4f566b"          
KEYWORD_COLOR = "#5469d4"     
ERROR_LINE_COLOR = "#fefafb" 
RED = "#d12441"
YELLOW = "#ffcc00"
GREEN = "#24b47e"

FONT_FAMILY = "Menlo" if platform.system() == "Darwin" else "Consolas"

def _read_rapl_energy_joules():
    root = "/sys/class/powercap"
    if not os.path.isdir(root):
        return None

    total_uj = 0
    found = False
    for dirpath, _, filenames in os.walk(root):
        if "energy_uj" not in filenames:
            continue
        try:
            with open(os.path.join(dirpath, "energy_uj"), "r", encoding="utf-8") as f:
                total_uj += int(f.read().strip())
                found = True
        except (OSError, ValueError):
            continue

    return total_uj / 1_000_000 if found else None

def _read_rapl_status():
    """Return (joules_or_None, display_text) honestly checking host OS and hardware interface."""
    if platform.system() == "Darwin":
        return None, "N/A (not supported on this OS)"
    joules = _read_rapl_energy_joules()
    if joules is not None:
        return joules, f"{joules:.3f} J"
    if not os.path.isdir("/sys/class/powercap"):
        return None, "Unavailable (no /sys/class/powercap)"
    return None, "Unavailable (permission denied on /sys/class/powercap)"

_CACHED_COMPILER_LABEL: str | None = None

def _resolve_compiler_command(cli_override: str | None = None) -> str:
    """Resolve compiler binary used by compiler_runner.py (CLI override, env CXX_OVERRIDE, or config.yaml)."""
    if cli_override:
        return cli_override
    if "--compiler" in sys.argv:
        try:
            idx = sys.argv.index("--compiler")
            if idx + 1 < len(sys.argv):
                return sys.argv[idx + 1]
        except Exception:
            pass
    env_cxx = os.environ.get("CXX_OVERRIDE")
    if env_cxx:
        return env_cxx
    try:
        from config_loader import get as cfg_get
        cmd = cfg_get("compiler", "command")
        if cmd:
            return cmd
    except Exception:
        pass
    return "g++"

def _resolve_language_standard() -> str:
    """Read the language standard from config.yaml compiler settings or flags.
    If the flag is absent, returns 'default'."""
    std = None
    try:
        from config_loader import get as cfg_get
        std = cfg_get("compiler", "standard")
        if not std:
            extra_flags = cfg_get("compiler", "extra_flags") or []
            for flag in extra_flags:
                if flag.startswith("-std="):
                    std = flag[len("-std="):]
                    break
    except Exception:
        pass

    if not std:
        return "default"

    std_str = str(std).strip()
    if std_str.startswith("-std="):
        std_str = std_str[len("-std="):]
    if std_str.lower().startswith("c++"):
        return "C++" + std_str[3:]
    elif std_str.lower().startswith("gnu++"):
        return "GNU++" + std_str[5:]
    return std_str

def _detect_compiler_version(compiler_cmd: str | None = None, force_refresh: bool = False) -> str:
    """Run compiler with --version once and parse a short label, e.g. 'Apple clang 21.0.0' or 'GCC 16.2.0'.
    Times out after 2 seconds or returns 'unknown' on any failure. Never falls back to a made-up default."""
    global _CACHED_COMPILER_LABEL
    if _CACHED_COMPILER_LABEL is not None and not force_refresh and compiler_cmd is None:
        return _CACHED_COMPILER_LABEL

    cmd = compiler_cmd or _resolve_compiler_command()
    label = "unknown"

    try:
        res = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=2.0)
        if res.returncode == 0 and res.stdout:
            first_line = res.stdout.strip().split("\n")[0]
            if "Apple clang" in first_line or "Apple LLVM" in first_line:
                m = re.search(r"Apple\s+(?:clang|LLVM)\s+version\s+([\d\.]+)", first_line, re.IGNORECASE)
                label = f"Apple clang {m.group(1)}" if m else "Apple clang"
            elif "clang" in first_line.lower():
                m = re.search(r"clang\s+version\s+([\d\.]+)", first_line, re.IGNORECASE)
                label = f"clang {m.group(1)}" if m else "clang"
            elif "g++" in first_line.lower() or "gcc" in first_line.lower():
                m = re.search(r"(?:g\+\+|gcc)\s+(?:\([^)]*\)\s+)?([\d\.]+)", first_line, re.IGNORECASE)
                if not m:
                    m = re.search(r"(\d+\.\d+(?:\.\d+)?)", first_line)
                label = f"GCC {m.group(1)}" if m else "GCC"
            else:
                label = first_line.split()[0] if first_line else "unknown"
        else:
            label = "unknown"
    except Exception:
        label = "unknown"

    if compiler_cmd is None and not force_refresh:
        _CACHED_COMPILER_LABEL = label
    return label

get_status_bar_compiler_label = _detect_compiler_version

class TelemetryConstants(tuple):
    """Tuple subclass supporting 2-element unpacking (grid_intensity, assumed_tdp)
    while exposing grid_region and grid_source as named properties."""
    def __new__(cls, grid_intensity=700.0, assumed_tdp=15.0, grid_region="India (approx. national average)", grid_source="approximate; verify against CEA/Ember before citing"):
        return super().__new__(cls, (grid_intensity, assumed_tdp))

    def __init__(self, grid_intensity=700.0, assumed_tdp=15.0, grid_region="India (approx. national average)", grid_source="approximate; verify against CEA/Ember before citing"):
        self.grid_intensity = grid_intensity
        self.assumed_tdp = assumed_tdp
        self.grid_region = grid_region
        self.grid_source = grid_source

def _get_configured_telemetry_constants() -> TelemetryConstants:
    """Load grid carbon intensity, assumed active package TDP, region, and source from config.yaml."""
    grid_intensity = 700.0
    assumed_tdp = 15.0
    grid_region = "India (approx. national average)"
    grid_source = "approximate; verify against CEA/Ember before citing"
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")
    if os.path.exists(config_path):
        try:
            import yaml
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
                t_cfg = cfg.get("telemetry", {})
                grid_intensity = float(t_cfg.get("grid_carbon_intensity_g_per_kwh", grid_intensity))
                assumed_tdp = float(t_cfg.get("assumed_package_tdp_watts", assumed_tdp))
                grid_region = str(t_cfg.get("grid_region", grid_region))
                grid_source = str(t_cfg.get("grid_source", grid_source))
        except Exception:
            pass
    return TelemetryConstants(grid_intensity, assumed_tdp, grid_region, grid_source)

def _measure_child_rss_mb(ru):
    """Accurately convert ru_maxrss from os.wait4 or getrusage to megabytes.
    On macOS (Darwin), ru_maxrss is in bytes; on Linux, it is in kilobytes.
    """
    if ru is None:
        return 0.0
    raw_rss = float(getattr(ru, "ru_maxrss", 0))
    if sys.platform == "darwin":
        return raw_rss / (1024.0 * 1024.0)
    return raw_rss / 1024.0

def run_command_with_wait4(cmd, timeout=None, input_data=None):
    """Run a subprocess command and reap it strictly via os.wait4(pid, 0)
    to obtain accurate per-process rusage (ru_utime, ru_stime, ru_maxrss)
    without contamination from lifetime RUSAGE_CHILDREN or concurrent background threads.
    Subprocess.Popen bookkeeping is maintained by setting proc.returncode."""
    t0 = time.perf_counter()
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE if input_data is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if input_data is not None and proc.stdin:
        try:
            proc.stdin.write(input_data)
            proc.stdin.close()
        except Exception:
            pass

    stdout_chunks = []
    stderr_chunks = []
    sel = selectors.DefaultSelector()
    if proc.stdout:
        sel.register(proc.stdout, selectors.EVENT_READ, (stdout_chunks, proc.stdout))
    if proc.stderr:
        sel.register(proc.stderr, selectors.EVENT_READ, (stderr_chunks, proc.stderr))

    deadline = (t0 + timeout) if timeout else None
    while sel.get_map():
        timeout_left = max(0.0, deadline - time.perf_counter()) if deadline else None
        if deadline and timeout_left <= 0:
            proc.kill()
            raise subprocess.TimeoutExpired(cmd, timeout)
        events = sel.select(timeout=timeout_left if timeout_left is not None else 0.1)
        for key, _ in events:
            chunk_list, stream = key.data
            chunk = stream.read(4096)
            if not chunk:
                sel.unregister(stream)
                stream.close()
            else:
                chunk_list.append(chunk)

    try:
        pid, status, ru = os.wait4(proc.pid, 0)
        exit_code = os.waitstatus_to_exitcode(status) if hasattr(os, "waitstatus_to_exitcode") else (
            (status >> 8) if os.WIFEXITED(status) else -os.WTERMSIG(status)
        )
    except ChildProcessError:
        exit_code = proc.poll() or 0
        ru = None

    proc.returncode = exit_code
    wall_time = max(0.0001, time.perf_counter() - t0)
    stdout = "".join(stdout_chunks)
    stderr = "".join(stderr_chunks)

    cpu_time = (ru.ru_utime + ru.ru_stime) if ru else wall_time
    rss_mb = _measure_child_rss_mb(ru) if ru else 0.0

    return subprocess.CompletedProcess(cmd, exit_code, stdout, stderr), wall_time, cpu_time, rss_mb

class ProcessRunner(QObject):
    """Subprocess runner drop-in for QProcess that executes binaries and reaps
    strictly via os.wait4(pid, 0) to collect exact per-run rusage (ru_utime,
    ru_stime, ru_maxrss) instead of contaminated lifetime process-wide deltas."""
    readyReadStandardOutput = pyqtSignal()
    finished = pyqtSignal(int, int)  # exit_code, exit_status
    errorOccurred = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proc = None
        self._output_buffer = bytearray()
        self._lock = threading.Lock()
        self._worker_thread = None
        self.rusage = None
        self.cpu_time = 0.0
        self.rss_mb = 0.0
        self.wall_time = 0.0
        self._t0 = 0.0
        self.returncode = None

    def setProcessChannelMode(self, mode):
        pass

    def state(self):
        if self.proc and self.proc.poll() is None:
            return QProcess.ProcessState.Running
        return QProcess.ProcessState.NotRunning

    def kill(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.kill()
            except Exception:
                pass

    def waitForFinished(self, msecs=30000):
        t0 = time.perf_counter()
        timeout = (msecs / 1000.0) if msecs > 0 else 30.0
        while self._worker_thread and self._worker_thread.is_alive():
            QApplication.processEvents()
            if time.perf_counter() - t0 > timeout:
                return False
            time.sleep(0.005)
        for _ in range(5):
            QApplication.processEvents()
        return True

    def write(self, data: bytes):
        if self.proc and self.proc.stdin:
            try:
                self.proc.stdin.write(data)
                self.proc.stdin.flush()
            except Exception:
                pass

    def readAllStandardOutput(self):
        with self._lock:
            data = bytes(self._output_buffer)
            self._output_buffer.clear()
        return QByteArray(data)

    def start(self, program, args=None):
        cmd = [program] + (args or [])
        self._t0 = time.perf_counter()
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
            )
        except Exception:
            self.errorOccurred.emit(QProcess.ProcessError.FailedToStart)
            return

        def _reader_and_reaper():
            try:
                while True:
                    chunk = self.proc.stdout.read(1024)
                    if not chunk:
                        break
                    with self._lock:
                        self._output_buffer.extend(chunk)
                    self.readyReadStandardOutput.emit()
            except Exception:
                pass
            finally:
                if self.proc.stdout:
                    try:
                        self.proc.stdout.close()
                    except Exception:
                        pass

            try:
                pid, status, ru = os.wait4(self.proc.pid, 0)
                if hasattr(os, "waitstatus_to_exitcode"):
                    exit_code = os.waitstatus_to_exitcode(status)
                else:
                    exit_code = (status >> 8) if os.WIFEXITED(status) else -os.WTERMSIG(status)
                self.rusage = ru
                self.cpu_time = (ru.ru_utime + ru.ru_stime) if ru else 0.0
                self.rss_mb = _measure_child_rss_mb(ru) if ru else 0.0
            except ChildProcessError:
                exit_code = self.proc.poll() if self.proc.poll() is not None else 0
                self.rusage = None
                self.cpu_time = 0.0
                self.rss_mb = 0.0

            self.proc.returncode = exit_code
            self.returncode = exit_code
            self.wall_time = max(0.0001, time.perf_counter() - self._t0)
            exit_status = QProcess.ExitStatus.NormalExit if exit_code >= 0 else QProcess.ExitStatus.CrashExit
            self.finished.emit(exit_code, exit_status)

        self._worker_thread = threading.Thread(target=_reader_and_reaper, daemon=True)
        self._worker_thread.start()

def _extract_cpp_call_graph(code):
    keywords = {
        "if", "for", "while", "switch", "return", "sizeof", "catch", "delete",
        "new", "static_cast", "dynamic_cast", "reinterpret_cast", "const_cast",
    }
    function_re = re.compile(
        r"(?:^|\n)\s*(?:template\s*<[^>{}]+>\s*)?"
        r"(?:[\w:<>,~*&\s]+\s+)+(?P<name>[A-Za-z_]\w*)\s*"
        r"\([^;{}]*\)\s*(?:const\s*)?(?:noexcept\s*)?\{",
        re.MULTILINE,
    )

    functions = []
    for match in function_re.finditer(code):
        name = match.group("name")
        if name in keywords:
            continue
        body_start = match.end()
        depth = 1
        i = body_start
        while i < len(code) and depth:
            if code[i] == "{":
                depth += 1
            elif code[i] == "}":
                depth -= 1
            i += 1
        functions.append({"name": name, "body": code[body_start:i - 1]})

    names = [f["name"] for f in functions]
    name_set = set(names)
    edges = set()
    external_calls = set()
    call_re = re.compile(r"\b([A-Za-z_]\w*)\s*\(")

    for function in functions:
        caller = function["name"]
        for callee in call_re.findall(function["body"]):
            if callee in keywords or callee == caller:
                continue
            if callee in name_set:
                edges.add((caller, callee))
            elif len(external_calls) < 12:
                external_calls.add((caller, callee))

    includes = re.findall(r"^\s*#include\s+[<\"]([^>\"]+)[>\"]", code, re.MULTILINE)
    modules = sorted(set(includes))
    return names, sorted(edges), sorted(external_calls), modules

def _extract_cpp_cfg(code):
    function_re = re.compile(
        r"(?:^|\n)\s*(?:[\w:<>,~*&\s]+\s+)+(?P<name>[A-Za-z_]\w*)\s*"
        r"\([^;{}]*\)\s*(?:const\s*)?(?:noexcept\s*)?\{",
        re.MULTILINE,
    )
    
    results = []
    for match in function_re.finditer(code):
        name = match.group("name")
        if name in {"if", "for", "while", "switch", "return"}:
            continue
        body_start = match.end()
        depth = 1
        i = body_start
        while i < len(code) and depth:
            if code[i] == "{": depth += 1
            elif code[i] == "}": depth -= 1
            i += 1
            
        body = code[body_start:i-1]
        lines = [l.strip() for l in body.split("\n") if l.strip()]
        
        nodes = []
        edges = []
        
        # Start node
        nodes.append({"id": "start", "label": f"START: {name}", "type": "entry"})
        
        current_node_id = "start"
        block_counter = 0
        
        pending_text = []
        
        for line in lines:
            # Check for control flow
            if any(kw in line for kw in ["if", "while", "for", "switch"]):
                # Close current block
                if pending_text:
                    block_id = f"b{block_counter}"
                    nodes.append({"id": block_id, "label": "\n".join(pending_text[:3]), "type": "stmt"})
                    edges.append((current_node_id, block_id))
                    current_node_id = block_id
                    block_counter += 1
                    pending_text = []
                
                # Create branch node
                branch_id = f"c{block_counter}"
                nodes.append({"id": branch_id, "label": line, "type": "branch"})
                edges.append((current_node_id, branch_id))
                current_node_id = branch_id
                block_counter += 1
            elif "return" in line:
                if pending_text:
                    block_id = f"b{block_counter}"
                    nodes.append({"id": block_id, "label": "\n".join(pending_text[:3]), "type": "stmt"})
                    edges.append((current_node_id, block_id))
                    current_node_id = block_id
                    block_counter += 1
                    pending_text = []
                
                ret_id = f"r{block_counter}"
                nodes.append({"id": ret_id, "label": line, "type": "exit"})
                edges.append((current_node_id, ret_id))
                current_node_id = ret_id # Technically current becomes terminal here
                block_counter += 1
            else:
                pending_text.append(line)
                if len(pending_text) > 4:
                    block_id = f"b{block_counter}"
                    nodes.append({"id": block_id, "label": "\n".join(pending_text), "type": "stmt"})
                    edges.append((current_node_id, block_id))
                    current_node_id = block_id
                    block_counter += 1
                    pending_text = []

        if pending_text or current_node_id != "start":
            if pending_text:
                block_id = f"b{block_counter}"
                nodes.append({"id": block_id, "label": "\n".join(pending_text), "type": "stmt"})
                edges.append((current_node_id, block_id))
                current_node_id = block_id
            
            nodes.append({"id": "end", "label": "END", "type": "exit"})
            edges.append((current_node_id, "end"))
            
        results.append({"name": name, "nodes": nodes, "edges": edges})
        
    return results

class SparklineGraph(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(15)
        self.setMaximumHeight(40)
        self.values = [0.0] * 50
        self.psutil_available = True
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_fluctuation)
        self.timer.start(500)
        self.peak = 0.0

    def update_fluctuation(self):
        try:
            import psutil
            val = float(psutil.cpu_percent(interval=None))
            self.psutil_available = True
        except Exception:
            val = 0.0
            self.psutil_available = False
        self.add_value(val)

    def add_value(self, val):
        self.values.pop(0)
        self.values.append(max(0.0, float(val)))
        self.update()

    def trigger_spike(self):
        try:
            import psutil
            val = float(psutil.cpu_percent(interval=None))
            self.psutil_available = True
        except Exception:
            val = 0.0
            self.psutil_available = False
        self.add_value(val)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        width = self.width()
        height = self.height()
        
        painter.setPen(QColor(BORDER_COLOR))
        painter.drawLine(0, height - 1, width, height - 1)
        
        if not getattr(self, "psutil_available", True):
            painter.setPen(QPen(QColor(TEXT_DIM)))
            painter.setFont(QFont(FONT_FAMILY, 9))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "[unavailable]")
            return

        if not self.values or len(self.values) < 2:
            return
            
        max_val = max(max(self.values), 10.0)
        
        path = QPainterPath()
        step = width / (len(self.values) - 1)
        
        for i, v in enumerate(self.values):
            x = i * step
            y = height - (v / max_val * (height - 5)) - 2
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        
        painter.setPen(QPen(QColor(PINK), 1.5))
        painter.drawPath(path)
        
        fill_path = QPainterPath(path)
        fill_path.lineTo(width, height)
        fill_path.lineTo(0, height)
        fill_path.closeSubpath()
        
        gradient = QLinearGradient(0, 0, 0, height)
        gradient.setColorAt(0, QColor(211, 141, 186, 60)) # PINK with alpha
        gradient.setColorAt(1, QColor(211, 141, 186, 0))
        painter.fillPath(fill_path, gradient)

class MetricsGraph(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.series = {
            "Duration (s)": [],
            "CPU Time (s)": [],
            "Est Energy (mWh)": [],
        }
        self.colors = {
            "Duration (s)": QColor(YELLOW),
            "CPU Time (s)": QColor(PINK),
            "Est Energy (mWh)": QColor(GREEN),
        }

    def add_run(self, duration_s: float, cpu_s: float, energy_mwh: float):
        self.series["Duration (s)"].append(max(0.0, float(duration_s or 0.0)))
        self.series["CPU Time (s)"].append(max(0.0, float(cpu_s or 0.0)))
        self.series["Est Energy (mWh)"].append(max(0.0, float(energy_mwh or 0.0)))
        for s in self.series.values():
            if len(s) > 50:
                s.pop(0)
        self.update()

    def add_sample(self, power_mw, carbon_mg_per_wh, execution_time):
        """Backward-compatible hook for CodeCarbon live samples if provided."""
        self.add_run(execution_time, 0.0, power_mw)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(PANE_BG))

        left, top, right, bottom = 60, 20, 20, 42
        width = max(1, self.width() - left - right)
        height = max(1, self.height() - top - bottom)
        graph_rect = QRect(left, top, width, height)

        painter.setPen(QPen(QColor(BORDER_COLOR), 1))
        painter.drawRect(graph_rect)
        for i in range(1, 4):
            y = top + int(height * i / 4)
            painter.drawLine(left, y, left + width, y)

        total_samples = len(self.series["Duration (s)"])

        legend_x = left
        painter.setFont(QFont(FONT_FAMILY, 9))
        for name, color in self.colors.items():
            painter.setPen(QPen(color, 2))
            painter.drawLine(legend_x, self.height() - 18, legend_x + 18, self.height() - 18)
            painter.setPen(QColor(TEXT_DIM))
            painter.drawText(legend_x + 24, self.height() - 14, name)
            legend_x += 150

        if total_samples == 0:
            painter.setFont(QFont(FONT_FAMILY, 10))
            painter.setPen(QColor(TEXT_DIM))
            msg = "No execution runs recorded yet. Compile or run code to view energy history."
            painter.drawText(graph_rect, Qt.AlignmentFlag.AlignCenter, msg)
            painter.setFont(QFont(FONT_FAMILY, 8))
            painter.drawText(8, top + 10, "0.00")
            painter.drawText(8, top + height, "0.00")
            return

        all_vals = []
        for d in self.series.values():
            all_vals.extend(d)
        max_val = max(max(all_vals) if all_vals else 0.0, 0.01)

        painter.setFont(QFont(FONT_FAMILY, 8))
        painter.setPen(QColor(TEXT_DIM))
        painter.drawText(6, top + 10, f"{max_val:.2f}")
        painter.drawText(6, top + int(height / 2), f"{(max_val / 2):.2f}")
        painter.drawText(6, top + height, "0.00")

        step = width / max(1, total_samples - 1) if total_samples > 1 else 0

        for name, data in self.series.items():
            if not data:
                continue
            color = self.colors[name]
            painter.setPen(QPen(color, 2))
            
            if total_samples == 1:
                x = left + int(width / 2)
                val = data[0]
                y = top + height - int((val / max_val) * height)
                painter.setBrush(color)
                painter.drawEllipse(x - 4, y - 4, 8, 8)
                continue

            path = QPainterPath()
            for i, value in enumerate(data):
                x = left + i * step
                y = top + height - ((value / max_val) * height)
                if i == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            painter.drawPath(path)

            painter.setBrush(color)
            for i, value in enumerate(data):
                x = left + i * step
                y = top + height - ((value / max_val) * height)
                painter.drawEllipse(int(x - 3), int(y - 3), 6, 6)

class GraphNode(QGraphicsRectItem):
    def __init__(self, label, x, y, w, h, border, fill):
        super().__init__(-w/2, -h/2, w, h)
        self.setPos(x + w/2, y + h/2)
        self.setBrush(fill)
        self.setPen(QPen(border, 1.8))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        
        self.text = QGraphicsTextItem(label, self)
        self.text.setFont(QFont(FONT_FAMILY, 9, QFont.Weight.Bold))
        self.text.setDefaultTextColor(QColor(TEXT_MAIN))
        br = self.text.boundingRect()
        self.text.setPos(-br.width() / 2, -br.height() / 2)
        
        self.edges_out = []
        self.edges_in = []

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for edge in self.edges_out:
                edge.updatePosition()
            for edge in self.edges_in:
                edge.updatePosition()
        return super().itemChange(change, value)

class GraphEdge(QGraphicsLineItem):
    def __init__(self, source_node, dest_node, color, pen_width=1.5):
        super().__init__()
        self.source_node = source_node
        self.dest_node = dest_node
        self.setPen(QPen(color, pen_width))
        self.setZValue(-1)
        self.source_node.edges_out.append(self)
        self.dest_node.edges_in.append(self)
        self.updatePosition()

    def updatePosition(self):
        self.setLine(self.source_node.pos().x(), self.source_node.pos().y(), 
                     self.dest_node.pos().x(), self.dest_node.pos().y())

class CallGraphWidget(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(420)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QColor(PANE_BG))

    def update_graph(self, functions, edges, external_calls, modules):
        self.scene.clear()
        if not functions:
            t = self.scene.addText("No C++ function definitions found in the current source.")
            t.setDefaultTextColor(QColor(TEXT_DIM))
            t.setFont(QFont(FONT_FAMILY, 12))
            return

        margin = 34
        module_y = 46
        function_y = 180
        external_y = 320
        node_w, node_h = 150, 42

        view_w = max(self.width(), 800)

        def positions(items, y):
            count = max(1, len(items))
            available = max(1, view_w - 2 * margin - node_w)
            return {
                item: (margin + (available * i / max(1, count - 1)), y)
                for i, item in enumerate(items)
            }

        function_pos = positions(functions, function_y)
        module_labels = modules[:6] or ["current source"]
        module_pos = positions(module_labels, module_y)
        external_names = sorted({callee for _, callee in external_calls})[:8]
        external_pos = positions(external_names, external_y)

        nodes = {}
        for module, pos in module_pos.items():
            node = GraphNode(module, pos[0], pos[1], node_w, node_h, QColor(TEXT_DIM), QColor(HEADER_BG))
            self.scene.addItem(node)
            nodes[module] = node
            
        for function, pos in function_pos.items():
            node = GraphNode(function, pos[0], pos[1], node_w, node_h, QColor(PINK), QColor("#ffffff"))
            self.scene.addItem(node)
            nodes[function] = node
            
        for external, pos in external_pos.items():
            node = GraphNode(external, pos[0], pos[1], node_w, node_h, QColor(GREEN), QColor("#f8fffb"))
            self.scene.addItem(node)
            nodes[external] = node
            
        for module in module_labels:
            for function in functions:
                edge = GraphEdge(nodes[module], nodes[function], QColor(BORDER_COLOR), 1.5)
                self.scene.addItem(edge)
                
        for caller, callee in edges:
            if caller in nodes and callee in nodes:
                edge = GraphEdge(nodes[caller], nodes[callee], QColor(PINK), 2.0)
                self.scene.addItem(edge)
        
        for caller, callee in external_calls:
            if caller in nodes and callee in nodes:
                edge = GraphEdge(nodes[caller], nodes[callee], QColor(GREEN), 1.5)
                self.scene.addItem(edge)


class StyledButton(QPushButton):
    def __init__(self, text, style_type="outline_dim", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(QFont(FONT_FAMILY, 11, QFont.Weight.Bold))
        self.is_active = False
        self.style_type = style_type
        self._update_style(0)
        
        self.hover_anim = QVariantAnimation(self)
        self.hover_anim.setDuration(150)
        self.hover_anim.valueChanged.connect(self._update_style)

    def set_active(self, active: bool):
        self.is_active = active
        self._update_style(0)

    def enterEvent(self, event):
        self.hover_anim.setStartValue(0)
        self.hover_anim.setEndValue(1)
        self.hover_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover_anim.setStartValue(1)
        self.hover_anim.setEndValue(0)
        self.hover_anim.start()
        super().leaveEvent(event)

    def _update_style(self, progress):
        if self.style_type == "outline_dim":
            if getattr(self, "is_active", False):
                self.setStyleSheet(f"""
                    QPushButton {{
                        border: 1px solid {PINK};
                        border-left: 4px solid {PINK};
                        background-color: #e8ecfb;
                        color: {PINK};
                        border-radius: 4px;
                        padding: 6px;
                        font-weight: bold;
                    }}
                    QPushButton:hover {{
                        background-color: #dbe2f9;
                        border: 1px solid {PINK};
                        border-left: 4px solid #3b4cb8;
                        color: #3b4cb8;
                    }}
                    QPushButton:pressed {{
                        background-color: #c7d2fe;
                    }}
                """)
            else:
                self.setStyleSheet(f"""
                    QPushButton {{
                        border: 1px solid {BORDER_COLOR};
                        border-left: 1px solid {BORDER_COLOR};
                        background-color: {PANE_BG};
                        color: {TEXT_MAIN};
                        border-radius: 4px;
                        padding: 6px;
                    }}
                    QPushButton:hover {{
                        background-color: {HEADER_BG};
                        border: 1px solid {PINK};
                        border-left: 1px solid {PINK};
                        color: {PINK};
                    }}
                    QPushButton:pressed {{
                        background-color: {BORDER_COLOR};
                    }}
                """)
        elif self.style_type == "solid_pink":
            c = QColor(PINK)
            h = QColor("#df9cc6")
            r = int(c.red() + (h.red() - c.red()) * progress)
            g = int(c.green() + (h.green() - c.green()) * progress)
            b = int(c.blue() + (h.blue() - c.blue()) * progress)
            bg = f"rgb({r}, {g}, {b})"
            
            self.setStyleSheet(f"""
                QPushButton {{
                    border: 1px solid {PINK};
                    background-color: {PINK};
                    color: {BG_COLOR};
                    padding: 8px 15px;
                }}
                QPushButton:hover {{
                    background-color: {bg};
                }}
                QPushButton:pressed {{
                    background-color: {KEYWORD_COLOR};
                }}
            """)


class StyledCheckBox(QCheckBox):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.Bold))
        self.setStyleSheet(f"color: {PINK};")

class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)
    def paintEvent(self, event):
        self.editor.line_number_area_paint_event(event)

class CodeEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)

        self.error_line = None
        self.errors = []
        self.fixed_lines = set() # Set of 1-based line numbers

        self.update_line_number_area_width(0)
        self.highlight_current_line()
        
        self.setFont(QFont(FONT_FAMILY, 13))
        self.setStyleSheet(f"QPlainTextEdit {{ background-color: {PANE_BG}; color: {TEXT_MAIN}; border: none; }}")
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        
        # Set tab stop width to 4 spaces
        font_metrics = self.fontMetrics()
        self.setTabStopDistance(4 * font_metrics.horizontalAdvance(' '))

    def set_errors(self, errors):
        self.errors = errors
        self.highlight_current_line()
        self.viewport().update()

    def set_fixed_lines(self, lines):
        self.fixed_lines = set(lines)
        self.highlight_current_line()
        self.viewport().update()

    def clear_fixed_lines(self):
        self.fixed_lines.clear()
        self.highlight_current_line()
        self.viewport().update()

    def line_number_area_width(self):
        digits = 1
        max_blocks = max(1, self.blockCount())
        while max_blocks >= 10:
            max_blocks /= 10
            digits += 1
        return 5 + self.fontMetrics().horizontalAdvance('9') * digits

    def update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy: self.line_number_area.scroll(0, dy)
        else: self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()): self.update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def line_number_area_paint_event(self, event):
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QColor(PANE_BG))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                
                if self.error_line and block_number + 1 == self.error_line:
                    painter.setPen(QColor(PINK))
                    painter.setFont(QFont(FONT_FAMILY, 13, QFont.Weight.Bold))
                else:
                    painter.setPen(QColor(TEXT_DIM))
                    painter.setFont(QFont(FONT_FAMILY, 13))
                    
                painter.drawText(0, top, self.line_number_area.width() - 5, self.fontMetrics().height(),
                                 Qt.AlignmentFlag.AlignRight, number)
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1

    def highlight_current_line(self):
        extraSelections = []
        
        if not self.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            lineColor = QColor(HEADER_BG)
            selection.format.setBackground(lineColor)
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            extraSelections.append(selection)

        # Draw green background for lines changed by the healer
        for line in self.fixed_lines:
            fixed_selection = QTextEdit.ExtraSelection()
            # Very light green background for modern feel
            fixed_selection.format.setBackground(QColor("#edfff2")) 
            fixed_selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            
            cursor = QTextCursor(self.document())
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            if line > 1:
                cursor.movePosition(QTextCursor.MoveOperation.Down, n=line - 1)
            
            fixed_selection.cursor = cursor
            extraSelections.append(fixed_selection)

        # Draw red squigglies for errors
        for err in self.errors:
            raw_line = err.get("line")
            raw_col = err.get("column")
            etype = err.get("error_type", "error").lower()
            
            try:
                line = int(raw_line) if raw_line is not None and str(raw_line).strip() != "?" else None
            except (ValueError, TypeError):
                line = None

            if line is None or line <= 0:
                continue
                
            try:
                col = int(raw_col) if raw_col is not None and str(raw_col).strip() != "?" else None
            except (ValueError, TypeError):
                col = None
                
            error_selection = QTextEdit.ExtraSelection()
            
            # Wavy underline
            fmt = QTextCharFormat()
            underline_color = QColor(RED) if etype == "error" else QColor(YELLOW)
            fmt.setUnderlineColor(underline_color)
            fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SpellCheckUnderline)
            error_selection.format = fmt
            
            cursor = QTextCursor(self.document())
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.movePosition(QTextCursor.MoveOperation.Down, n=line - 1)
            
            if col and col > 0:
                # If we have a column, try to highlight the word at that position
                cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
                cursor.movePosition(QTextCursor.MoveOperation.Right, n=col - 1)
                # Select the word or at least a few chars
                cursor.movePosition(QTextCursor.MoveOperation.NextWord, QTextCursor.MoveMode.KeepAnchor)
            else:
                # Otherwise highlight the whole line
                cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
                cursor.movePosition(QTextCursor.MoveOperation.EndOfLine, QTextCursor.MoveMode.KeepAnchor)
                
            error_selection.cursor = cursor
            extraSelections.append(error_selection)

        self.setExtraSelections(extraSelections)

    def keyPressEvent(self, event):
        # Handle Command/Control + Backspace to delete to start of line
        if event.key() == Qt.Key.Key_Backspace and event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            return

        # Handle Alt/Option + Backspace to delete previous word
        if event.key() == Qt.Key.Key_Backspace and event.modifiers() & Qt.KeyboardModifier.AltModifier:
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.PreviousWord, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            return

        # Handle Backspace at the start of a line to go to previous line
        if event.key() == Qt.Key.Key_Backspace and not event.modifiers():
            cursor = self.textCursor()
            if cursor.atBlockStart() and not cursor.atStart():
                cursor.deletePreviousChar()
                return

        if event.key() == Qt.Key.Key_Tab:
            # Insert 4 spaces instead of a tab character
            self.insertPlainText("    ")
            return

        if event.key() == Qt.Key.Key_Return:
            # Handle auto-indentation
            cursor = self.textCursor()
            current_line = cursor.block().text()
            indentation = ""
            for char in current_line:
                if char.isspace():
                    indentation += char
                else:
                    break
            
            # If the line ends with an opening brace, add one more level of indentation
            if current_line.strip().endswith('{'):
                indentation += "    "
            
            super().keyPressEvent(event)
            self.insertPlainText(indentation)
            return

        super().keyPressEvent(event)


class CppSyntaxHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlightingRules = []

        keywordFormat = QTextCharFormat()
        keywordFormat.setForeground(QColor(KEYWORD_COLOR))
        keywords = ["int", "return", "if", "else", "for", "while", "class", "public", "private", "protected", "void", "namespace", "using", "auto"]
        for word in keywords:
            pattern = r"\b" + word + r"\b"
            self.highlightingRules.append((pattern, keywordFormat))

        stdFormat = QTextCharFormat()
        stdFormat.setForeground(QColor(TEXT_MAIN))
        self.highlightingRules.append((r"\bstd::\w+\b", stdFormat))

        stringFormat = QTextCharFormat()
        stringFormat.setForeground(QColor(PINK))
        self.highlightingRules.append((r'".*"', stringFormat))
        self.highlightingRules.append((r"\b[0-9]+\b", stringFormat))

        commentFormat = QTextCharFormat()
        commentFormat.setForeground(QColor(TEXT_DIM))
        self.highlightingRules.append((r"//[^\n]*", commentFormat))

        includeFormat = QTextCharFormat()
        includeFormat.setForeground(QColor(TEXT_DIM))
        self.highlightingRules.append((r"#\w+", includeFormat))

        bracketFormat = QTextCharFormat()
        bracketFormat.setForeground(QColor(TEXT_MAIN))
        self.highlightingRules.append((r"[\{\}\(\)\[\]]", bracketFormat))

    def highlightBlock(self, text):
        for pattern, format in self.highlightingRules:
            for match in re.finditer(pattern, text):
                self.setFormat(match.start(), match.end() - match.start(), format)


class CustomFrame(QFrame):
    def __init__(self, title, left_padding=False):
        super().__init__()
        self.setStyleSheet(f"QFrame {{ border: 1px solid {BORDER_COLOR}; background-color: {PANE_BG}; border-radius: 8px; }}")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        self.header = QLabel(f" {title} ")
        self.header.setFont(QFont(FONT_FAMILY, 9, QFont.Weight.Bold))
        self.header.setStyleSheet(f"QLabel {{ background-color: {HEADER_BG}; color: {PINK}; border: none; border-bottom: 1px solid {BORDER_COLOR}; padding: 8px 15px; border-top-left-radius: 7px; border-top-right-radius: 7px; }}")
        self.layout.addWidget(self.header)
            
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        pad = 20 if left_padding else 10
        self.content_layout.setContentsMargins(pad, pad, pad, pad)
        self.content_widget.setStyleSheet(f"QWidget {{ border: none; background-color: transparent; border-bottom-left-radius: 7px; border-bottom-right-radius: 7px; }}")
        self.layout.addWidget(self.content_widget)

    def set_title(self, title):
        self.header.setText(f" {title} ")

class ASTWorker(QThread):
    finished = pyqtSignal(list)
    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path
    def run(self):
        try:
            ast_raw = extract_ast(self.file_path)
            if ast_raw:
                ast_tree = parse_ast_to_tree(ast_raw, self.file_path)
                self.finished.emit(ast_tree)
            else:
                self.finished.emit([])
        except Exception:
            self.finished.emit([])


class CompilerWorker(QThread):
    finished = pyqtSignal(str, str, int)

    def __init__(self, cmd):
        super().__init__()
        self.cmd = cmd
        self.wall_time = 0.0
        self.cpu_time = 0.0
        self.rss_mb = 0.0

    def run(self):
        try:
            result, wall_time, cpu_time, rss_mb = run_command_with_wait4(self.cmd)
            self.wall_time = wall_time
            self.cpu_time = cpu_time
            self.rss_mb = rss_mb
            self.finished.emit(result.stdout, result.stderr, result.returncode)
        except Exception as e:
            self.finished.emit("", str(e), -1)

class RunnerWorker(QThread):
    finished = pyqtSignal(str, str, int)

    def __init__(self, cmd):
        super().__init__()
        self.cmd = cmd

    def run(self):
        try:
            result = subprocess.run(self.cmd, capture_output=True, text=True, timeout=5)
            self.finished.emit(result.stdout, result.stderr, result.returncode)
        except subprocess.TimeoutExpired as e:
            self.finished.emit(e.stdout.decode() if e.stdout else "", "Timeout expired after 5s", -1)
        except Exception as e:
            self.finished.emit("", str(e), -1)

class SyntaxWorker(QThread):
    finished = pyqtSignal(list)
    
    def __init__(self, code, file_path):
        super().__init__()
        self.code = code
        self.file_path = file_path

    def run(self):
        try:
            from compiler_runner import _sanitize_code
            if not _sanitize_code(self.code):
                self.finished.emit([{
                    "line": 1,
                    "column": 1,
                    "error_type": "error",
                    "message": "Security Error: Malicious command injection or forbidden system call detected."
                }])
                return
            
            import tempfile, os, subprocess, re
            
            dir_name = os.path.dirname(os.path.abspath(self.file_path)) if self.file_path else tempfile.gettempdir()
            fd, temp_path = tempfile.mkstemp(suffix=".cpp", dir=dir_name)
            
            with os.fdopen(fd, 'w') as f:
                f.write(self.code)
                
            res = subprocess.run(
                ["g++", "-fsyntax-only", "-std=c++17", temp_path],
                capture_output=True,
                text=True
            )
            
            errors = []
            pattern = r"(.+):(\d+):(\d+):\s+(error|warning):\s+(.*)"
            for line in res.stderr.splitlines():
                match = re.match(pattern, line)
                if match:
                    if temp_path in match.group(1) or os.path.basename(temp_path) in match.group(1):
                        errors.append({
                            "line": int(match.group(2)),
                            "column": int(match.group(3)),
                            "error_type": match.group(4),
                            "message": match.group(5)
                        })
            
            os.remove(temp_path)
            self.finished.emit(errors)
        except Exception as e:
            self.finished.emit([])
            try:
                if 'temp_path' in locals() and os.path.exists(temp_path):
                    os.remove(temp_path)
            except:
                pass


class ASTViewerDialog(QDialog):
    def __init__(self, ast_tree, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AST EXPLORER :: ARCHITECTURE VIEW")
        self.resize(1000, 700)
        self.setStyleSheet(f"QDialog {{ background-color: {BG_COLOR}; }}")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        
        label = QLabel("ABSTRACT SYNTAX TREE")
        label.setFont(QFont(FONT_FAMILY, 14, QFont.Weight.Bold))
        label.setStyleSheet(f"color: {PINK}; margin-bottom: 10px;")
        layout.addWidget(label)

        self.tree = QTreeWidget()
        self.tree.setStyle(QStyleFactory.create("windows"))
        self.tree.setHeaderLabels(["NODE TYPE", "DETAILS / SOURCE"])
        self.tree.setColumnWidth(0, 300)
        self.tree.setAlternatingRowColors(True)
        self.tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {PANE_BG};
                color: {TEXT_MAIN};
                border: 1px solid {BORDER_COLOR};
                font-family: {FONT_FAMILY};
                font-size: 12px;
                alternate-background-color: {BG_COLOR};
            }}
            QHeaderView::section {{
                background-color: {HEADER_BG};
                color: {PINK};
                border: 1px solid {BORDER_COLOR};
                padding: 10px;
                font-weight: bold;
            }}
            QTreeWidget::item {{
                padding: 5px;
                border-bottom: 1px solid {HEADER_BG};
            }}
            QTreeWidget::item:selected {{
                background-color: {BORDER_COLOR};
                color: {PINK};
            }}
        """)
        
        self._populate(ast_tree, self.tree.invisibleRootItem())
        
        layout.addWidget(self.tree)
        
        btn_close = StyledButton(" CLOSE VIEWER ", "solid_pink")
        btn_close.clicked.connect(self.close)
        btn_close.setFixedWidth(150)
        layout.addWidget(btn_close, 0, Qt.AlignmentFlag.AlignCenter)

    def _populate(self, nodes, parent_item):
        for n in nodes:
            item = QTreeWidgetItem(parent_item)
            item.setText(0, n["type"])
            item.setText(1, n["details"])
            
            if "Decl" in n["type"]:
                item.setForeground(0, QColor(PINK))
            elif "Stmt" in n["type"]:
                item.setForeground(0, QColor(KEYWORD_COLOR))
            elif "Expr" in n["type"]:
                item.setForeground(0, QColor(TEXT_MAIN))
            else:
                item.setForeground(0, QColor(TEXT_DIM))
                
            item.setForeground(1, QColor(TEXT_DIM))
            
            if n["children"]:
                self._populate(n["children"], item)


class TerminalDisplay(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.process = None 
        self.prompt_pos = 0
        self.setFont(QFont(FONT_FAMILY, 11))
        self.setStyleSheet(f"QTextEdit {{ background-color: transparent; border: 1px solid {BORDER_COLOR}; border-radius: 4px; color: {TEXT_MAIN}; line-height: 1.5; }}")

    def append_output(self, text, is_html=False):
        self.setReadOnly(False)
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.setTextCursor(cursor)
        if is_html:
            self.insertHtml(text)
        else:
            self.insertPlainText(text)
        self.prompt_pos = self.document().characterCount() - 1
        self.ensureCursorVisible()
        if not (self.process and self.process.state() == QProcess.ProcessState.Running):
            self.setReadOnly(True)

    def keyPressEvent(self, event):
        if event.key() in [Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right, 
                           Qt.Key.Key_PageUp, Qt.Key.Key_PageDown, Qt.Key.Key_Home, Qt.Key.Key_End]:
            if event.key() == Qt.Key.Key_Left and self.textCursor().position() <= self.prompt_pos:
                return
            super().keyPressEvent(event)
            return

        if (event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)):
            if event.key() in [Qt.Key.Key_C, Qt.Key.Key_A]:
                super().keyPressEvent(event)
                return

        if not self.process or self.process.state() != QProcess.ProcessState.Running:
            return

        cursor = self.textCursor()
        if cursor.position() < self.prompt_pos:
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.setTextCursor(cursor)

        if event.key() == Qt.Key.Key_Return:
            cursor.setPosition(self.prompt_pos)
            cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
            text = cursor.selectedText().replace('\u2029', '\n')
            self.process.write((text + "\n").encode())
            
            self.setReadOnly(False)
            super().keyPressEvent(event)
            self.prompt_pos = self.document().characterCount() - 1
            self.ensureCursorVisible()
        elif event.key() == Qt.Key.Key_Backspace:
            if cursor.position() > self.prompt_pos:
                self.setReadOnly(False)
                super().keyPressEvent(event)
        else:
            if event.text():
                self.setReadOnly(False)
                super().keyPressEvent(event)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if self.process and self.process.state() == QProcess.ProcessState.Running:
            if self.textCursor().position() < self.prompt_pos:
                cursor = self.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.End)
                self.setTextCursor(cursor)


class _KeywordClassifier:
    """
    Lightweight fallback classifier using keyword matching.
    Used when the ML model isn't trained yet.
    """
    _RULES = [
        ("missing_include",  ["'std::", "was not declared", "no member named", "include"]),
        ("syntax_error",     ["expected ';'", "expected ')'", "expected '{'", "parse error", "stray"]),
        ("name_resolution",  ["undeclared", "not declared", "undefined", "cannot find"]),
        ("type_error",       ["cannot convert", "invalid conversion", "no matching function", "incompatible"]),
        ("return_type_error",["return type", "no return", "control reaches end"]),
        ("redefinition",     ["redefinition", "already defined", "multiple definition"]),
        ("linker_error",     ["undefined reference", "linker", "ld returned"]),
        ("access_error",     ["is private", "is protected", "inaccessible"]),
    ]

    def predict(self, message: str, ast_node: str = "") -> tuple:
        msg_lower = (message + " " + ast_node).lower()
        for category, keywords in self._RULES:
            if any(kw in msg_lower for kw in keywords):
                return category, 0.8
        return "other", 0.5


class UserGuidanceDialog(QDialog):
    """
    Shown when the healer exhausts all 3 attempts without fixing the error.
    Offers three actions: Edit Manually, Skip This Error, Give Me a Hint.
    """
    EDIT_MANUALLY = 1
    SKIP          = 2
    GIVE_HINT     = 3

    def __init__(self, history: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚕ Auto-Heal — Guidance Needed")
        self.setModal(True)
        self.setMinimumWidth(500)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {BG_COLOR};
                color: {TEXT_MAIN};
                font-family: {FONT_FAMILY};
            }}
            QLabel {{ color: {TEXT_MAIN}; font-family: {FONT_FAMILY}; }}
            QLineEdit {{
                background-color: {PANE_BG};
                color: {TEXT_MAIN};
                border: 1px solid {BORDER_COLOR};
                border-radius: 4px;
                padding: 6px;
                font-family: {FONT_FAMILY};
            }}
        """)
        self._result_code = self.SKIP
        self._hint = ""

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # Header
        warn = QLabel("⚠️  I tried 3 fixes but couldn't resolve this error.")
        warn.setStyleSheet(f"color: {YELLOW}; font-size: 13px; font-weight: bold;")
        layout.addWidget(warn)

        # Last error detail
        last_err = next((h.get("error") for h in reversed(history) if h.get("error")), {})
        raw_msg = last_err.get("message", "Unknown error")
        cat     = last_err.get("category", "other")
        line_no = last_err.get("line")
        line_str = str(line_no) if line_no is not None and str(line_no) != "?" else ("No specific line (linker error)" if cat == "linker_error" else "No specific line")
        suggestion = last_err.get("suggestion", "")

        layout.addWidget(QLabel(f"<b>Error:</b> {raw_msg}"))
        layout.addWidget(QLabel(f"<b>Category:</b> {cat}  |  <b>Line:</b> {line_str}"))

        if suggestion:
            suggestion_title = QLabel("<b>Suggested fix:</b>")
            layout.addWidget(suggestion_title)
            suggestion_box = QLabel(suggestion.replace("\n", "<br>"))
            suggestion_box.setTextFormat(Qt.TextFormat.RichText)
            suggestion_box.setWordWrap(True)
            suggestion_box.setStyleSheet(
                f"background-color: {PANE_BG}; border: 1px solid {BORDER_COLOR}; "
                f"border-radius: 4px; padding: 8px; color: {TEXT_MAIN};"
            )
            layout.addWidget(suggestion_box)

        # What was tried
        tried_label = QLabel("<b>What I tried:</b>")
        layout.addWidget(tried_label)
        for h in history:
            if h.get("patch"):
                attempt_lbl = QLabel(f"  • Attempt {h['attempt']}: applied a patch for [{h['error'].get('category', '?').upper()}]")
                attempt_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
                layout.addWidget(attempt_lbl)
            elif h.get("reason"):
                attempt_lbl = QLabel(f"  • Attempt {h.get('attempt', '?')}: {h['reason']}")
                attempt_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
                layout.addWidget(attempt_lbl)

        # Hint input
        hint_label = QLabel("→ Give me a hint (optional):")
        layout.addWidget(hint_label)
        self._hint_input = QLineEdit()
        self._hint_input.setPlaceholderText("e.g.  the variable x should be a pointer")
        layout.addWidget(self._hint_input)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_edit = StyledButton("✏️  Edit Manually", "outline_dim")
        btn_skip = StyledButton("⏭  Skip This Error", "outline_dim")
        btn_hint = StyledButton("💡  Give Hint & Retry", "solid_pink")
        btn_edit.clicked.connect(self._do_edit)
        btn_skip.clicked.connect(self._do_skip)
        btn_hint.clicked.connect(self._do_hint)
        btn_row.addWidget(btn_edit)
        btn_row.addWidget(btn_skip)
        btn_row.addWidget(btn_hint)
        layout.addLayout(btn_row)

    def _do_edit(self):
        self._result_code = self.EDIT_MANUALLY
        self.done(self.EDIT_MANUALLY)

    def _do_skip(self):
        self._result_code = self.SKIP
        self.done(self.SKIP)

    def _do_hint(self):
        self._hint = self._hint_input.text().strip()
        self._result_code = self.GIVE_HINT
        self.done(self.GIVE_HINT)

    def hint_text(self) -> str:
        return self._hint


class Sidebar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(54)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(5, 10, 5, 10)
        self.layout.setSpacing(10)
        
        # Side buttons - Emoji Only
        self.btn1 = StyledButton("📁", "outline_dim")
        self.btn2 = StyledButton("🕒", "outline_dim")
        self.btn3 = StyledButton("⚡", "outline_dim")
        self.btn4 = StyledButton("↔", "outline_dim")
        self.btn5 = StyledButton("🛡", "outline_dim")
        self.btn6 = StyledButton("🔀", "outline_dim")
        self.btn7 = StyledButton("🤖", "outline_dim")
        self.btn8 = StyledButton("📝", "outline_dim")

        self.buttons = [self.btn1, self.btn2, self.btn3, self.btn4, self.btn5, self.btn6, self.btn7, self.btn8]
        self.tooltips = [
            "Editor / Source Code",
            "Abstract Syntax Tree Explorer",
            "Energy & Resource Profiler",
            "Function Call Graph",
            "Security Vulnerability Scanner",
            "Control Flow Graph",
            "Agent Execution Trace",
            "Patch Review Panel"
        ]
        
        for btn, tip in zip(self.buttons, self.tooltips):
            btn.setFixedWidth(44)
            btn.setFixedHeight(44)
            btn.setFont(QFont(FONT_FAMILY, 15))
            btn.setToolTip(tip)
            self.layout.addWidget(btn)

        self.layout.addStretch()
        
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {HEADER_BG};
                border-right: 1px solid {BORDER_COLOR};
                border-top-left-radius: 0px;
                border-bottom-left-radius: 6px;
            }}
            QToolTip {{
                background-color: #1a1f36;
                color: #ffffff;
                border: 1px solid {PINK};
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 12px;
                font-family: {FONT_FAMILY};
                font-weight: normal;
            }}
        """)
        self.set_active_index(0)

    def set_active_index(self, index: int):
        self.active_index = index
        for i, (btn, tip) in enumerate(zip(self.buttons, self.tooltips)):
            is_active = (i == index)
            btn.set_active(is_active)
            status_text = " (Active View)" if is_active else ""
            btn.setToolTip(f"{tip}{status_text}")


class ASTPage(CustomFrame):
    def __init__(self, parent=None):
        super().__init__("ABSTRACT SYNTAX TREE EXPLORER", left_padding=True)
        
        self.tree = QTreeWidget()
        self.tree.setStyle(QStyleFactory.create("windows"))
        self.tree.setHeaderLabels(["NODE TYPE", "DETAILS / SOURCE"])
        self.tree.setColumnWidth(0, 300)
        self.tree.setAlternatingRowColors(True)
        self.tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {PANE_BG};
                color: {TEXT_MAIN};
                border: none;
                font-family: {FONT_FAMILY};
                font-size: 13px;
                alternate-background-color: {BG_COLOR};
            }}
            QHeaderView::section {{
                background-color: {HEADER_BG};
                color: {PINK};
                border: none;
                border-bottom: 1px solid {BORDER_COLOR};
                padding: 10px;
                font-weight: bold;
            }}
            QTreeWidget::item {{
                padding: 8px;
            }}
            QTreeWidget::item:selected {{
                background-color: {BG_COLOR};
                color: {PINK};
            }}
        """)
        self.content_layout.addWidget(self.tree)

    def update_tree(self, ast_tree):
        self.tree.clear()
        self._populate(ast_tree, self.tree.invisibleRootItem())
        self.tree.expandAll()

    def _populate(self, nodes, parent_item):
        for n in nodes:
            item = QTreeWidgetItem(parent_item)
            item.setText(0, n["type"])
            item.setText(1, n["details"])
            
            if "Decl" in n["type"]:
                item.setForeground(0, QColor(PINK))
            elif "Stmt" in n["type"]:
                item.setForeground(0, QColor(KEYWORD_COLOR))
            elif "Expr" in n["type"]:
                item.setForeground(0, QColor(TEXT_MAIN))
            else:
                item.setForeground(0, QColor(TEXT_DIM))
            
            item.setForeground(1, QColor(TEXT_DIM))
            
            if "children" in n and n["children"]:
                self._populate(n["children"], item)


class EnergyPage(CustomFrame):
    def __init__(self, parent=None):
        super().__init__("ENERGY & RESOURCE TELEMETRY", left_padding=True)
        
        self.desc = QLabel("Energy & resource telemetry: duration, CPU/memory, power estimate, RAPL")
        self.desc.setStyleSheet(f"color: {PINK}; font-weight: bold; font-size: 14px;")
        self.content_layout.addWidget(self.desc)

        self.history = []

        self.metric_row = QWidget()
        metric_layout = QHBoxLayout(self.metric_row)
        metric_layout.setContentsMargins(0, 0, 0, 0)
        metric_layout.setSpacing(10)

        _, rapl_initial = _read_rapl_status()
        rapl_tag = "[measured]" if (platform.system() != "Darwin" and os.path.isdir("/sys/class/powercap")) else "[unavailable]"

        consts = _get_configured_telemetry_constants()
        grid_intensity = consts.grid_intensity
        assumed_tdp = consts.assumed_tdp
        grid_region = consts.grid_region
        grid_source = consts.grid_source
        region_short = grid_region.split("(")[0].strip() if "(" in grid_region else grid_region
        grid_label = f"assumed grid: {region_short} ~{int(grid_intensity)} g/kWh"

        self.time_value = self._metric_label("Execution Time", "No run yet", "[measured]", YELLOW)
        self.cpu_value = self._metric_label("CPU & Memory", "No run yet", "[measured]", PINK)
        self.energy_value = self._metric_label(f"Estimated Energy & CO₂ ({grid_label})", "No run yet", "[estimated]", GREEN)
        self.rapl_value = self._metric_label("RAPL Hardware", rapl_initial, rapl_tag, TEXT_MAIN)

        for label in [self.time_value, self.cpu_value, self.energy_value, self.rapl_value]:
            metric_layout.addWidget(label)
        self.content_layout.addWidget(self.metric_row)

        self.graph = MetricsGraph()
        self.graph.setStyleSheet(f"""
            MetricsGraph {{
                background-color: {BG_COLOR};
                border: 1px solid {BORDER_COLOR};
                border-radius: 6px;
            }}
        """)
        self.content_layout.addWidget(self.graph, 1)

        self.notes = QTextBrowser()
        self.notes.setMaximumHeight(145)
        self.notes.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {BG_COLOR};
                border: 1px solid {BORDER_COLOR};
                border-radius: 6px;
                color: {TEXT_MAIN};
                font-family: {FONT_FAMILY};
                font-size: 12px;
                padding: 10px;
            }}
        """)
        self.content_layout.addWidget(self.notes)
        
        self.btn_download_csv = StyledButton(" 📥 DOWNLOAD CSV REPORT ", "outline_dim")
        self.btn_download_csv.clicked.connect(self._download_csv)
        self.content_layout.addWidget(self.btn_download_csv, 0, Qt.AlignmentFlag.AlignRight)

        self.notes.setHtml(f"""
            <b style="color:{PINK};">Telemetry Configuration & Real Data Sources</b><br>
            • <b>Measurement Status:</b> Idle — waiting for compile or execution run.<br>
            • <b>Telemetry Sources:</b> Per-process <code>os.wait4(pid, 0)</code> [measured] + active package TDP &times; CPU time [estimated].<br>
            • <b>Assumed Package TDP:</b> {assumed_tdp:.1f} W (active package load from <code>config.yaml</code>).<br>
            • <b>Grid Carbon Intensity:</b> {grid_intensity:.1f} gCO₂/kWh ({grid_region}; {grid_source} from <code>config.yaml</code>).<br>
            • <b>RAPL Interface:</b> {rapl_initial} <code>{rapl_tag}</code>.
        """)

    def _metric_label(self, title, value, tag, color):
        tag_color = GREEN if "measured" in tag else (YELLOW if "estimated" in tag else TEXT_DIM)
        label = QLabel(
            f"<div style='line-height:130%;'>"
            f"<span style='color:{TEXT_DIM}; font-size:11px;'>{title}</span> "
            f"<span style='color:{tag_color}; font-size:9px; font-weight:bold;'>{tag}</span><br>"
            f"<b style='color:{color}; font-size:16px;'>{value}</b>"
            f"</div>"
        )
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setMinimumHeight(76)
        label.setStyleSheet(f"""
            QLabel {{
                background-color: {BG_COLOR};
                border: 1px solid {BORDER_COLOR};
                border-radius: 6px;
                padding: 8px;
                font-family: {FONT_FAMILY};
            }}
        """)
        return label

    def _update_card(self, label, title, value, tag, color):
        tag_color = GREEN if "measured" in tag else (YELLOW if "estimated" in tag else TEXT_DIM)
        label.setText(
            f"<div style='line-height:130%;'>"
            f"<span style='color:{TEXT_DIM}; font-size:11px;'>{title}</span> "
            f"<span style='color:{tag_color}; font-size:9px; font-weight:bold;'>{tag}</span><br>"
            f"<b style='color:{color}; font-size:16px;'>{value}</b>"
            f"</div>"
        )

    def display_run_telemetry(self, record: dict):
        self.history.append(record)
        wall_s = record.get("wall_s", 0.0)
        cpu_s = record.get("cpu_s", 0.0)
        rss_mb = record.get("rss_mb", 0.0)
        energy_mwh = record.get("energy_mwh", 0.0)
        emissions_mg = record.get("emissions_mg", 0.0)
        action = record.get("action", "Run")

        _, rapl_status = _read_rapl_status()
        rapl_tag = "[measured]" if (platform.system() != "Darwin" and os.path.isdir("/sys/class/powercap")) else "[unavailable]"

        consts = _get_configured_telemetry_constants()
        grid_intensity = consts.grid_intensity
        assumed_tdp = consts.assumed_tdp
        grid_region = consts.grid_region
        grid_source = consts.grid_source
        region_short = grid_region.split("(")[0].strip() if "(" in grid_region else grid_region
        grid_label = f"assumed grid: {region_short} ~{int(grid_intensity)} g/kWh"

        self._update_card(self.time_value, "Execution Time", f"{wall_s:.3f} s", "[measured]", YELLOW)
        self._update_card(self.cpu_value, "CPU & Memory", f"{cpu_s:.3f}s | {rss_mb:.1f}MB", "[measured]", PINK)
        self._update_card(self.energy_value, f"Estimated Energy & CO₂ ({grid_label})", f"{energy_mwh:.3f}mWh | {emissions_mg:.3f}mg", "[estimated]", GREEN)
        self._update_card(self.rapl_value, "RAPL Hardware", rapl_status, rapl_tag, TEXT_MAIN)

        self.graph.add_run(wall_s, cpu_s, energy_mwh)

        self.notes.setHtml(f"""
            <b style="color:{PINK};">Last Completed Action: {action}</b><br>
            • <b>Wall Clock Duration:</b> {wall_s:.4f} s <code>[measured via perf_counter]</code><br>
            • <b>Child CPU Time:</b> {cpu_s:.4f} s &nbsp;|&nbsp; <b>Peak RSS:</b> {rss_mb:.2f} MB <code>[measured per-run via os.wait4]</code><br>
            • <b>Estimated Energy:</b> {energy_mwh:.4f} mWh (active TDP = {assumed_tdp:.1f} W from <code>config.yaml</code>) <code>[estimated]</code><br>
            • <b>Estimated Carbon:</b> {emissions_mg:.4f} mg CO₂ (assumed grid: {grid_region} ~{int(grid_intensity)} g/kWh; {grid_source}) <code>[estimated]</code><br>
            • <b>RAPL:</b> {rapl_status} <code>{rapl_tag}</code>
        """)

    def update_metrics(self, power_mw, carbon_mg_per_wh, execution_time, rapl_text, note):
        """Backward-compatible update hook."""
        if execution_time > 0:
            record = {
                "action": "Execution",
                "wall_s": execution_time,
                "cpu_s": execution_time,
                "rss_mb": 0.0,
                "energy_mwh": power_mw,
                "emissions_mg": carbon_mg_per_wh * power_mw if power_mw > 0 else 0.0,
            }
            self.display_run_telemetry(record)

    def _download_csv(self):
        if not self.history:
            QMessageBox.information(self, "No Data", "No execution telemetry recorded yet. Compile or run code first.")
            return

        save_path, _ = QFileDialog.getSaveFileName(self, "Save Telemetry Report", "energy_telemetry_report.csv", "CSV Files (*.csv)")
        if not save_path:
            return

        import csv
        try:
            grid_intensity, assumed_tdp = _get_configured_telemetry_constants()
            with open(save_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "run_index", "action", "timestamp", "wall_duration_seconds",
                    "cpu_time_seconds", "peak_rss_mb", "estimated_energy_mwh",
                    "estimated_emissions_mg_co2", "rapl_status",
                    "grid_carbon_intensity_g_per_kwh", "assumed_package_tdp_watts"
                ])
                for idx, r in enumerate(self.history, 1):
                    _, rapl_status = _read_rapl_status()
                    writer.writerow([
                        idx,
                        r.get("action", "Run"),
                        r.get("timestamp", time.time()),
                        f"{r.get('wall_s', 0.0):.4f}",
                        f"{r.get('cpu_s', 0.0):.4f}",
                        f"{r.get('rss_mb', 0.0):.2f}",
                        f"{r.get('energy_mwh', 0.0):.4f}",
                        f"{r.get('emissions_mg', 0.0):.4f}",
                        rapl_status,
                        grid_intensity,
                        assumed_tdp
                    ])
            QMessageBox.information(self, "Export Complete", f"Telemetry report successfully saved to:\n{save_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save CSV:\n{e}")

class CallGraphPage(CustomFrame):
    def __init__(self, parent=None):
        super().__init__("FUNCTION CALL GRAPH :: MODULE RELATIONSHIPS", left_padding=True)
        self.summary = QLabel("Compile or open this page to map functions, internal calls, external calls, and included modules.")
        self.summary.setStyleSheet(f"color: {TEXT_DIM}; font-family: {FONT_FAMILY};")
        self.summary.setWordWrap(True)
        self.content_layout.addWidget(self.summary)

        self.graph = CallGraphWidget()
        self.graph.setStyleSheet(f"background-color: {PANE_BG}; border: 1px solid {BORDER_COLOR}; border-radius: 6px;")
        self.content_layout.addWidget(self.graph, 1)

    def update_from_code(self, code):
        functions, edges, external_calls, modules = _extract_cpp_call_graph(code)
        self.graph.update_graph(functions, edges, external_calls, modules)
        self.summary.setText(
            f"Functions: {len(functions)} | Internal calls: {len(edges)} | "
            f"External calls: {len(external_calls)} | Modules/includes: {len(modules)}"
        )


class CFGWidget(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(420)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QColor(PANE_BG))

    def update_graph(self, functions_data):
        self.scene.clear()
        if not functions_data:
            t = self.scene.addText("No functions found for CFG analysis.")
            t.setDefaultTextColor(QColor(TEXT_DIM))
            t.setFont(QFont(FONT_FAMILY, 12))
            return

        # Simple vertical layout for demo
        y_offset = 50
        margin_x = 100
        
        for func in functions_data:
            nodes_data = func["nodes"]
            edges_data = func["edges"]
            
            node_map = {}
            node_w, node_h = 180, 50
            
            # Label for function
            f_lbl = self.scene.addText(f"FUNCTION: {func['name']}")
            f_lbl.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.Bold))
            f_lbl.setDefaultTextColor(QColor(PINK))
            f_lbl.setPos(margin_x, y_offset - 30)
            
            # Simple linear vertical layout for nodes
            for i, n in enumerate(nodes_data):
                color = {
                    "entry": QColor("#e1f5fe"),
                    "exit": QColor("#fce4ec"),
                    "branch": QColor("#fff9c4"),
                    "stmt": QColor("#ffffff")
                }.get(n["type"], QColor("#ffffff"))
                
                border = {
                    "entry": QColor("#03a9f4"),
                    "exit": QColor("#f06292"),
                    "branch": QColor("#fbc02d"),
                    "stmt": QColor(BORDER_COLOR)
                }.get(n["type"], QColor(BORDER_COLOR))
                
                # if branch type, make it diamond-ish or just distinct
                node = GraphNode(n["label"], margin_x, y_offset, node_w, node_h, border, color)
                self.scene.addItem(node)
                node_map[n["id"]] = node
                y_offset += 80
            
            for start_id, end_id in edges_data:
                if start_id in node_map and end_id in node_map:
                    edge = GraphEdge(node_map[start_id], node_map[end_id], QColor(TEXT_DIM))
                    self.scene.addItem(edge)
            
            y_offset += 50 # gap between functions

class CFGPage(CustomFrame):
    def __init__(self, parent=None):
        super().__init__("CONTROL FLOW GRAPH :: EXECUTION PATHS", left_padding=True)
        self.summary = QLabel("Visualizing the logical structure and execution paths of your C++ code.")
        self.summary.setStyleSheet(f"color: {TEXT_DIM}; font-family: {FONT_FAMILY};")
        self.content_layout.addWidget(self.summary)
        
        self.graph = CFGWidget()
        self.graph.setStyleSheet(f"background-color: {PANE_BG}; border: 1px solid {BORDER_COLOR}; border-radius: 6px;")
        self.content_layout.addWidget(self.graph, 1)

    def update_from_code(self, code):
        data = _extract_cpp_cfg(code)
        self.graph.update_graph(data)
        self.summary.setText(f"Functions Analyzed: {len(data)} | Total Nodes: {sum(len(f['nodes']) for f in data)}")


class FilterTabButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(34)
        self.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.Bold))
        self._active = False
        self._apply_style(False)

    def setActive(self, active: bool):
        self._active = active
        self.setChecked(active)
        self._apply_style(active)

    def _apply_style(self, active: bool):
        if active:
            self.setStyleSheet("""
                QPushButton {
                    background-color: #6C5CE7;
                    color: white;
                    border: none;
                    border-radius: 16px;
                    padding: 8px 14px;
                }
                QPushButton:hover {
                    background-color: #7B6BEE;
                }
            """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background-color: #F7F5FF;
                    color: #4F46E5;
                    border: 1px solid #E1DAFF;
                    border-radius: 16px;
                    padding: 8px 14px;
                }
                QPushButton:hover {
                    background-color: #EEE9FF;
                    border: 1px solid #C7B9FF;
                }
            """)


class SecurityCard(QFrame):
    def __init__(self, finding: dict, severity_color: str, parent=None):
        super().__init__(parent)
        self.finding = finding
        self.severity_color = severity_color
        self.expanded = True

        self.setObjectName("SecurityCard")
        self.setMouseTracking(True)
        self.setStyleSheet("""
            QFrame#SecurityCard {
                background-color: #ffffff;
                border: 1px solid #EEF0FF;
                border-radius: 14px;
            }
        """)

        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(18)
        self.shadow.setOffset(0, 3)
        self.shadow.setColor(QColor(0, 0, 0, 18))
        self.setGraphicsEffect(self.shadow)
        self.shadow_anim = QPropertyAnimation(self.shadow, b"blurRadius", self)
        self.shadow_anim.setDuration(200)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.strip = QFrame()
        self.strip.setFixedWidth(6)
        self.strip.setStyleSheet(f"background-color: {severity_color}; border: none; border-top-left-radius: 14px; border-bottom-left-radius: 14px;")
        outer.addWidget(self.strip)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(16, 14, 16, 14)
        body_layout.setSpacing(10)
        outer.addWidget(body, 1)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        title_box = QVBoxLayout()
        title_box.setSpacing(3)
        vuln = finding.get("vulnerability_type", "Security Issue")
        cwe_id = finding.get("cwe")
        if not cwe_id and vuln:
            try:
                cwe_id = get_cwe_for_vulnerability(vuln)
            except Exception:
                cwe_id = None

        title_text = f"⚠️ {html.escape(vuln)} ({html.escape(cwe_id)})" if cwe_id else f"⚠️ {html.escape(vuln)}"
        self.title_label = QLabel(title_text)
        self.title_label.setStyleSheet("color: #1F163A; font-size: 14px; font-weight: 700;")
        self.title_label.setWordWrap(True)
        self.title_label.setTextFormat(Qt.TextFormat.RichText)
        title_box.addWidget(self.title_label)

        loc = self._location_text(finding)
        self.meta_label = QLabel(f"📄 {html.escape(loc)}")
        self.meta_label.setStyleSheet("color: #8B90A6; font-size: 11px;")
        self.meta_label.setWordWrap(True)
        self.meta_label.setTextFormat(Qt.TextFormat.RichText)
        title_box.addWidget(self.meta_label)
        top_row.addLayout(title_box, 1)

        # CWE ID Badge
        if cwe_id:
            cwe_badge = QLabel(cwe_id)
            cwe_badge.setStyleSheet("""
                QLabel {
                    background-color: #6C5CE7;
                    color: white;
                    border-radius: 999px;
                    padding: 5px 10px;
                    font-size: 10px;
                    font-weight: 700;
                    letter-spacing: 0px;
                }
            """)
            cwe_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            top_row.addWidget(cwe_badge, 0, Qt.AlignmentFlag.AlignTop)

        # Gate 4 Status Badge (if introduced/blocked or unmasked by patch)
        if finding.get("blocked_by_gate4") or finding.get("introduced_by_patch"):
            blocked_badge = QLabel("⛔ BLOCKED BY GATE 4")
            blocked_badge.setStyleSheet("""
                QLabel {
                    background-color: #D63031;
                    color: white;
                    border-radius: 999px;
                    padding: 5px 10px;
                    font-size: 10px;
                    font-weight: 700;
                    letter-spacing: 0px;
                }
            """)
            blocked_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            top_row.addWidget(blocked_badge, 0, Qt.AlignmentFlag.AlignTop)
        elif finding.get("unmasked_by_patch"):
            unmasked_badge = QLabel("ℹ️ UNMASKED")
            unmasked_badge.setStyleSheet("""
                QLabel {
                    background-color: #E17055;
                    color: white;
                    border-radius: 999px;
                    padding: 5px 10px;
                    font-size: 10px;
                    font-weight: 700;
                    letter-spacing: 0px;
                }
            """)
            unmasked_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            top_row.addWidget(unmasked_badge, 0, Qt.AlignmentFlag.AlignTop)

        badge = QLabel(finding.get("severity", "Low").upper())
        badge_color = self.severity_color
        badge.setStyleSheet(f"""
            QLabel {{
                background-color: {badge_color};
                color: white;
                border-radius: 999px;
                padding: 5px 10px;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 0px;
            }}
        """)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)

        body_layout.addLayout(top_row)

        desc_label = QLabel("DESCRIPTION")
        desc_label.setStyleSheet("color: #8B90A6; font-size: 10px; font-weight: 700; letter-spacing: 0px;")
        body_layout.addWidget(desc_label)

        self.description = QLabel(html.escape(finding.get("description", "")))
        self.description.setWordWrap(True)
        self.description.setStyleSheet("color: #1F163A; font-size: 12px;")
        self.description.setTextFormat(Qt.TextFormat.RichText)
        body_layout.addWidget(self.description)

        rec_label = QLabel("RECOMMENDATION")
        rec_label.setStyleSheet("color: #8B90A6; font-size: 10px; font-weight: 700;")
        body_layout.addWidget(rec_label)

        self.recommendation_box = QFrame()
        self.recommendation_box.setStyleSheet("""
            QFrame {
                background-color: #F6F1FF;
                border: 1px solid #E8DBFF;
                border-radius: 12px;
            }
        """)
        rec_layout = QVBoxLayout(self.recommendation_box)
        rec_layout.setContentsMargins(12, 10, 12, 10)
        rec_layout.setSpacing(4)
        self.recommendation = QLabel(f"🛡 {html.escape(finding.get('recommendation', ''))}")
        self.recommendation.setWordWrap(True)
        self.recommendation.setTextFormat(Qt.TextFormat.RichText)
        self.recommendation.setStyleSheet("color: #3F2CA1; font-size: 12px; font-weight: 600;")
        rec_layout.addWidget(self.recommendation)
        body_layout.addWidget(self.recommendation_box)

        self.details_row = QHBoxLayout()
        self.details_row.setSpacing(12)
        self.file_chip = QLabel(f"📄 {html.escape(self._file_only(finding))}")
        self.file_chip.setStyleSheet("color: #6F7591; font-size: 11px;")
        self.file_chip.setWordWrap(True)
        self.file_chip.setTextFormat(Qt.TextFormat.RichText)
        line_val = finding.get('line')
        line_str = f"Line {line_val}" if line_val is not None and str(line_val) != "—" and str(line_val) != "?" else "No specific line"
        self.line_chip = QLabel(line_str)
        self.line_chip.setStyleSheet("color: #6F7591; font-size: 11px;")
        self.source_chip = QLabel(f"Source: {str(finding.get('source', 'static_scan')).replace('_', ' ')}")
        self.cwe_chip = QLabel(f"🏷️ CWE: {cwe_id or '—'}")
        self.cwe_chip.setStyleSheet("color: #6F7591; font-size: 11px;")
        self.details_row.addWidget(self.file_chip, 1)
        self.details_row.addWidget(self.line_chip, 0)
        self.details_row.addWidget(self.cwe_chip, 0)
        self.details_row.addWidget(self.source_chip, 0)
        body_layout.addLayout(self.details_row)

        self.toggle_btn = QPushButton("Details")
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(True)
        self.toggle_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #6C5CE7;
                border: none;
                padding: 0;
                font-size: 11px;
                font-weight: 700;
            }
            QPushButton:hover {
                color: #4F46E5;
            }
        """)
        self.toggle_btn.toggled.connect(self._toggle_details)
        body_layout.addWidget(self.toggle_btn, 0, Qt.AlignmentFlag.AlignRight)

    def _file_only(self, finding):
        path = finding.get("file", "unknown")
        return os.path.basename(path) if path else "unknown"

    def _location_text(self, finding):
        path = finding.get("file", "unknown")
        line = finding.get("line")
        column = finding.get("column")
        if line is not None:
            if column is not None:
                return f"{path}:{line}:{column}"
            return f"{path}:{line}"
        return path

    def _toggle_details(self, checked):
        self.description.setVisible(checked)
        self.recommendation_box.setVisible(checked)
        self.details_row_widget_set_visible(checked)
        self.toggle_btn.setText("Hide" if checked else "Details")

    def details_row_widget_set_visible(self, visible):
        for i in range(self.details_row.count()):
            item = self.details_row.itemAt(i)
            widget = item.widget()
            if widget:
                widget.setVisible(visible)

    def enterEvent(self, event):
        self.shadow_anim.stop()
        self.shadow_anim.setStartValue(self.shadow.blurRadius())
        self.shadow_anim.setEndValue(30)
        self.shadow_anim.start()
        self.shadow.setColor(QColor(108, 92, 231, 42))
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.shadow_anim.stop()
        self.shadow_anim.setStartValue(self.shadow.blurRadius())
        self.shadow_anim.setEndValue(18)
        self.shadow_anim.start()
        self.shadow.setColor(QColor(0, 0, 0, 18))
        super().leaveEvent(event)


class SecurityPage(CustomFrame):
    def __init__(self, parent=None):
        super().__init__("SECURITY ANALYZER :: VULNERABILITY REPORT", left_padding=True)
        self.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #E8DBFF;
                border-radius: 16px;
            }
        """)
        self.header.setStyleSheet("""
            QLabel {
                background-color: #ffffff;
                color: #6C5CE7;
                border: none;
                border-bottom: 1px solid #F0E9FF;
                padding: 10px 16px;
                border-top-left-radius: 15px;
                border-top-right-radius: 15px;
            }
        """)
        self.content_widget.setStyleSheet("QWidget { background-color: #ffffff; }")
        self.content_layout.setContentsMargins(18, 18, 18, 18)
        self.content_layout.setSpacing(14)

        self.findings = []
        self.current_filter = "All"
        self._cards = []
        self.session_gate6_blocked = 0

        self.scope_explanation = (
            "This scans the current source file on disk. Blocked patch attempts (including "
            "malicious candidates rejected before being applied) are shown separately in Patch Review."
        )
        self.header.setToolTip(self.scope_explanation)

        self.header_row = QHBoxLayout()
        self.header_row.setSpacing(12)

        title_box = QVBoxLayout()
        title_box.setSpacing(4)

        summary_title_row = QHBoxLayout()
        summary_title_row.setSpacing(8)
        self.summary = QLabel("0 critical, 0 high, 0 medium, 0 low findings")
        self.summary.setStyleSheet("color: #1F163A; font-size: 18px; font-weight: 800;")
        self.summary.setWordWrap(True)
        summary_title_row.addWidget(self.summary)

        # Info icon clarifying the two panels' scopes (Task 3)
        self.info_icon = QLabel("ℹ️")
        self.info_icon.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.info_icon.setToolTip(self.scope_explanation)
        self.info_icon.setStyleSheet("""
            QLabel {
                font-size: 15px;
                padding: 2px 6px;
                border-radius: 6px;
                background-color: #F1F5F9;
                color: #475569;
            }
            QLabel:hover {
                background-color: #EDE9FE;
                color: #5B21B6;
            }
        """)
        summary_title_row.addWidget(self.info_icon)
        summary_title_row.addStretch()
        title_box.addLayout(summary_title_row)

        self.subsummary = QLabel(
            "Grouped security findings with exact source lines and fix guidance. "
            f"<span style='color: #4F46E5; font-size: 11px;'>ℹ️ {self.scope_explanation}</span>"
        )
        self.subsummary.setStyleSheet("color: #8B90A6; font-size: 12px;")
        self.subsummary.setWordWrap(True)
        self.subsummary.setToolTip(self.scope_explanation)
        title_box.addWidget(self.subsummary)
        self.header_row.addLayout(title_box, 1)

        self.risk_badge = QLabel("Risk Score: 0")
        self.risk_badge.setStyleSheet("""
            QLabel {
                background-color: #F6F1FF;
                color: #6C5CE7;
                border: 1px solid #E8DBFF;
                border-radius: 14px;
                padding: 8px 12px;
                font-weight: 700;
            }
        """)
        self.header_row.addWidget(self.risk_badge, 0, Qt.AlignmentFlag.AlignTop)
        self.content_layout.addLayout(self.header_row)

        self.permissions_box = QFrame()
        self.permissions_box.setStyleSheet("background-color: #F8F9FA; border-radius: 8px; border: 1px solid #E8DBFF;")
        pbox_layout = QHBoxLayout(self.permissions_box)
        pbox_layout.setContentsMargins(15, 10, 15, 10)
        pbox_label = QLabel("Sanitizer Policy:")
        pbox_label.setStyleSheet("font-weight: bold; color: #1F163A;")
        pbox_layout.addWidget(pbox_label)
        
        self.perm_system_calls = StyledCheckBox("Allow System Calls")
        self.perm_assembly = StyledCheckBox("Allow Inline Assembly")
        self.perm_sys_includes = StyledCheckBox("Allow <sys/*>")
        
        for chk in [self.perm_system_calls, self.perm_assembly, self.perm_sys_includes]:
            pbox_layout.addWidget(chk)
            chk.stateChanged.connect(self._update_permissions)
            
        pbox_layout.addStretch()
        self.content_layout.addWidget(self.permissions_box)
        self._update_permissions()

        self.risk_bar = QProgressBar()
        self.risk_bar.setRange(0, 100)
        self.risk_bar.setTextVisible(False)
        self.risk_bar.setFixedHeight(10)
        self.risk_bar.setStyleSheet("""
            QProgressBar {
                background-color: #F1ECFF;
                border: none;
                border-radius: 5px;
            }
            QProgressBar::chunk {
                background-color: #6C5CE7;
                border-radius: 5px;
            }
        """)
        self.content_layout.addWidget(self.risk_bar)

        self.filter_row = QHBoxLayout()
        self.filter_row.setSpacing(8)
        self.filter_buttons = {}
        for label in ["All", "High", "Medium", "Low"]:
            btn = FilterTabButton(label)
            btn.clicked.connect(lambda _checked=False, value=label: self.set_filter(value))
            self.filter_buttons[label] = btn
            self.filter_row.addWidget(btn)
        self.filter_row.addStretch()
        self.content_layout.addLayout(self.filter_row)
        self.filter_buttons["All"].setActive(True)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.report_host = QWidget()
        self.report_host.setStyleSheet("QWidget { background: transparent; }")
        self.report_layout = QVBoxLayout(self.report_host)
        self.report_layout.setContentsMargins(0, 0, 0, 0)
        self.report_layout.setSpacing(14)
        self.report_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.report_host)
        self.content_layout.addWidget(self.scroll, 1)

        self.update_report([])

    def _normalize_findings(self, findings):
        normalized = []
        for finding in findings or []:
            if hasattr(finding, "to_dict"):
                item = dict(finding.to_dict())
            elif isinstance(finding, dict):
                item = dict(finding)
            else:
                continue
            if not item.get("cwe"):
                vuln = item.get("vulnerability_type")
                if vuln:
                    try:
                        item["cwe"] = get_cwe_for_vulnerability(vuln)
                    except Exception:
                        pass
            normalized.append(item)
        return normalized

    def _badge_color(self, severity):
        return {
            "Critical": "#FF4D4D",
            "High": "#FF4D4D",
            "Medium": "#FFA500",
            "Low": "#2ECC71",
        }.get(severity, "#2ECC71")

    def _group_counts(self, findings):
        counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
        for finding in findings:
            sev = finding.get("severity", "Low")
            if sev == "Critical":
                counts["Critical"] += 1
            elif sev in counts:
                counts[sev] += 1
        return counts

    def _risk_score(self, findings):
        weights = {"Critical": 10, "High": 5, "Medium": 2, "Low": 1}
        return sum(weights.get(f.get("severity", "Low"), 1) for f in findings)

    def _risk_label(self, score):
        if score == 0:
            return "Clean"
        if score <= 10:
            return "Low Risk"
        if score <= 30:
            return "Moderate"
        return "High Risk"

    def _clear_cards(self):
        while self.report_layout.count():
            item = self.report_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._cards = []

    def _display_filter(self, severity):
        if self.current_filter == "All":
            return True
        if self.current_filter == "High":
            return severity in ("Critical", "High")
        return severity == self.current_filter

    def _match_sections(self, findings):
        sections = []
        for severity in ("Critical", "High", "Medium", "Low"):
            group = [f for f in findings if f.get("severity", "Low") == severity]
            if not group:
                continue
            if not any(self._display_filter(severity) for _ in group):
                continue
            sections.append((severity, group))
        return sections

    def _make_empty_state(self):
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #EEF0FF;
                border-radius: 14px;
            }
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        label = QLabel("No security findings detected.")
        label.setStyleSheet("color: #1F163A; font-size: 13px; font-weight: 600;")
        layout.addWidget(label)
        return card

    def _make_blocked_attacks_banner(self, count: int) -> QFrame:
        banner = QFrame()
        banner.setObjectName("BlockedAttacksBanner")
        banner.setStyleSheet("""
            QFrame#BlockedAttacksBanner {
                background-color: #FFFBEB;
                border: 1px solid #FCD34D;
                border-left: 5px solid #F59E0B;
                border-radius: 10px;
            }
        """)
        layout = QHBoxLayout(banner)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)

        icon_lbl = QLabel("🛑")
        icon_lbl.setStyleSheet("font-size: 20px;")
        layout.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        plural = "attempt" if count == 1 else "attempts"
        msg_lbl = QLabel(
            f"<b>Note:</b> 0 vulnerabilities found in the current source. However, <b>{count} malicious patch {plural}</b> "
            f"{'was' if count == 1 else 'were'} detected and blocked during this session before being applied — see <b>Patch Review</b> for details."
        )
        msg_lbl.setStyleSheet("color: #92400E; font-size: 12px; line-height: 1.4;")
        msg_lbl.setWordWrap(True)
        layout.addWidget(msg_lbl, 1)

        return banner

    def set_filter(self, value):
        self.current_filter = value
        for label, btn in self.filter_buttons.items():
            btn.setActive(label == value)
        self._render()

    def update_report(self, findings, patch_gate_results=None, session_gate6_blocked=None):
        if session_gate6_blocked is not None:
            self.session_gate6_blocked = int(session_gate6_blocked)
        self.findings = self._normalize_findings(findings)
        if patch_gate_results:
            self._apply_patch_gate_results(patch_gate_results)
        self._render()

    def _apply_patch_gate_results(self, gate_results):
        if isinstance(gate_results, dict):
            items = list(gate_results.values())
        elif isinstance(gate_results, (list, tuple)):
            items = list(gate_results)
        else:
            items = [gate_results] if gate_results else []

        for gr in items:
            details = getattr(gr, "details", None)
            if details is None and isinstance(gr, dict):
                details = gr.get("details")
            if not details:
                if isinstance(gr, dict) and ("introduced_regressions" in gr or "unmasked_findings" in gr):
                    details = gr
            if not details:
                continue

            for intro in details.get("introduced_regressions", []):
                intro_dict = intro if isinstance(intro, dict) else (intro.to_dict() if hasattr(intro, "to_dict") else {})
                intro_dict = dict(intro_dict)
                intro_dict["blocked_by_gate4"] = True
                intro_dict["introduced_by_patch"] = True
                self.findings.extend(self._normalize_findings([intro_dict]))
            for unmasked in details.get("unmasked_findings", []):
                un_dict = unmasked if isinstance(unmasked, dict) else (unmasked.to_dict() if hasattr(unmasked, "to_dict") else {})
                un_dict = dict(un_dict)
                un_dict["unmasked_by_patch"] = True
                self.findings.extend(self._normalize_findings([un_dict]))

    def _render(self):
        counts = self._group_counts(self.findings)
        score = self._risk_score(self.findings)
        self.summary.setText(
            f"{counts['Critical']} critical, {counts['High']} high, {counts['Medium']} medium, {counts['Low']} low findings"
        )
        self.risk_badge.setText(f"Risk Score: {score} • {self._risk_label(score)}")
        self.risk_bar.setValue(min(100, score * 3))

        self._clear_cards()

        # Task 2: Cross-reference banner when 0 real findings in file, but gate6 blocked attacks occurred in this session
        if self.session_gate6_blocked > 0 and len(self.findings) == 0:
            banner = self._make_blocked_attacks_banner(self.session_gate6_blocked)
            self.report_layout.addWidget(banner)

        filtered = [f for f in self.findings if self._display_filter(f.get("severity", "Low"))]
        if not filtered:
            self.report_layout.addWidget(self._make_empty_state())
            return

        for severity, group in self._match_sections(filtered):
            section = QLabel(f"{severity.upper()}  •  {len(group)}")
            section.setStyleSheet("color: #6C5CE7; font-size: 11px; font-weight: 800; letter-spacing: 0px;")
            self.report_layout.addWidget(section)
            for finding in group:
                self.report_layout.addWidget(SecurityCard(finding, self._badge_color(severity)))

    def _update_permissions(self):
        import os
        os.environ["ALLOW_SYSTEM_CALLS"] = "1" if self.perm_system_calls.isChecked() else "0"
        os.environ["ALLOW_ASSEMBLY"] = "1" if self.perm_assembly.isChecked() else "0"
        os.environ["ALLOW_SYS_INCLUDES"] = "1" if self.perm_sys_includes.isChecked() else "0"


class AgentTracePage(CustomFrame):
    def __init__(self, parent=None):
        super().__init__("AGENT EXECUTION TRACE", left_padding=True)
        self.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #E8DBFF;
                border-radius: 16px;
            }
        """)
        self.header.setStyleSheet("""
            QLabel {
                background-color: #ffffff;
                color: #6C5CE7;
                border: none;
                border-bottom: 1px solid #F0E9FF;
                padding: 10px 16px;
                border-top-left-radius: 15px;
                border-top-right-radius: 15px;
                font-weight: bold;
            }
        """)
        self.content_widget.setStyleSheet("QWidget { background-color: #ffffff; }")
        self.content_layout.setContentsMargins(18, 18, 18, 18)
        self.content_layout.setSpacing(12)

        self.trace_log = []

        # Top summary bar
        summary_card = QFrame()
        summary_card.setStyleSheet("""
            QFrame {
                background-color: #F8F9FD;
                border: 1px solid #E2E8F0;
                border-radius: 12px;
                padding: 6px 12px;
            }
        """)
        summary_layout = QHBoxLayout(summary_card)
        summary_layout.setContentsMargins(12, 8, 12, 8)
        summary_layout.setSpacing(14)

        self.lbl_steps = QLabel("Steps: 0")
        self.lbl_steps.setStyleSheet("font-weight: bold; color: #1E293B; font-size: 13px;")
        summary_layout.addWidget(self.lbl_steps)

        self.lbl_patches = QLabel("Patches: Applied 0 | Rollbacks 0 | Pending 0")
        self.lbl_patches.setStyleSheet("color: #475569; font-size: 12px;")
        summary_layout.addWidget(self.lbl_patches)

        self.lbl_status = QLabel("STATUS: IDLE")
        self.lbl_status.setStyleSheet("font-weight: bold; color: #64748B; background: #EEF2F6; padding: 4px 8px; border-radius: 6px; font-size: 11px;")
        summary_layout.addWidget(self.lbl_status)

        summary_layout.addStretch()

        btn_copy = QPushButton("Copy Trace")
        btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_copy.setStyleSheet("""
            QPushButton {
                background-color: #EDE9FE;
                color: #5B21B6;
                font-weight: bold;
                border: 1px solid #DDD6FE;
                border-radius: 8px;
                padding: 5px 12px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #DDD6FE;
            }
        """)
        btn_copy.clicked.connect(self._copy_trace)
        summary_layout.addWidget(btn_copy)

        btn_clear = QPushButton("Clear")
        btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clear.setStyleSheet("""
            QPushButton {
                background-color: #F1F5F9;
                color: #475569;
                border: 1px solid #CBD5E1;
                border-radius: 8px;
                padding: 5px 12px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #E2E8F0;
            }
        """)
        btn_clear.clicked.connect(self.clear_trace)
        summary_layout.addWidget(btn_clear)

        self.content_layout.addWidget(summary_card)

        # Splitter: Left is step timeline tree, right is formatted HTML report
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background-color: #E2E8F0; }")

        # Left panel: step timeline tree
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        lbl_tree_title = QLabel("Step-by-Step Execution Timeline")
        lbl_tree_title.setStyleSheet("font-weight: bold; color: #334155; font-size: 12px;")
        left_layout.addWidget(lbl_tree_title)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Step / Event", "Tool", "Outcome"])
        self.tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: #FFFFFF;
                color: #1E293B;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 4px;
                font-size: 11px;
                font-family: {FONT_FAMILY};
            }}
            QHeaderView::section {{
                background-color: #F8FAFC;
                color: #334155;
                border: none;
                border-bottom: 1px solid #E2E8F0;
                padding: 6px 8px;
                font-weight: bold;
                font-size: 11px;
                font-family: {FONT_FAMILY};
            }}
            QTreeWidget::item {{
                padding: 5px 4px;
                color: #1E293B;
                border-bottom: 1px solid #F8FAFC;
            }}
            QTreeWidget::item:hover {{
                background-color: #F1F5F9;
                color: #0F172A;
            }}
            QTreeWidget::item:selected {{
                background-color: #EDE9FE;
                color: #5B21B6;
            }}
        """)
        self.tree.setColumnWidth(0, 240)
        self.tree.setColumnWidth(1, 90)
        left_layout.addWidget(self.tree)
        splitter.addWidget(left_widget)

        # Right panel: Formatted HTML browser
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        lbl_browser_title = QLabel("Rich Execution & Gate Report")
        lbl_browser_title.setStyleSheet("font-weight: bold; color: #334155; font-size: 12px;")
        right_layout.addWidget(lbl_browser_title)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setStyleSheet("""
            QTextBrowser {
                background-color: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 10px;
                font-family: Menlo, Consolas, monospace;
                font-size: 11px;
            }
        """)
        self.browser.setHtml("<p style='color: #64748B;'>No trace data recorded yet. Run Auto-Heal to inspect agent execution steps.</p>")
        right_layout.addWidget(self.browser)
        splitter.addWidget(right_widget)

        splitter.setSizes([400, 500])
        self.content_layout.addWidget(splitter, 1)

    def clear_trace(self):
        self.trace_log = []
        self._user_applied_count = 0
        self.tree.clear()
        self.browser.setHtml("<p style='color: #64748B;'>No trace data recorded yet. Run Auto-Heal to inspect agent execution steps.</p>")
        self.lbl_steps.setText("Steps: 0")
        self.lbl_patches.setText("Patches: Applied 0 | Rollbacks 0 | Pending 0")
        self.lbl_status.setText("STATUS: IDLE")
        self.lbl_status.setStyleSheet("font-weight: bold; color: #64748B; background: #EEF2F6; padding: 4px 8px; border-radius: 6px; font-size: 11px;")

    def set_user_applied_count(self, count: int):
        self._user_applied_count = max(0, int(count))
        self._update_views()

    def add_step(self, step_record: dict):
        self.trace_log.append(step_record)
        self._add_step_to_tree(step_record)
        self._update_views()

    def set_trace_log(self, trace_log: list):
        self.trace_log = list(trace_log)
        self.tree.clear()
        for step in self.trace_log:
            self._add_step_to_tree(step)
        self._update_views()

    def _add_step_to_tree(self, step: dict):
        step_num = step.get("step", len(self.trace_log))
        tool = step.get("tool_called", "unknown")
        decision = step.get("decision", "in_progress")
        summary = step.get("output_summary", "")

        item = QTreeWidgetItem(self.tree)
        if tool.lower() in ("gate6_security_block", "gate6_block", "gate6"):
            item.setText(0, f"🛑 Step {step_num}: GATE6_SECURITY_BLOCK [DEFENSE]")
            item.setForeground(0, QBrush(QColor("#DC2626")))
            item.setForeground(1, QBrush(QColor("#DC2626")))
            item.setForeground(2, QBrush(QColor("#DC2626")))
        elif tool.lower() in ("security_guardrail", "security"):
            item.setText(0, f"🛡️ Step {step_num}: {tool.upper()} [DEFENSE]")
            item.setForeground(0, QBrush(QColor("#7C3AED")))
            item.setForeground(1, QBrush(QColor("#7C3AED")))
            item.setForeground(2, QBrush(QColor("#7C3AED")))
        else:
            item.setText(0, f"Step {step_num}: {tool.upper()}")
        item.setText(1, tool)
        item.setText(2, decision)

        in_item = QTreeWidgetItem(item)
        in_item.setText(0, f"Input: {step.get('input_summary', '')}")

        out_item = QTreeWidgetItem(item)
        out_item.setText(0, f"Output: {summary}")

        dec_item = QTreeWidgetItem(item)
        dec_item.setText(0, f"Decision: {decision}")

        # Verification gate breakdown
        gate_details = step.get("gate_details")
        if gate_details and isinstance(gate_details, dict):
            gates_root = QTreeWidgetItem(item)
            failing = step.get("failing_gate")
            gates_root.setText(0, f"Verification Gates (Failing: {failing or 'None'})")
            for g_name, g_info in gate_details.items():
                passed = g_info.get("passed") if isinstance(g_info, dict) else g_info
                g_item = QTreeWidgetItem(gates_root)
                status_str = "PASS ✅" if passed else "FAIL ❌"
                g_item.setText(0, f"Gate [{g_name}]: {status_str}")
                if isinstance(g_info, dict) and "reason" in g_info:
                    g_item.setText(2, str(g_info.get("reason", "")))
            gates_root.setExpanded(True)

        item.setExpanded(True)

    def _update_views(self):
        summary = summarize_trace(self.trace_log)
        self.lbl_steps.setText(f"Steps: {summary['total_steps']}")
        applied_cnt = getattr(self, "_user_applied_count", 0)
        rollbacks_cnt = summary.get("patches_rolled_back", 0)
        pending_cnt = summary.get("patches_pending", 0)
        if applied_cnt > 0:
            pending_cnt = max(0, pending_cnt - applied_cnt)
        self.lbl_patches.setText(f"Patches: Applied {applied_cnt} | Rollbacks {rollbacks_cnt} | Pending {pending_cnt}")
        stop_reason = summary.get("stop_reason", "in_progress")
        gate6_blocked_count = summary.get("gate6_blocked_count", 0)
        if gate6_blocked_count == 0:
            gate6_blocked_count = sum(
                1 for s in self.trace_log
                if s.get("tool_called") in ("GATE6_SECURITY_BLOCK", "gate6_security_block")
                or (s.get("tool_called") == "verify" and s.get("failing_gate") == "gate6_patch_security")
            )

        if "goal met" in stop_reason.lower() or stop_reason == "compiled_clean":
            if gate6_blocked_count > 0:
                plural = "attempt" if gate6_blocked_count == 1 else "attempts"
                status_text = f"GOAL MET: COMPILATION CLEAN AND SECURE ({gate6_blocked_count} malicious patch {plural} blocked during this session)"
            else:
                if "clean and secure" in stop_reason.lower():
                    status_text = "GOAL MET: COMPILATION CLEAN AND SECURE"
                elif stop_reason == "compiled_clean":
                    status_text = "HEALED ✅"
                else:
                    status_text = stop_reason.upper()
            self.lbl_status.setText(f"STATUS: {status_text}")
            self.lbl_status.setStyleSheet("font-weight: bold; color: #15803D; background: #DCFCE7; padding: 4px 8px; border-radius: 6px; font-size: 11px;")
            self.lbl_status.setMinimumWidth(self.lbl_status.fontMetrics().horizontalAdvance(self.lbl_status.text()) + 24)
            self.lbl_status.adjustSize()
        elif stop_reason in ("gave_up", "max_iterations", "no_fixable_finding"):
            self.lbl_status.setText(f"STATUS: {stop_reason.upper()} ⚠️")
            self.lbl_status.setStyleSheet("font-weight: bold; color: #B91C1C; background: #FEE2E2; padding: 4px 8px; border-radius: 6px; font-size: 11px;")
            self.lbl_status.setMinimumWidth(self.lbl_status.fontMetrics().horizontalAdvance(self.lbl_status.text()) + 24)
            self.lbl_status.adjustSize()
        else:
            self.lbl_status.setText(f"STATUS: {stop_reason.upper()}")
            self.lbl_status.setStyleSheet("font-weight: bold; color: #64748B; background: #EEF2F6; padding: 4px 8px; border-radius: 6px; font-size: 11px;")
            self.lbl_status.setMinimumWidth(self.lbl_status.fontMetrics().horizontalAdvance(self.lbl_status.text()) + 24)
            self.lbl_status.adjustSize()

        html_content = format_trace_html(self.trace_log)
        self.browser.setHtml(html_content)

    def _copy_trace(self):
        try:
            txt = format_trace_text(self.trace_log)
        except Exception:
            txt = json.dumps(self.trace_log, indent=2)
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(txt)


class PatchReviewCard(QFrame):
    def __init__(self, reviewable_patch: Any, session: Any, on_action_completed=None, parent=None):
        super().__init__(parent)
        self.rp = reviewable_patch
        self.session = session
        self.on_action_completed = on_action_completed

        self.setStyleSheet("""
            QFrame#PatchReviewCard {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 12px;
            }
        """)
        self.setObjectName("PatchReviewCard")

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Left indicator strip
        tier = getattr(self.rp, "safety_level", "S0")
        strip_color = "#10B981" if tier == "S0" else ("#3B82F6" if tier == "S1" else "#F59E0B")
        if not getattr(self.rp, "passed_gates", True):
            strip_color = "#EF4444"

        strip = QFrame()
        strip.setFixedWidth(6)
        strip.setStyleSheet(f"background-color: {strip_color}; border-top-left-radius: 12px; border-bottom-left-radius: 12px;")
        outer.addWidget(strip)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(14, 12, 14, 12)
        body_layout.setSpacing(8)
        outer.addWidget(body, 1)

        # Header row: Title + Badges
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        diag = getattr(self.rp.patch, "diagnostic", None)
        line_no = getattr(diag, "line", "?") if diag else "?"
        category = getattr(diag, "category", "Repair") if diag else "Repair"
        conf = getattr(diag, "confidence", 1.0) if diag else 1.0
        msg = getattr(diag, "message", "Proposed Fix") if diag else "Proposed Fix"

        lbl_title = QLabel(f"<b>Patch #{self.rp.patch_id} — Line {line_no}</b>: [{category.upper()}] {msg}")
        lbl_title.setStyleSheet("font-size: 13px; color: #1E293B;")
        lbl_title.setWordWrap(True)
        top_row.addWidget(lbl_title, 1)

        # Safety Tier badge
        badge_tier = QLabel(f"Tier: {tier}")
        badge_tier_color = "#D1FAE5" if tier == "S0" else ("#DBEAFE" if tier == "S1" else "#FEF3C7")
        badge_tier_fg = "#065F46" if tier == "S0" else ("#1E40AF" if tier == "S1" else "#92400E")
        badge_tier.setStyleSheet(f"background: {badge_tier_color}; color: {badge_tier_fg}; font-weight: bold; font-size: 10px; padding: 3px 8px; border-radius: 6px;")
        top_row.addWidget(badge_tier)

        # Status badge
        st_val = self.rp.status.value if hasattr(self.rp.status, "value") else str(self.rp.status)
        self.badge_status = QLabel(st_val.upper())
        self._update_status_badge()
        top_row.addWidget(self.badge_status)

        body_layout.addLayout(top_row)

        # Gate verification row
        gates_box = QFrame()
        gates_box.setStyleSheet("background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px;")
        gates_layout = QVBoxLayout(gates_box)
        gates_layout.setContentsMargins(8, 6, 8, 6)
        gates_layout.setSpacing(4)

        if getattr(self.rp, "passed_gates", True):
            lbl_gate = QLabel("<b>Verification:</b> All verification gates PASSED ✅")
            lbl_gate.setStyleSheet("color: #15803D; font-size: 11px;")
        else:
            failing = getattr(self.rp, "failing_gate", None) or "verification_gate"
            lbl_gate = QLabel(f"<b>Verification:</b> Failed gate: <b>{failing}</b> ❌ (Cannot be accepted)")
            lbl_gate.setStyleSheet("color: #B91C1C; font-size: 11px;")
        gates_layout.addWidget(lbl_gate)

        body_layout.addWidget(gates_box)

        # Diff View
        from diff_viewer import format_diff_html, compute_diff
        raw_diff = getattr(self.rp.patch, "diff", "")
        if isinstance(raw_diff, list):
            diff_html = format_diff_html(raw_diff)
        else:
            orig = getattr(self.rp.patch, "original_source", "") or (open(self.session.file_path, "r", errors="ignore").read() if os.path.exists(self.session.file_path) else "")
            patched = getattr(self.rp.patch, "patched_source", "")
            diff_lines = compute_diff(orig, patched)
            diff_html = format_diff_html(diff_lines)

        diff_browser = QTextBrowser()
        diff_browser.setOpenLinks(False)
        diff_browser.setHtml(diff_html)
        diff_browser.setStyleSheet("background: #0F172A; color: #F8FAFC; border: 1px solid #334155; border-radius: 6px; padding: 6px; font-family: Menlo, Consolas, monospace; font-size: 11px;")
        diff_browser.setMaximumHeight(140)
        body_layout.addWidget(diff_browser)

        # Action Buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        can_acc, reason = self.rp.can_accept()
        self.btn_accept = QPushButton("Accept Patch")
        self.btn_accept.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_accept.setEnabled(can_acc)
        if not can_acc:
            self.btn_accept.setToolTip(reason)
        self.btn_accept.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #059669; }
            QPushButton:disabled { background-color: #E2E8F0; color: #94A3B8; }
        """)
        self.btn_accept.clicked.connect(self._on_accept)
        btn_row.addWidget(self.btn_accept)

        self.btn_reject = QPushButton("Reject")
        self.btn_reject.setCursor(Qt.CursorShape.PointingHandCursor)
        st_val = self.rp.status.value if hasattr(self.rp.status, "value") else str(self.rp.status)
        self.btn_reject.setEnabled(st_val == "pending")
        self.btn_reject.setStyleSheet("""
            QPushButton {
                background-color: #EF4444;
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #DC2626; }
            QPushButton:disabled { background-color: #E2E8F0; color: #94A3B8; }
        """)
        self.btn_reject.clicked.connect(self._on_reject)
        btn_row.addWidget(self.btn_reject)

        self.btn_undo = QPushButton("Undo")
        self.btn_undo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_undo.setEnabled(st_val == "accepted")
        self.btn_undo.setStyleSheet("""
            QPushButton {
                background-color: #F1F5F9;
                color: #475569;
                font-weight: bold;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #E2E8F0; }
            QPushButton:disabled { background-color: #F8FAFC; color: #CBD5E1; border-color: #E2E8F0; }
        """)
        self.btn_undo.clicked.connect(self._on_undo)
        btn_row.addWidget(self.btn_undo)

        btn_row.addStretch()
        body_layout.addLayout(btn_row)

    def _update_status_badge(self):
        st_val = self.rp.status.value if hasattr(self.rp.status, "value") else str(self.rp.status)
        if st_val == "accepted":
            self.badge_status.setText("ACCEPTED ✅")
            self.badge_status.setStyleSheet("background: #DCFCE7; color: #15803D; font-weight: bold; font-size: 10px; padding: 3px 8px; border-radius: 6px;")
        elif st_val == "rejected":
            self.badge_status.setText("REJECTED ❌")
            self.badge_status.setStyleSheet("background: #FEE2E2; color: #B91C1C; font-weight: bold; font-size: 10px; padding: 3px 8px; border-radius: 6px;")
        elif not getattr(self.rp, "passed_gates", True):
            self.badge_status.setText("GATE FAILED ❌")
            self.badge_status.setStyleSheet("background: #FEE2E2; color: #B91C1C; font-weight: bold; font-size: 10px; padding: 3px 8px; border-radius: 6px;")
        else:
            self.badge_status.setText("PENDING")
            self.badge_status.setStyleSheet("background: #FEF3C7; color: #B45309; font-weight: bold; font-size: 10px; padding: 3px 8px; border-radius: 6px;")

    def _on_accept(self):
        try:
            self.session.accept(self.rp.patch_id)
            self._refresh_buttons()
            if self.on_action_completed:
                self.on_action_completed("accept", self.rp)
        except Exception as e:
            QMessageBox.warning(self, "Accept Patch", str(e))

    def _on_reject(self):
        try:
            self.session.reject(self.rp.patch_id)
            self._refresh_buttons()
            if self.on_action_completed:
                self.on_action_completed("reject", self.rp)
        except Exception as e:
            QMessageBox.warning(self, "Reject Patch", str(e))

    def _on_undo(self):
        try:
            undone = self.session.undo(self.rp.patch_id)
            if self.on_action_completed:
                self.on_action_completed("undo", undone)
        except Exception as e:
            QMessageBox.warning(self, "Undo Patch", str(e))

    def _refresh_buttons(self):
        self._update_status_badge()
        can_acc, reason = self.rp.can_accept()
        st_val = self.rp.status.value if hasattr(self.rp.status, "value") else str(self.rp.status)
        self.btn_accept.setEnabled(can_acc)
        self.btn_reject.setEnabled(st_val == "pending")
        self.btn_undo.setEnabled(st_val == "accepted")


class BlockedAttemptCard(QFrame):
    """
    Card for REJECTED security findings in Patch Review:
    - Gate 6 malicious patch rejections (anti-exfiltration)
    - Comment-based instruction_injection detections
    Visually distinct: Dark red/charcoal card, bright red left indicator strip,
    explicit 'BLOCKED - NEVER APPLIED' badge, risk score, intercepted detector,
    and NO Accept button (only Acknowledge & Dismiss).
    """
    def __init__(self, finding: dict, on_dismiss=None, parent=None):
        super().__init__(parent)
        self.finding = finding
        self.on_dismiss = on_dismiss

        self.setObjectName("BlockedAttemptCard")
        self.setStyleSheet("""
            QFrame#BlockedAttemptCard {
                background-color: #1A131F;
                border: 1px solid #7F1D1D;
                border-radius: 12px;
            }
            QFrame#BlockedAttemptCard QWidget {
                background-color: transparent;
            }
        """)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Left indicator strip - Bright Red
        strip = QFrame()
        strip.setFixedWidth(6)
        strip.setStyleSheet("background-color: #EF4444; border-top-left-radius: 12px; border-bottom-left-radius: 12px;")
        outer.addWidget(strip)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(14, 12, 14, 12)
        body_layout.setSpacing(8)
        outer.addWidget(body, 1)

        # Header row: Title + Badges
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        attack_type = self.finding.get("attack_type", self.finding.get("type", "Security Block"))
        line_no = self.finding.get("line", "?")
        lbl_title = QLabel(f"🛑 <b>Blocked Security Threat — Line {line_no}</b>: [{attack_type.upper()}]")
        lbl_title.setStyleSheet("font-size: 13px; color: #FCA5A5; background: transparent;")
        lbl_title.setWordWrap(True)
        top_row.addWidget(lbl_title, 1)

        # Risk tier badge
        risk_tier = str(self.finding.get("risk_tier", "HIGH")).upper()
        badge_tier = QLabel(f"Risk Tier: {risk_tier}")
        badge_tier.setStyleSheet("background: #991B1B; color: #FFFFFF; font-weight: bold; font-size: 10px; padding: 3px 8px; border-radius: 6px;")
        top_row.addWidget(badge_tier)

        # Risk Score badge
        risk_score = self.finding.get("risk_score", 0.95)
        badge_score = QLabel(f"Risk: {risk_score:.2f}" if isinstance(risk_score, (int, float)) else f"Risk: {risk_score}")
        badge_score.setStyleSheet("background: #27272A; color: #FCA5A5; font-weight: bold; font-size: 10px; padding: 3px 8px; border-radius: 6px; border: 1px solid #52525B;")
        top_row.addWidget(badge_score)

        # Status badge
        badge_status = QLabel("BLOCKED — NEVER APPLIED 🛑")
        badge_status.setStyleSheet("background: #450A0A; color: #F87171; font-weight: bold; font-size: 10px; padding: 3px 8px; border-radius: 6px; border: 1px solid #991B1B;")
        top_row.addWidget(badge_status)

        body_layout.addLayout(top_row)

        # Security Interception Details Box
        sec_box = QFrame()
        sec_box.setStyleSheet("background: #110B17; border: 1px solid #450A0A; border-radius: 6px;")
        sec_layout = QVBoxLayout(sec_box)
        sec_layout.setContentsMargins(10, 8, 10, 8)
        sec_layout.setSpacing(4)

        detector = self.finding.get("detector", "Security Guardrail")
        attempted = self.finding.get("attempted", self.finding.get("reason", "Malicious action attempted"))

        lbl_attempt = QLabel(f"<b>Attempted Action:</b> <span style='color: #FEE2E2;'>{attempted}</span>")
        lbl_attempt.setStyleSheet("color: #E2E8F0; font-size: 11px;")
        lbl_attempt.setWordWrap(True)
        sec_layout.addWidget(lbl_attempt)

        lbl_caught = QLabel(f"<b>Intercepted By:</b> <span style='color: #C084FC;'>{detector}</span>")
        lbl_caught.setStyleSheet("color: #E2E8F0; font-size: 11px;")
        lbl_caught.setWordWrap(True)
        sec_layout.addWidget(lbl_caught)

        lbl_policy = QLabel("<b>Enforcement:</b> <span style='color: #EF4444; font-weight: bold;'>Automatically blocked and purged from code suggestions. Cannot be approved, accepted, or applied.</span>")
        lbl_policy.setStyleSheet("font-size: 11px;")
        lbl_policy.setWordWrap(True)
        sec_layout.addWidget(lbl_policy)

        body_layout.addWidget(sec_box)

        # Code Diff or Payload Snippet
        patch_obj = self.finding.get("patch")
        raw_diff = self.finding.get("diff")
        snippet = self.finding.get("snippet", "")

        from diff_viewer import format_diff_html
        content_html = ""
        if raw_diff:
            content_html = format_diff_html(raw_diff) if isinstance(raw_diff, list) else f"<pre style='color:#EF4444;'>{html.escape(str(raw_diff))}</pre>"
        elif patch_obj and hasattr(patch_obj, "diff") and patch_obj.diff:
            content_html = format_diff_html(patch_obj.diff)
        elif snippet:
            content_html = f"<div style='font-family: Menlo, Consolas, monospace; font-size: 11px; color: #FCA5A5; background: #0F172A; padding: 8px; border-radius: 4px;'><b>Intercepted Adversarial Payload:</b><br><span style='color: #EF4444; background: #450A0A; padding: 2px 4px; border-radius: 3px;'>{html.escape(str(snippet))}</span></div>"

        if content_html:
            diff_browser = QTextBrowser()
            diff_browser.setOpenLinks(False)
            diff_browser.setHtml(content_html)
            diff_browser.setStyleSheet("background: #09060E; color: #F8FAFC; border: 1px solid #3F131D; border-radius: 6px; padding: 6px; font-family: Menlo, Consolas, monospace; font-size: 11px;")
            diff_browser.setMaximumHeight(130)
            body_layout.addWidget(diff_browser)

        # Action Buttons row (NO Accept button, only Dismiss)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        lbl_no_accept = QLabel("<i>(No Accept button: Security blocks are non-negotiable and cannot be approved)</i>")
        lbl_no_accept.setStyleSheet("color: #94A3B8; font-size: 11px;")
        btn_row.addWidget(lbl_no_accept)

        btn_row.addStretch()

        self.btn_dismiss = QPushButton("Acknowledge & Dismiss")
        self.btn_dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_dismiss.setStyleSheet("""
            QPushButton {
                background-color: #27272A;
                color: #F1F5F9;
                font-weight: bold;
                border: 1px solid #52525B;
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #3F3F46; border-color: #71717A; }
        """)
        self.btn_dismiss.clicked.connect(self._on_dismiss)
        btn_row.addWidget(self.btn_dismiss)

        body_layout.addLayout(btn_row)

    def _on_dismiss(self):
        self.hide()
        if self.on_dismiss:
            self.on_dismiss(self)


class PatchReviewPage(CustomFrame):
    def __init__(self, file_path_getter=None, on_file_updated=None, parent=None):
        super().__init__("PATCH REVIEW & APPROVAL WORKFLOW", left_padding=True)
        self.file_path_getter = file_path_getter
        self.on_file_updated = on_file_updated
        self.session: Optional[Any] = None
        self.card_widgets: list[PatchReviewCard] = []
        self.blocked_widgets: list[BlockedAttemptCard] = []

        self.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #E8DBFF;
                border-radius: 16px;
            }
        """)
        self.header.setStyleSheet("""
            QLabel {
                background-color: #ffffff;
                color: #6C5CE7;
                border: none;
                border-bottom: 1px solid #F0E9FF;
                padding: 10px 16px;
                border-top-left-radius: 15px;
                border-top-right-radius: 15px;
                font-weight: bold;
            }
        """)
        self.content_widget.setStyleSheet("QWidget { background-color: #ffffff; }")
        self.content_layout.setContentsMargins(18, 18, 18, 18)
        self.content_layout.setSpacing(12)

        # Top summary bar
        summary_card = QFrame()
        summary_card.setStyleSheet("""
            QFrame {
                background-color: #F8F9FD;
                border: 1px solid #E2E8F0;
                border-radius: 12px;
                padding: 6px 12px;
            }
        """)
        summary_layout = QHBoxLayout(summary_card)
        summary_layout.setContentsMargins(12, 8, 12, 8)
        summary_layout.setSpacing(14)

        self.lbl_stats = QLabel("No review session active.")
        self.lbl_stats.setStyleSheet("font-weight: bold; color: #1E293B; font-size: 13px;")
        summary_layout.addWidget(self.lbl_stats)

        summary_layout.addStretch()

        self.btn_global_undo = QPushButton("Undo Last Action")
        self.btn_global_undo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_global_undo.setEnabled(False)
        self.btn_global_undo.setStyleSheet("""
            QPushButton {
                background-color: #EDE9FE;
                color: #5B21B6;
                font-weight: bold;
                border: 1px solid #DDD6FE;
                border-radius: 8px;
                padding: 6px 14px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #DDD6FE; }
            QPushButton:disabled { background-color: #F1F5F9; color: #94A3B8; border-color: #E2E8F0; }
        """)
        self.btn_global_undo.clicked.connect(self._on_global_undo)
        summary_layout.addWidget(self.btn_global_undo)

        self.content_layout.addWidget(summary_card)

        # Scrollable area for cards
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(10)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.scroll.setWidget(self.cards_container)
        self.content_layout.addWidget(self.scroll, 1)

        self._show_empty_placeholder()

    def _show_empty_placeholder(self):
        for i in reversed(range(self.cards_layout.count())):
            w = self.cards_layout.itemAt(i).widget()
            if w:
                w.setParent(None)
        lbl = QLabel("No pending patches to review. Click 'REVIEW FIXES' in the toolbar to plan repairs and inspect diffs.")
        lbl.setStyleSheet("color: #64748B; font-size: 13px; padding: 40px;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cards_layout.addWidget(lbl)
        self.lbl_stats.setText("No active review session")
        self.btn_global_undo.setEnabled(False)

    def load_patches(self, file_path: str, patches: list, blocked_findings: Optional[list] = None):
        if PatchReviewSession is not None and patches:
            self.session = PatchReviewSession(file_path, patches)
        else:
            self.session = None

        self.card_widgets.clear()
        self.blocked_widgets.clear()

        for i in reversed(range(self.cards_layout.count())):
            w = self.cards_layout.itemAt(i).widget()
            if w:
                w.setParent(None)

        has_patches = bool(self.session and self.session.patches)
        has_blocked = bool(blocked_findings)

        if not has_patches and not has_blocked:
            self._show_empty_placeholder()
            return

        # 1. Normal Reviewable Patches
        if has_patches:
            for rp in self.session.patches:
                card = PatchReviewCard(rp, self.session, on_action_completed=self._handle_card_action)
                self.card_widgets.append(card)
                self.cards_layout.addWidget(card)

        # 2. Blocked Security Finding Attempts
        if has_blocked:
            seen_snippets = set()
            for bf in blocked_findings:
                snip_key = (bf.get("attempted"), bf.get("snippet"), bf.get("gate"))
                if snip_key in seen_snippets:
                    continue
                seen_snippets.add(snip_key)
                b_card = BlockedAttemptCard(bf, on_dismiss=self._handle_blocked_dismiss)
                self.blocked_widgets.append(b_card)
                self.cards_layout.addWidget(b_card)

        self._update_stats()

    def _handle_card_action(self, action: str, rp):
        self._update_stats()
        for card in self.card_widgets:
            card._refresh_buttons()
        if self.on_file_updated:
            self.on_file_updated()

    def _handle_blocked_dismiss(self, card):
        self._update_stats()

    def _on_global_undo(self):
        if not self.session or not self.session.can_undo:
            return
        try:
            self.session.undo()
            self._update_stats()
            for card in self.card_widgets:
                card._refresh_buttons()
            if self.on_file_updated:
                self.on_file_updated()
        except Exception as e:
            QMessageBox.warning(self, "Undo", str(e))

    def _update_stats(self):
        p_cnt = self.session.pending_count if self.session else 0
        a_cnt = self.session.accepted_count if self.session else 0
        r_cnt = self.session.rejected_count if self.session else 0
        b_cnt = sum(1 for w in self.blocked_widgets if w.isVisible())

        stats_text = f"Review Session: {p_cnt} Pending | {a_cnt} Accepted | {r_cnt} Rejected"
        if b_cnt > 0:
            stats_text += f" | <span style='color: #EF4444; font-weight: bold;'>{b_cnt} Blocked Attack(s) 🛑</span>"
        self.lbl_stats.setText(stats_text)
        self.btn_global_undo.setEnabled(self.session.can_undo if self.session else False)


class AppGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CppCheck Error Explainer")
        self.resize(1400, 850)
        
        self.file_name = "no file"
        self.file_path = None
        self.compiler_cmd = _resolve_compiler_command()
        self.compiler_version = _detect_compiler_version(self.compiler_cmd)
        self.language_standard = _resolve_language_standard()
        self.compile_has_run = False
        self.telemetry_history = []
        self.last_run_telemetry = None
        self.errors_count = 0
        self.warnings_count = 0
        self.execution_count = 0
        self.manual_co2_offset = 0.0
        self.energy_started_at = time.monotonic()
        self.rapl_start_j = _read_rapl_energy_joules()
        self.latest_security_findings = []
        self.latest_security_report = ""
        self.latest_agent_security_detections = []
        self.cumulative_compilation_co2 = 0.0
        self.session_gate6_rejections = {}
        
        self.setStyleSheet(f"QMainWindow {{ background-color: {BG_COLOR}; }}")

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        header_layout = QHBoxLayout()
        logo = QLabel("CppCheck Error Explainer")
        logo.setFont(QFont(FONT_FAMILY, 12, QFont.Weight.Bold))
        logo.setStyleSheet(f"color: {PINK}; letter-spacing:1px;")
        header_layout.addWidget(logo)
        header_layout.addStretch()
        
        header_layout.addSpacing(15)
        self.energy_container = QWidget()
        energy_hbox = QHBoxLayout(self.energy_container)
        energy_hbox.setContentsMargins(5, 0, 5, 0)
        energy_hbox.setSpacing(10)
        
        cpu_label = QLabel("CpU utilization")
        cpu_label.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.Bold))
        cpu_label.setStyleSheet(f"color: {TEXT_DIM};")
        energy_hbox.addWidget(cpu_label)
        
        self.sparkline = SparklineGraph()
        self.sparkline.setFixedWidth(120)
        self.sparkline.setFixedHeight(30)
        energy_hbox.addWidget(self.sparkline)
        
        header_layout.addWidget(self.energy_container)
        
        main_layout.addLayout(header_layout)

        toolbar_layout = QHBoxLayout()
        toolbar_layout.setSpacing(10)

        btn_load = StyledButton(" LOAD C++ FILE", "outline_dim")
        btn_load.clicked.connect(self.load_file)
        toolbar_layout.addWidget(btn_load)

        btn_compile = StyledButton(" COMPILE", "solid_pink")
        btn_compile.clicked.connect(self.analyze)
        toolbar_layout.addWidget(btn_compile)

        btn_run = StyledButton(" RUN CODE", "outline_dim")
        btn_run.clicked.connect(self.run_code)
        toolbar_layout.addWidget(btn_run)

        self.btn_heal = StyledButton("⚕ AUTO-HEAL", "outline_dim")
        self.btn_heal.clicked.connect(self.start_heal)
        self.btn_heal.setToolTip("Auto-detect + fix errors (up to 10 attempts)")
        toolbar_layout.addWidget(self.btn_heal)

        self.btn_review = StyledButton("👁 REVIEW FIXES", "outline_dim")
        self.btn_review.clicked.connect(self.start_review)
        self.btn_review.setToolTip("Plan repairs in review mode without auto-applying; inspect diffs and accept/reject/undo")
        toolbar_layout.addWidget(self.btn_review)


        self.cb_output_toggle = StyledCheckBox("Compile Output")
        self.cb_output_toggle.setChecked(True)
        self.cb_output_toggle.stateChanged.connect(self.toggle_output_pane)
        # Hidden to reduce visual noise
        # toolbar_layout.addWidget(self.cb_output_toggle)

        # AI explanation enhancer (OFF by default; does not persist across sessions)
        self.cb_ai_explain = StyledCheckBox("Use AI-enhanced explanations (experimental)")
        self.cb_ai_explain.setChecked(False)
        self.cb_ai_explain.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        toolbar_layout.addWidget(self.cb_ai_explain)

        self.cb_dataset_toggle = StyledCheckBox("Dataset Collector")
        # Hidden to reduce visual noise
        # toolbar_layout.addWidget(self.cb_dataset_toggle)
        
        toolbar_layout.addSpacing(10)
        self.status_label = QLabel("STATUS: ● READY TO ANALYZE")
        self.status_label.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.Bold))
        self.status_label.setStyleSheet(f"color: {PINK};")
        toolbar_layout.addWidget(self.status_label)
        
        toolbar_layout.addStretch()
        main_layout.addLayout(toolbar_layout)

        # Classifier — used by the auto-healer
        self.error_classifier = None
        if ErrorClassifier is not None:
            try:
                clf = ErrorClassifier()
                clf.load()   # load pre-trained model if available; trains lazily on first predict
                self.error_classifier = clf
            except Exception:
                self.error_classifier = None

        # Main horizontal layout for sidebar + content
        self.content_h_layout = QHBoxLayout()
        self.content_h_layout.setContentsMargins(0, 0, 0, 0)
        self.content_h_layout.setSpacing(0)
        main_layout.addLayout(self.content_h_layout, 1)

        self.sidebar = Sidebar()
        self.content_h_layout.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        self.content_h_layout.addWidget(self.stack, 1)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setStyleSheet(f"QSplitter::handle {{ background-color: {BG_COLOR}; }}")
        self.stack.addWidget(self.splitter) # Index 0

        self.ast_page = ASTPage()
        self.stack.addWidget(self.ast_page) # Index 1

        self.energy_page = EnergyPage()
        self.stack.addWidget(self.energy_page) # Index 2

        self.call_graph_page = CallGraphPage()
        self.stack.addWidget(self.call_graph_page) # Index 3

        self.security_page = SecurityPage()
        self.stack.addWidget(self.security_page) # Index 4

        self.cfg_page = CFGPage()
        self.stack.addWidget(self.cfg_page) # Index 5

        self.trace_page = AgentTracePage()
        self.stack.addWidget(self.trace_page) # Index 6

        self.review_page = PatchReviewPage(file_path_getter=lambda: self.file_path, on_file_updated=self._reload_editor_file)
        self.stack.addWidget(self.review_page) # Index 7

        # Sidebar navigation connections
        self.sidebar.btn1.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        self.sidebar.btn2.clicked.connect(self.switch_to_ast)
        self.sidebar.btn3.clicked.connect(lambda: self.stack.setCurrentIndex(2))
        self.sidebar.btn4.clicked.connect(self.switch_to_call_graph)
        self.sidebar.btn5.clicked.connect(self.switch_to_security)
        self.sidebar.btn6.clicked.connect(self.switch_to_cfg)
        self.sidebar.btn7.clicked.connect(self.switch_to_trace)
        self.sidebar.btn8.clicked.connect(self.switch_to_review)
        self.stack.currentChanged.connect(self.sidebar.set_active_index)

        if not hasattr(self, "energy_timer"):
            self.energy_timer = QTimer(self)
            self.energy_timer.timeout.connect(self.update_energy_dashboard)
            self.energy_timer.start(600)

        self.pane_left = CustomFrame("<> " + self.file_name.upper())
        self.pane_left.content_layout.setContentsMargins(0, 0, 0, 0)
        
        self.editor = CodeEditor()
        self.highlighter = CppSyntaxHighlighter(self.editor.document())
        
        # Editor layout within pane_left
        self.pane_left.content_layout.addWidget(self.editor)

        # Instructions to Agent prompt channel (Task B1 & B2)
        inst_card = QFrame()
        inst_card.setStyleSheet(f"""
            QFrame {{
                background-color: #F8FAFC;
                border-top: 1px solid #E2E8F0;
                padding: 4px 8px;
            }}
        """)
        inst_layout = QVBoxLayout(inst_card)
        inst_layout.setContentsMargins(8, 6, 8, 8)
        inst_layout.setSpacing(4)

        inst_header = QHBoxLayout()
        inst_title = QLabel("💬 Give the agent instructions (optional)")
        inst_title.setStyleSheet("font-weight: bold; font-size: 11px; color: #334155;")
        inst_badge = QLabel("READ ONLY • ISOLATED")
        inst_badge.setStyleSheet("font-size: 9px; font-weight: bold; color: #64748B; background: #EEF2F6; padding: 2px 6px; border-radius: 4px;")
        inst_header.addWidget(inst_title)
        inst_header.addWidget(inst_badge)
        inst_header.addStretch()
        inst_layout.addLayout(inst_header)

        self.input_instructions = QLineEdit()
        self.input_instructions.setPlaceholderText("e.g. please prioritize fixing memory safety issues or explain for a beginner")
        self.input_instructions.setStyleSheet(f"""
            QLineEdit {{
                background-color: #FFFFFF;
                color: #1E293B;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 5px 10px;
                font-size: 11px;
                font-family: {FONT_FAMILY};
            }}
            QLineEdit:focus {{
                border: 1px solid #7C3AED;
            }}
        """)
        inst_layout.addWidget(self.input_instructions)
        self.pane_left.content_layout.addWidget(inst_card)

        self.splitter.addWidget(self.pane_left)
        
        self.editor.textChanged.connect(self.on_code_changed)

        self.v_splitter = QSplitter(Qt.Orientation.Vertical)
        self.v_splitter.setStyleSheet(f"QSplitter::handle {{ background-color: {BG_COLOR}; }}")
        self.splitter.addWidget(self.v_splitter)

        self.pane_right_top = CustomFrame("MESSAGE LOG :: FIX SUGGESTION", left_padding=True)
        self.error_cards_scroll = QScrollArea()
        self.error_cards_scroll.setWidgetResizable(True)
        self.error_cards_scroll.setStyleSheet(f"QScrollArea {{ border: none; background-color: transparent; }}")
        
        self.error_cards_widget = QWidget()
        self.error_cards_widget.setStyleSheet(f"QWidget {{ background-color: transparent; }}")
        self.error_cards_layout = QVBoxLayout(self.error_cards_widget)
        self.error_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.error_cards_layout.setSpacing(8)
        self.error_cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        self.error_cards_scroll.setWidget(self.error_cards_widget)
        self.pane_right_top.content_layout.addWidget(self.error_cards_scroll)
        
        self.v_splitter.addWidget(self.pane_right_top)

        self.pane_right_bottom = CustomFrame("RUNNER CONSOLE :: I/O INTERFACE", left_padding=True)
        
        console_split_layout = QVBoxLayout()
        console_split_layout.setSpacing(0)
        
        self.runner_splitter = QSplitter(Qt.Orientation.Vertical)
        self.runner_splitter.setStyleSheet(f"QSplitter::handle {{ background-color: {BG_COLOR}; height: 4px; }}")

        # Input Screen
        input_container = QWidget()
        input_layout = QVBoxLayout(input_container)
        input_layout.setContentsMargins(0, 0, 0, 10)
        
        input_label = QLabel("INPUT SCREEN (stdin)")
        input_label.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        input_label.setStyleSheet(f"color: {TEXT_DIM}; margin-bottom: 4px;")
        input_layout.addWidget(input_label)
        
        self.input_area = QTextEdit()
        self.input_area.setPlaceholderText("Paste your test cases here...")
        self.input_area.setFont(QFont(FONT_FAMILY, 11))
        self.input_area.setStyleSheet(f"""
            QTextEdit {{
                background-color: {BG_COLOR};
                border: 1px solid {BORDER_COLOR};
                color: {GREEN};
                border-radius: 4px;
            }}
        """)
        input_layout.addWidget(self.input_area)
        self.runner_splitter.addWidget(input_container)

        # Output Screen
        output_container = QWidget()
        output_layout = QVBoxLayout(output_container)
        output_layout.setContentsMargins(0, 10, 0, 0)

        output_label = QLabel("OUTPUT SCREEN (stdout/stderr)")
        output_label.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        output_label.setStyleSheet(f"color: {TEXT_DIM}; margin-bottom: 4px;")
        output_layout.addWidget(output_label)

        self.terminal = TerminalDisplay()
        output_layout.addWidget(self.terminal)
        self.runner_splitter.addWidget(output_container)
        
        self.runner_splitter.setSizes([300, 500])
        console_split_layout.addWidget(self.runner_splitter)
        
        self.pane_right_bottom.content_layout.addLayout(console_split_layout)
        self.v_splitter.addWidget(self.pane_right_bottom)

        self.splitter.setSizes([700, 650])
        self.v_splitter.setSizes([500, 250])

        footer_layout = QHBoxLayout()
        err_str = str(self.errors_count) if self.compile_has_run else "-"
        warn_str = str(self.warnings_count) if self.compile_has_run else "-"
        self.status_bar_left = QLabel(f"Compiler: {self.compiler_version} | Language: {self.language_standard} | Errors: {err_str} | Warnings: {warn_str} | File Name: {self.file_name}")
        self.status_bar_left.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.Bold))
        self.status_bar_left.setStyleSheet(f"color: {TEXT_DIM};")
        footer_layout.addWidget(self.status_bar_left)
        
        footer_layout.addStretch()
        
        t2 = QLabel("● REC    ")
        t2.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.Bold))
        t2.setStyleSheet(f"color: {TEXT_DIM};")
        footer_layout.addWidget(t2)
        main_layout.addLayout(footer_layout)

        self.syntax_timer = QTimer(self)
        self.syntax_timer.setSingleShot(True)
        self.syntax_timer.timeout.connect(self._run_syntax_check)

        init_code = """// Enter your C++ code here\n"""
        self.editor.setPlainText(init_code)
        self.editor.set_errors([])
        self._update_footer()

        self.loading_prefix = ""
        self.loading_timer = QTimer(self)
        self.loading_timer.timeout.connect(self._animate_loading)
        self.loading_dots = 0
        self.is_loading = False

        # Internet Status Check
        self.net_checker = QTimer(self)
        self.net_checker.timeout.connect(self.update_net_status)
        self.net_checker.start(5000) # Check every 5 seconds
        self.update_net_status() # Initial check

    def update_net_status(self):
        # Background check to avoid UI lag
        class CheckerThread(QThread):
            status = pyqtSignal(bool)
            def run(self):
                try:
                    socket.create_connection(("8.8.8.8", 53), timeout=2)
                    self.status.emit(True)
                except OSError:
                    self.status.emit(False)
        
        self.checker = CheckerThread()
        self.checker.status.connect(self._apply_net_status)
        self.checker.start()

    def _apply_net_status(self, available):
        pass

    # ── Auto-Heal ─────────────────────────────────────────────────────────────


    def switch_to_ast(self):
        # Starts empty; content reflects file state
        if self.file_path and os.path.exists(self.file_path):
            self.status_label.setText("STATUS: ● LOADING AST... 🕒")
            self.ast_worker = ASTWorker(self.file_path)
            self.ast_worker.finished.connect(self._on_ast_ready)
            self.ast_worker.start()
        
        self.stack.setCurrentIndex(1)

    def _on_ast_ready(self, ast_tree):
        self.ast_page.update_tree(ast_tree)
        self.status_label.setText("STATUS: ● AST EXPLORER ACTIVE")

    def switch_to_call_graph(self):
        if hasattr(self, "call_graph_page"):
            self.call_graph_page.update_from_code(self.editor.toPlainText())
        self.stack.setCurrentIndex(3)

    def get_gate6_blocked_count(self, file_path=None) -> int:
        target = file_path or getattr(self, "file_path", None)
        if not target:
            return 0
        norm = os.path.abspath(target)
        cnt = getattr(self, "session_gate6_rejections", {}).get(norm, 0)
        worker = getattr(self, "heal_worker", None)
        if worker:
            w_file = getattr(worker, "file_path", None)
            if w_file and os.path.abspath(w_file) == norm:
                w_cnt = sum(1 for b in getattr(worker, "blocked_attacks", []) if b.get("gate") == "gate6_patch_security")
                if w_cnt == 0 and hasattr(worker, "trace_log"):
                    w_cnt = sum(1 for s in getattr(worker, "trace_log", []) if s.get("tool_called") in ("GATE6_SECURITY_BLOCK", "gate6_security_block"))
                cnt = max(cnt, w_cnt)
        return cnt

    def switch_to_security(self):
        findings = self.latest_security_findings
        if not findings and self.file_path and os.path.exists(self.file_path):
            try:
                findings = analyze_security(self.file_path, [])
            except Exception:
                findings = []
        gate6_count = self.get_gate6_blocked_count()
        self.security_page.update_report(findings, session_gate6_blocked=gate6_count)
        self.stack.setCurrentIndex(4)

    def switch_to_cfg(self):
        if hasattr(self, "cfg_page"):
            self.cfg_page.update_from_code(self.editor.toPlainText())
        self.stack.setCurrentIndex(5)

    def switch_to_trace(self):
        self.stack.setCurrentIndex(6)

    def switch_to_review(self):
        if hasattr(self, "review_page"):
            blocked = self._collect_blocked_findings()
            pending = list(getattr(self.heal_worker, "pending_patches", [])) if hasattr(self, "heal_worker") else []
            sugg = [p for p in getattr(self.heal_worker, "suggestions", []) if p not in pending] if hasattr(self, "heal_worker") else []
            if not self.review_page.card_widgets and not self.review_page.blocked_widgets:
                if blocked or pending or sugg:
                    self.review_page.load_patches(self.file_path, pending + sugg, blocked_findings=blocked)
        self.stack.setCurrentIndex(7)

    def _reload_editor_file(self):
        """Reload the editor content from disk after an accept/undo patch action."""
        try:
            self.editor.blockSignals(True)
            with open(self.file_path, "r", encoding="utf-8") as f:
                self.editor.setPlainText(f.read())
            self.editor.blockSignals(False)
        except Exception:
            self.editor.blockSignals(False)

        if hasattr(self, "trace_page") and hasattr(self, "review_page") and self.review_page.session:
            self.trace_page.set_user_applied_count(self.review_page.session.accepted_count)

    def _on_trace_step(self, step_record: dict):
        if hasattr(self, "trace_page"):
            self.trace_page.add_step(step_record)

    def start_review(self):
        """Launch the planner in review mode to propose patches without auto-applying."""
        if not HEALER_AVAILABLE:
            QMessageBox.warning(self, "Review Fixes", "heal_loop.py not found.")
            return
        if not self.save_file():
            return

        classifier = self.error_classifier
        if classifier is None:
            classifier = _KeywordClassifier()

        if hasattr(self, "trace_page"):
            self.trace_page.clear_trace()

        self.btn_heal.setEnabled(False)
        if hasattr(self, "btn_review"):
            self.btn_review.setEnabled(False)
        self.status_label.setText("STATUS: ● REVIEW PLANNING…")

        self.heal_worker = HealWorker(self.file_path, classifier, review_mode=True)
        self.heal_worker.attempt_started.connect(self._on_heal_attempt)
        self.heal_worker.diff_ready.connect(self._on_heal_diff)
        self.heal_worker.compile_clean.connect(self._on_heal_success)
        self.heal_worker.give_up.connect(self._on_heal_give_up)
        self.heal_worker.error_signal.connect(self._on_heal_error)
        self.heal_worker.telemetry_ready.connect(self._on_telemetry_ready)
        self.heal_worker.trace_step.connect(self._on_trace_step)
        self.heal_worker.patches_for_review.connect(self._on_patches_for_review)
        self.heal_worker.start()

    def _collect_blocked_findings(self) -> list:
        blocked = []
        if hasattr(self, "heal_worker") and getattr(self.heal_worker, "blocked_attacks", None):
            blocked.extend(self.heal_worker.blocked_attacks)
        if hasattr(self, "latest_agent_security_detections") and self.latest_agent_security_detections:
            for det in self.latest_agent_security_detections:
                snip = det.get("snippet", "")
                if not any(b.get("snippet") == snip for b in blocked):
                    blocked.append({
                        "type": det.get("attack_type", "instruction_injection"),
                        "attack_type": det.get("attack_type", "instruction_injection"),
                        "surface": det.get("surface", "line_comment"),
                        "gate": "security_guardrail",
                        "detector": "Agent Security Guardrail (Prompt Injection Scanner)",
                        "attempted": f"Adversarial instruction injection: {snip}",
                        "reason": det.get("details", {}).get("reason", "Prompt injection directive intercepted"),
                        "snippet": snip,
                        "risk_score": det.get("risk_score", 0.90),
                        "risk_tier": det.get("risk_tier", "HIGH"),
                        "action_taken": det.get("action_taken", "blocked"),
                        "line": det.get("line", 1),
                    })
        return blocked

    def _on_patches_for_review(self, patches: list):
        self.btn_heal.setEnabled(True)
        if hasattr(self, "btn_review"):
            self.btn_review.setEnabled(True)
        self.status_label.setText("STATUS: ● REVIEW READY")
        worker = getattr(self, "heal_worker", None)
        if worker and hasattr(worker, "blocked_attacks") and self.file_path:
            cnt = sum(1 for b in worker.blocked_attacks if b.get("gate") == "gate6_patch_security")
            if cnt > 0:
                self.session_gate6_rejections[os.path.abspath(self.file_path)] = cnt
        if hasattr(self, "security_page"):
            self.security_page.session_gate6_blocked = self.get_gate6_blocked_count()
        if hasattr(self, "review_page"):
            blocked = self._collect_blocked_findings()
            self.review_page.load_patches(self.file_path, patches, blocked_findings=blocked)
            self.switch_to_review()
        if hasattr(self, "security_page") and patches:
            gate_results = []
            for p in patches:
                gr = getattr(p, "gate_results", None)
                if gr:
                    if isinstance(gr, (list, tuple)):
                        gate_results.extend(gr)
                    elif isinstance(gr, dict):
                        gate_results.append(gr)
                vr = getattr(p, "verify_result", None)
                if vr:
                    vgr = getattr(vr, "gate_results", None)
                    if vgr:
                        gate_results.extend(vgr)
            if gate_results:
                self.security_page._apply_patch_gate_results(gate_results)
                self.security_page._render()

    def start_heal(self):
        """Launch the auto-heal loop in a background thread."""
        if not HEALER_AVAILABLE:
            QMessageBox.warning(self, "Auto-Heal", "heal_loop.py not found.")
            return
        if not self.save_file():
            return

        # If the ML classifier isn't loaded, use a lightweight keyword-based stub
        classifier = self.error_classifier
        if classifier is None:
            classifier = _KeywordClassifier()

        if hasattr(self, "trace_page"):
            self.trace_page.clear_trace()

        # Clear the cards pane and show a status message
        for i in reversed(range(self.error_cards_layout.count())):
            w = self.error_cards_layout.itemAt(i).widget()
            if w:
                w.setParent(None)
        
        self.editor.clear_fixed_lines()

        header = QLabel("⚕ AUTO-HEAL IN PROGRESS…")
        header.setStyleSheet(f"color: {YELLOW}; font-size: 13px; font-family: {FONT_FAMILY}; font-weight: bold;")
        self.error_cards_layout.addWidget(header)

        self.btn_heal.setEnabled(False)
        self.status_label.setText("STATUS: ● HEALING…")

        self.heal_worker = HealWorker(self.file_path, classifier, review_mode=True)
        self.heal_worker.attempt_started.connect(self._on_heal_attempt)
        self.heal_worker.diff_ready.connect(self._on_heal_diff)
        self.heal_worker.compile_clean.connect(self._on_heal_success)
        self.heal_worker.give_up.connect(self._on_heal_give_up)
        self.heal_worker.error_signal.connect(self._on_heal_error)
        self.heal_worker.lines_fixed.connect(self.editor.set_fixed_lines)
        self.heal_worker.telemetry_ready.connect(self._on_telemetry_ready)
        self.heal_worker.trace_step.connect(self._on_trace_step)
        self.heal_worker.patches_for_review.connect(self._on_patches_for_review)
        self.heal_worker.start()

    def _on_telemetry_ready(self, telemetry: list):
        for entry in telemetry:
            self.cumulative_compilation_co2 += entry.get("emissions", 0.0)

    def _on_heal_attempt(self, attempt_no: int, error: dict):
        msg = error.get("message", "?")
        cat = error.get("category", "?")
        max_attempts = 10
        try:
            from config_loader import get as cfg_get
            max_attempts = int(cfg_get("pipeline", "max_heal_attempts", 10))
        except Exception:
            pass
        lbl = QLabel(f"<b>Attempt {attempt_no}/{max_attempts}</b> — [{cat.upper()}] {msg}")
        lbl.setStyleSheet(f"color: {YELLOW}; font-size: 11px; font-family: {FONT_FAMILY};")
        lbl.setWordWrap(True)
        self.error_cards_layout.addWidget(lbl)

    def _on_heal_diff(self, attempt_no: int, diff_html: str):
        title = QLabel(f"<b>Diff — Attempt {attempt_no} (Review Pending)</b>")
        title.setStyleSheet(f"color: {TEXT_DIM}; font-size: 10px; font-family: {FONT_FAMILY};")
        self.error_cards_layout.addWidget(title)

        diff_box = QTextBrowser()
        diff_box.setOpenLinks(False)
        diff_box.setHtml(diff_html)
        diff_box.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {BG_COLOR};
                border: 1px solid {BORDER_COLOR};
                border-radius: 4px;
                padding: 4px;
                font-family: {FONT_FAMILY};
            }}
        """)
        diff_box.setMaximumHeight(160)
        diff_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.error_cards_layout.addWidget(diff_box)

    def _on_heal_success(self):
        self.btn_heal.setEnabled(True)
        if hasattr(self, "btn_review"):
            self.btn_review.setEnabled(True)
        self.status_label.setText("STATUS: ● REVIEW READY ✅")
        lbl = QLabel("✅ Fix verified through all gates — review & accept patch in Review Fixes to apply to disk.")
        lbl.setStyleSheet(f"color: {GREEN}; font-size: 13px; font-weight: bold; font-family: {FONT_FAMILY};")
        self.error_cards_layout.addWidget(lbl)
        worker = getattr(self, "heal_worker", None)
        if worker and hasattr(worker, "blocked_attacks") and self.file_path:
            cnt = sum(1 for b in worker.blocked_attacks if b.get("gate") == "gate6_patch_security")
            if cnt > 0:
                self.session_gate6_rejections[os.path.abspath(self.file_path)] = cnt
        if hasattr(self, "security_page"):
            self.security_page.session_gate6_blocked = self.get_gate6_blocked_count()
        if hasattr(self, "trace_page") and worker and hasattr(worker, "trace_log") and worker.trace_log:
            self.trace_page.set_trace_log(worker.trace_log)
        if hasattr(self, "review_page"):
            blocked = self._collect_blocked_findings()
            pending = list(getattr(worker, "pending_patches", [])) if worker else []
            sugg = [p for p in getattr(worker, "suggestions", []) if p not in pending] if worker else []
            all_patches = pending + sugg
            if blocked or all_patches:
                self.review_page.load_patches(self.file_path, all_patches, blocked_findings=blocked)
                self.switch_to_review()

    def _on_heal_error(self, msg: str):
        self.btn_heal.setEnabled(True)
        if hasattr(self, "btn_review"):
            self.btn_review.setEnabled(True)
        self.status_label.setText("STATUS: ● HEAL ERROR")
        lbl = QLabel(f"⚠️ Internal error: {msg}")
        lbl.setStyleSheet(f"color: {RED}; font-size: 11px; font-family: {FONT_FAMILY};")
        lbl.setWordWrap(True)
        self.error_cards_layout.addWidget(lbl)

    def _on_heal_give_up(self, history: list):
        self.btn_heal.setEnabled(True)
        if hasattr(self, "btn_review"):
            self.btn_review.setEnabled(True)
        self.status_label.setText("STATUS: ● HEAL FAILED")
        worker = getattr(self, "heal_worker", None)
        if worker and hasattr(worker, "blocked_attacks") and self.file_path:
            cnt = sum(1 for b in worker.blocked_attacks if b.get("gate") == "gate6_patch_security")
            if cnt > 0:
                self.session_gate6_rejections[os.path.abspath(self.file_path)] = cnt
        if hasattr(self, "security_page"):
            self.security_page.session_gate6_blocked = self.get_gate6_blocked_count()
        if hasattr(self, "trace_page") and worker and hasattr(worker, "trace_log") and worker.trace_log:
            self.trace_page.set_trace_log(worker.trace_log)
        blocked = self._collect_blocked_findings()
        if hasattr(self, "review_page"):
            pending = list(getattr(worker, "pending_patches", [])) if worker else []
            sugg = [p for p in getattr(worker, "suggestions", []) if p not in pending] if worker else []
            if blocked or pending or sugg:
                self.review_page.load_patches(self.file_path, pending + sugg, blocked_findings=blocked)
                self.switch_to_review()
        dlg = UserGuidanceDialog(history, self)
        result = dlg.exec()
        if result == UserGuidanceDialog.EDIT_MANUALLY:
            # Focus editor on the last error line
            last_err = next((h.get("error") for h in reversed(history) if h.get("error")), None)
            if last_err and last_err.get("line") is not None:
                try:
                    line_num = int(last_err["line"])
                    if line_num > 0:
                        cursor = self.editor.textCursor()
                        block = self.editor.document().findBlockByLineNumber(line_num - 1)
                        cursor.setPosition(block.position())
                        self.editor.setTextCursor(cursor)
                except (ValueError, TypeError):
                    pass
        elif result == UserGuidanceDialog.GIVE_HINT:
            hint = dlg.hint_text()
            if hint:
                classifier = self.error_classifier
                if classifier is None:
                    classifier = _KeywordClassifier()
                self.heal_worker = HealWorker(self.file_path, classifier, hint=hint)
                self.heal_worker.attempt_started.connect(self._on_heal_attempt)
                self.heal_worker.diff_ready.connect(self._on_heal_diff)
                self.heal_worker.compile_clean.connect(self._on_heal_success)
                self.heal_worker.give_up.connect(self._on_heal_give_up)
                self.heal_worker.error_signal.connect(self._on_heal_error)
                self.heal_worker.lines_fixed.connect(self.editor.set_fixed_lines)
                self.heal_worker.telemetry_ready.connect(self._on_telemetry_ready)
                self.heal_worker.trace_step.connect(self._on_trace_step)
                self.btn_heal.setEnabled(False)
                if hasattr(self, "btn_review"):
                    self.btn_review.setEnabled(False)
                self.heal_worker.start()
        # SKIP THIS ERROR — do nothing (fall through)

    def _record_execution(self):
        self.execution_count += 1
        if hasattr(self, 'sparkline'):
            self.sparkline.trigger_spike()

    def _create_error_card(self, error):
        # Extract needed fields with safe defaults
        err_line = error.get('line')
        if err_line is not None and str(err_line).strip() and str(err_line) != "?":
            default_hotspot = f"Line {err_line}"
        elif error.get('category') == 'linker_error':
            default_hotspot = "No specific line (linker error)"
        else:
            default_hotspot = "No specific line"
        hotspot = error.get('hotspot') or default_hotspot
        risk = error.get('security_risk', 'LOW')
        etype = error.get('error_type', error.get('type', 'error')).upper()
        msg = error.get('message', 'Unknown Issue')
        expl = error.get('explanation', '')
        sugg = error.get('suggestion', '')
        
        # Color mapping: Warnings get YELLOW/amber by default
        default_sev = "MEDIUM" if etype == "WARNING" else "HIGH"
        severity = error.get('severity', default_sev)
        severity_color = {
            'HIGH': RED,
            'MEDIUM': YELLOW,
            'LOW': GREEN,
        }.get(severity.upper(), YELLOW if etype == "WARNING" else RED)
        
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {PANE_BG};
                border: 1px solid {severity_color};
                border-radius: 4px;
                padding: 4px;
                margin-bottom: 4px;
            }}
        """)
        layout = QVBoxLayout(card)
        layout.setSpacing(3)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Header (Type + Message)
        header_lbl = QLabel(f"<b>[{etype}]</b> {msg}")
        header_lbl.setStyleSheet(f"color: {severity_color}; font-size: 11px; font-family: {FONT_FAMILY};")
        header_lbl.setWordWrap(True)
        layout.addWidget(header_lbl)
        
        # Stats row (Horizontal)
        stats_widget = QWidget()
        stats_layout = QHBoxLayout(stats_widget)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(5)
        
        def create_stat(emoji, text, color):
            lbl = QLabel(f"<b>{emoji} {text}</b>")
            lbl.setStyleSheet(f"color: {color}; font-size: 9px; font-family: {FONT_FAMILY}; padding: 1px 3px; border: 1px solid {BORDER_COLOR}; border-radius: 3px; background-color: {BG_COLOR};")
            return lbl

        stats_layout.addWidget(create_stat('🔥', f"HOTSPOT: {hotspot}", YELLOW))
        stats_layout.addWidget(create_stat('🛡️', f"RISK: {risk.upper()}", RED if risk.upper() == 'HIGH' else YELLOW))
        stats_layout.addStretch()
        layout.addWidget(stats_widget)
        
        # Details text
        expl_source = error.get("explanation_source", "template")
        fallback_reason = error.get("fallback_reason")

        if expl:
            # On-screen badge indicator when AI toggle is checked
            if hasattr(self, "cb_ai_explain") and self.cb_ai_explain.isChecked():
                badge_layout = QHBoxLayout()
                badge_layout.setContentsMargins(0, 0, 0, 0)
                if expl_source == "llm":
                    badge = QLabel("✨ AI-enhanced")
                    badge.setStyleSheet(f"color: {GREEN}; font-size: 9px; font-weight: bold; font-family: {FONT_FAMILY};")
                elif expl_source == "template_fallback":
                    short_reason = fallback_reason or "unknown"
                    badge = QLabel(f"⚠️ Template (fallback: {short_reason})")
                    badge.setStyleSheet(f"color: {YELLOW}; font-size: 9px; font-weight: bold; font-family: {FONT_FAMILY};")
                else:
                    badge = QLabel("📄 Template")
                    badge.setStyleSheet(f"color: {TEXT_DIM}; font-size: 9px; font-family: {FONT_FAMILY};")
                badge_layout.addWidget(badge)
                badge_layout.addStretch()
                layout.addLayout(badge_layout)

            expl_lbl = QLabel()
            expl_lbl.setTextFormat(Qt.TextFormat.PlainText)
            try:
                from llm_explainer import sanitize_for_display
                clean_expl = sanitize_for_display(expl)
            except Exception:
                clean_expl = expl
            expl_lbl.setText(clean_expl)
            expl_lbl.setStyleSheet(f"color: {TEXT_MAIN}; font-size: 10px; font-family: {FONT_FAMILY};")
            expl_lbl.setWordWrap(True)
            layout.addWidget(expl_lbl)
        if sugg:
            sugg_lbl = QLabel(f"<b>SUGGESTION:</b> {sugg}")
            sugg_lbl.setStyleSheet(f"color: {GREEN}; font-size: 10px; font-family: {FONT_FAMILY};")
            sugg_lbl.setWordWrap(True)
            layout.addWidget(sugg_lbl)

        # ── Category correction row ──────────────────────────────────────────
        # Purpose: let a human reviewer confirm or correct the classifier's
        # category prediction.  This is the ONLY path that produces classifier
        # training signal.  It writes to data/confirmed_feedback.json via
        # feedback_store.record_feedback() which uses an atomic temp-rename.
        # Patch decisions (accept/reject/undo) are strictly separate and never
        # flow through this widget.
        cat_row = QWidget()
        cat_row_layout = QHBoxLayout(cat_row)
        cat_row_layout.setContentsMargins(0, 3, 0, 0)
        cat_row_layout.setSpacing(4)

        cat_label = QLabel("Category:")
        cat_label.setStyleSheet(
            f"color: {TEXT_DIM}; font-size: 9px; font-family: {FONT_FAMILY};"
        )
        cat_row_layout.addWidget(cat_label)

        cat_combo = QComboBox()
        cat_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {BG_COLOR};
                border: 1px solid {BORDER_COLOR};
                border-radius: 3px;
                color: {TEXT_MAIN};
                font-size: 9px;
                font-family: {FONT_FAMILY};
                padding: 1px 4px;
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background-color: {PANE_BG};
                color: {TEXT_MAIN};
                font-size: 9px;
                font-family: {FONT_FAMILY};
                selection-background-color: {PINK};
                selection-color: #ffffff;
            }}
        """)
        # Populate with all canonical categories; pre-select the predicted one.
        predicted_cat = error.get("category", "") or ""
        for cat in _ALL_CATEGORIES:
            cat_combo.addItem(cat)
        idx = cat_combo.findText(predicted_cat, Qt.MatchFlag.MatchFixedString)
        if idx >= 0:
            cat_combo.setCurrentIndex(idx)
        cat_row_layout.addWidget(cat_combo)

        confirm_btn = QPushButton("✓ Category is correct")
        confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        confirm_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {BG_COLOR};
                border: 1px solid {BORDER_COLOR};
                border-radius: 3px;
                color: {TEXT_DIM};
                font-size: 9px;
                font-family: {FONT_FAMILY};
                padding: 2px 6px;
            }}
            QPushButton:hover {{
                background-color: {PINK};
                color: #ffffff;
                border-color: {PINK};
            }}
        """)
        cat_row_layout.addWidget(confirm_btn)
        cat_row_layout.addStretch()
        layout.addWidget(cat_row)

        # Status label shown after submission
        feedback_status = QLabel("")
        feedback_status.setStyleSheet(
            f"color: {GREEN}; font-size: 9px; font-family: {FONT_FAMILY};"
        )
        feedback_status.setVisible(False)
        layout.addWidget(feedback_status)

        def _on_category_confirmed():
            """Write the category correction to confirmed_feedback.json.

            Invariant: this handler writes ONLY to data/confirmed_feedback.json
            via feedback_store.record_feedback().  It never touches training_data
            directly.  The record starts with reviewed_for_merge=False and must
            be approved via `python -m src.feedback_store review approve` before
            it can be merged into training by --include-feedback.
            """
            selected_cat = cat_combo.currentText().strip()
            if not selected_cat:
                return
            label_text = "Category is correct" if selected_cat == predicted_cat else f"Corrected → {selected_cat}"
            if not _FEEDBACK_STORE_AVAILABLE or _feedback_store is None:
                feedback_status.setText("⚠ feedback_store unavailable")
                feedback_status.setVisible(True)
                return
            try:
                _feedback_store.record_feedback(
                    diagnostic=error,
                    confirmed_category=selected_cat,
                    user_notes=label_text,
                )
                confirm_btn.setText(f"✓ Saved ({selected_cat})")
                confirm_btn.setEnabled(False)
                feedback_status.setText(f"Saved to confirmed_feedback.json — awaiting human review before merge.")
                feedback_status.setVisible(True)
            except Exception as exc:
                feedback_status.setText(f"⚠ Save failed: {exc}")
                feedback_status.setVisible(True)

        confirm_btn.clicked.connect(_on_category_confirmed)

        # Pulse animation (opacity)
        effect = QGraphicsOpacityEffect(card)
        card.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(1500)
        anim.setStartValue(0.7)
        anim.setEndValue(1.0)
        anim.setLoopCount(-1)
        anim.start()

        return card

    def _create_security_attack_card(self, attack: dict):
        """
        Creates a visually distinct card for agent security attack detections (Task A1 & C2).
        
        Uses a prominent purple/violet identity to clearly distinguish between
        user code bugs (red error / yellow warning) and adversarial tool manipulation attempts.
        """
        attack_type = attack.get("attack_type", "instruction_injection")
        surface = attack.get("surface", "line_comment")
        snippet = attack.get("snippet", "")
        risk_score = attack.get("risk_score", 0.90)
        risk_tier = attack.get("risk_tier", "HIGH").upper()
        action = attack.get("action_taken", "blocked").upper()
        line_no = attack.get("line")
        details = attack.get("details", {})
        reason = details.get("reason") or attack.get("reason") or "Adversarial manipulation directive detected"
        advice = attack.get("advice")

        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background-color: #FAF5FF;
                border: 2px solid #8B5CF6;
                border-radius: 8px;
                padding: 6px;
                margin-bottom: 8px;
            }
        """)
        layout = QVBoxLayout(card)
        layout.setSpacing(6)
        layout.setContentsMargins(10, 10, 10, 10)

        # Header Row: Badge + Title + Tier
        header_row = QHBoxLayout()
        header_row.setSpacing(8)

        badge_action = QLabel(f"🛡️ ATTACK DETECTED: {action}")
        badge_action_color = "#7C3AED" if action == "BLOCKED" else "#D97706"
        badge_action.setStyleSheet(f"""
            QLabel {{
                background-color: {badge_action_color};
                color: #FFFFFF;
                font-weight: bold;
                font-size: 10px;
                font-family: {FONT_FAMILY};
                padding: 3px 8px;
                border-radius: 4px;
            }}
        """)
        header_row.addWidget(badge_action)

        title_lbl = QLabel(f"<b>Agent Manipulation Attempt</b> [{attack_type}]")
        title_lbl.setStyleSheet(f"color: #4C1D95; font-size: 12px; font-family: {FONT_FAMILY};")
        header_row.addWidget(title_lbl, 1)

        tier_lbl = QLabel(f"Tier: {risk_tier} (Risk: {risk_score:.2f})")
        tier_lbl.setStyleSheet("""
            QLabel {
                background-color: #EDE9FE;
                color: #6D28D9;
                font-weight: bold;
                font-size: 10px;
                padding: 2px 6px;
                border-radius: 4px;
            }
        """)
        header_row.addWidget(tier_lbl)
        layout.addLayout(header_row)

        # Metadata Row
        loc_str = f"Line {line_no}" if line_no else "Input field"
        meta_lbl = QLabel(f"<b>Surface:</b> {surface} ({loc_str}) &nbsp;&nbsp;|&nbsp;&nbsp; <b>Defense Target:</b> Agent Control Integrity")
        meta_lbl.setStyleSheet(f"color: #5B21B6; font-size: 10px; font-family: {FONT_FAMILY};")
        layout.addWidget(meta_lbl)

        # Flagged Snippet Box
        snippet_box = QFrame()
        snippet_box.setStyleSheet("""
            QFrame {
                background-color: #1E1B4B;
                border: 1px solid #4338CA;
                border-radius: 6px;
                padding: 6px;
            }
        """)
        snippet_layout = QVBoxLayout(snippet_box)
        snippet_layout.setContentsMargins(8, 6, 8, 6)
        lbl_snip_title = QLabel("FLAGGED ADVERSARIAL PAYLOAD:")
        lbl_snip_title.setStyleSheet("color: #C7D2FE; font-size: 9px; font-weight: bold;")
        snippet_layout.addWidget(lbl_snip_title)
        
        lbl_snip_text = QLabel(snippet)
        lbl_snip_text.setWordWrap(True)
        lbl_snip_text.setStyleSheet("color: #FDF4FF; font-family: Menlo, Consolas, monospace; font-size: 11px;")
        snippet_layout.addWidget(lbl_snip_text)
        layout.addWidget(snippet_box)

        # Reason
        reason_lbl = QLabel(f"<b>Tripwire Rule:</b> {reason}")
        reason_lbl.setStyleSheet(f"color: #6B21A8; font-size: 10px; font-family: {FONT_FAMILY};")
        reason_lbl.setWordWrap(True)
        layout.addWidget(reason_lbl)

        # Comment Hygiene Advisor Section (Task C2)
        if advice and isinstance(advice, dict):
            advice_box = QFrame()
            advice_box.setStyleSheet("""
                QFrame {
                    background-color: #FFFFFF;
                    border: 1px solid #DDD6FE;
                    border-radius: 6px;
                    padding: 6px;
                }
            """)
            adv_layout = QVBoxLayout(advice_box)
            adv_layout.setContentsMargins(8, 6, 8, 6)
            adv_layout.setSpacing(4)

            adv_header = QHBoxLayout()
            lbl_adv_title = QLabel("💡 <b>Suggestion: Improve Comment Hygiene</b> (Cosmetic / Advisory)")
            lbl_adv_title.setStyleSheet("color: #6D28D9; font-size: 10px;")
            adv_header.addWidget(lbl_adv_title, 1)

            btn_ack = QPushButton("Acknowledge")
            btn_ack.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_ack.setStyleSheet("""
                QPushButton {
                    background-color: #EDE9FE;
                    color: #5B21B6;
                    font-weight: bold;
                    border: 1px solid #C4B5FD;
                    border-radius: 4px;
                    padding: 2px 8px;
                    font-size: 9px;
                }
                QPushButton:hover { background-color: #DDD6FE; }
            """)
            def _on_ack(checked=False, b=btn_ack):
                b.setText("Acknowledged ✓")
                b.setEnabled(False)
            btn_ack.clicked.connect(_on_ack)
            adv_header.addWidget(btn_ack)
            adv_layout.addLayout(adv_header)

            adv_exp = QLabel(advice.get("explanation", ""))
            adv_exp.setWordWrap(True)
            adv_exp.setStyleSheet(f"color: #475569; font-size: 10px; font-family: {FONT_FAMILY};")
            adv_layout.addWidget(adv_exp)

            rec_text = advice.get("suggested_text", "")
            if rec_text:
                adv_rec = QLabel(f"<b>Recommended Alternative:</b> <code style='color:#7C3AED;'>{rec_text}</code>")
                adv_rec.setWordWrap(True)
                adv_rec.setStyleSheet(f"color: #334155; font-size: 10px; font-family: {FONT_FAMILY};")
                adv_layout.addWidget(adv_rec)

            layout.addWidget(advice_box)

        return card

    def _create_cascading_group_widget(self, children: list):
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(18, 0, 0, 6)
        container_layout.setSpacing(4)

        n = len(children)
        err_str = "follow-on error" if n == 1 else "follow-on errors"

        btn = QPushButton(f"▶ {n} {err_str} hidden")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {BG_COLOR};
                border: 1px dashed {BORDER_COLOR};
                border-radius: 4px;
                color: {TEXT_DIM};
                font-family: {FONT_FAMILY};
                font-size: 11px;
                font-weight: 600;
                padding: 4px 8px;
                text-align: left;
            }}
            QPushButton:hover {{
                color: {PINK};
                border-color: {PINK};
            }}
        """)

        folded_widget = QWidget()
        folded_layout = QVBoxLayout(folded_widget)
        folded_layout.setContentsMargins(0, 4, 0, 0)
        folded_layout.setSpacing(4)

        for child in children:
            child_card = self._create_error_card(child)
            folded_layout.addWidget(child_card)

        folded_widget.setVisible(False)
        is_expanded = [False]

        def toggle():
            is_expanded[0] = not is_expanded[0]
            folded_widget.setVisible(is_expanded[0])
            if is_expanded[0]:
                btn.setText(f"▼ Hide {n} {err_str}")
            else:
                btn.setText(f"▶ {n} {err_str} hidden")

        btn.clicked.connect(toggle)
        container_layout.addWidget(btn)
        container_layout.addWidget(folded_widget)
        return container

    def _get_hotspots(self):
        """Simple static analysis to find potential energy hotspots (loops/recursion)"""
        code = self.editor.toPlainText()
        hotspot = "NONE"
        lines = code.split('\n')
        
        # Heuristic: Find nested loops or many loops
        for i, line in enumerate(lines):
            if any(k in line for k in ["for", "while"]):
                hotspot = f"LINE {i+1}"
                if 'for' in line and 'for' in code.split('\n')[i+1:i+3]: # very simple nesting check
                    hotspot = f"NESTED @ L{i+1}"
                    break
        return hotspot

    def record_action_telemetry(self, action_name: str, wall_s: float, cpu_s: float, rss_mb: float):
        grid_intensity, assumed_tdp = _get_configured_telemetry_constants()
        active_time = cpu_s if cpu_s > 0.001 else wall_s
        joules = active_time * assumed_tdp
        mwh = (joules / 3600.0) * 1000.0
        kwh = joules / 3_600_000.0
        emissions_mg = kwh * grid_intensity * 1000.0

        telemetry_record = {
            "action": action_name,
            "wall_s": max(0.0001, wall_s),
            "cpu_s": max(0.0, cpu_s),
            "rss_mb": max(0.0, rss_mb),
            "energy_mwh": max(0.0, mwh),
            "emissions_mg": max(0.0, emissions_mg),
            "joules": max(0.0, joules),
            "timestamp": time.time(),
        }
        self.last_run_telemetry = telemetry_record
        self.telemetry_history.append(telemetry_record)

        if hasattr(self, "energy_page"):
            self.energy_page.display_run_telemetry(telemetry_record)

    def update_energy_dashboard(self):
        try:
            if hasattr(self, "energy_page") and getattr(self, "last_run_telemetry", None) is not None:
                self.energy_page.display_run_telemetry(self.last_run_telemetry)
        except Exception:
            pass

    def set_compiler(self, compiler_cmd: str):
        """Allow dynamically switching the compiler for this session."""
        self.compiler_cmd = compiler_cmd
        os.environ["CXX_OVERRIDE"] = compiler_cmd
        self.compiler_version = _detect_compiler_version(compiler_cmd, force_refresh=True)
        self._update_footer()

    def _update_footer(self):
        comp_ver = getattr(self, "compiler_version", _detect_compiler_version())
        lang_std = getattr(self, "language_standard", _resolve_language_standard())
        err_str = str(self.errors_count) if getattr(self, "compile_has_run", False) else "-"
        warn_str = str(self.warnings_count) if getattr(self, "compile_has_run", False) else "-"
        text = f"Compiler: {comp_ver} | Language: {lang_std} | Errors: {err_str} | Warnings: {warn_str} | File Name: {self.file_name}"
        self.status_bar_left.setText(text)

    def _animate_loading(self):
        frames = ["🍓      ", " 🍓     ", "  🍓    ", "   🍓   ", "    🍓  ", "     🍓 ", "      🍓", "     🍓 ", "    🍓  ", "   🍓   ", "  🍓    ", " 🍓     "]
        self.loading_dots = (self.loading_dots + 1) % len(frames)
        frame = frames[self.loading_dots]
        
        self.status_label.setText(f"{self.loading_prefix} {frame}")

    def toggle_output_pane(self, state):
        should_show = (state == Qt.CheckState.Checked.value)
        self.pane_right_bottom.setVisible(should_show)

    def run_code(self):
        # 1. Immediately clear terminal and cancel any ongoing process
        self.terminal.clear()
        self.editor.clear_fixed_lines()

        if hasattr(self, 'process') and self.process.state() == QProcess.ProcessState.Running:
            self.process.kill()
            self.process.waitForFinished(1000)

        # 2. Extract live code from the editor
        code = self.editor.toPlainText()
        if not code.strip():
            self.terminal.append_output(
                f"<span style='color:{PINK}; font-family:{FONT_FAMILY};'>No code to run. Editor is empty.</span>",
                is_html=True
            )
            self.status_label.setText("STATUS: ● NO CODE")
            return

        # 3. Save to file_path if possible, or create a working file
        if not self.file_path or self.file_name == "no file":
            self.file_path = os.path.join(os.getcwd(), "untitled.cpp")

        src_file = self.file_path
        try:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                f.write(code)
        except Exception:
            # Fall back to a dedicated temporary file in temp directory if file_path is not writable
            fd, src_file = tempfile.mkstemp(suffix=".cpp", prefix="live_editor_")
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(code)

        # 4. Remove any existing a.out before building to ensure no stale binary runs on build failure
        bin_path = os.path.abspath("./a.out")
        if os.path.exists(bin_path):
            try:
                os.remove(bin_path)
            except OSError:
                pass

        # 5. Compile the current editor code to a.out
        compiler = os.environ.get("CXX_OVERRIDE", "g++")
        self.status_label.setText("STATUS: ● COMPILING BINARY...")
        QApplication.processEvents()

        try:
            compile_res, compile_wall, compile_cpu, compile_rss = run_command_with_wait4(
                [compiler, "-std=c++17", src_file, "-o", bin_path],
                timeout=15,
            )
        except Exception as e:
            self.terminal.append_output(
                f"<span style='color:{PINK}; font-family:{FONT_FAMILY};'>Build Error: {str(e)}</span>",
                is_html=True
            )
            self.status_label.setText("STATUS: ● BUILD ERROR")
            return

        # 6. Check compilation result
        if compile_res.returncode != 0 or not os.path.exists(bin_path):
            self.record_action_telemetry("Compile (Failed)", compile_wall, compile_cpu, compile_rss)
            err_text = (compile_res.stderr or compile_res.stdout or "Compilation failed.").strip()
            escaped_err = (
                err_text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br>")
            )
            self.terminal.append_output(
                f"<span style='color:{PINK}; font-weight:bold; font-family:{FONT_FAMILY};'>"
                f"Compilation failed (exit code {compile_res.returncode}):</span><br>"
                f"<pre style='color:{RED}; font-family:{FONT_FAMILY}; font-size:12px;'>{escaped_err}</pre>",
                is_html=True
            )
            self.status_label.setText("STATUS: ● BUILD FAILED")
            return

        # 7. Start executing the freshly compiled binary
        self._record_execution()
        self.exec_start_time = time.perf_counter()
        self.is_loading = True
        self.loading_prefix = "STATUS: ● EXECUTING BINARY "
        self.loading_timer.start(300)

        self.terminal.clear()
        self.terminal.setReadOnly(False)
        self.terminal.setFocus()

        self.process = ProcessRunner(self)
        self.terminal.process = self.process # Link process to terminal for input
        self.process.readyReadStandardOutput.connect(self._read_process_output)
        self.process.finished.connect(self._on_process_finished)
        self.process.errorOccurred.connect(self._on_process_error)
        
        # Start the fresh binary
        self.process.start(bin_path)
        
        # Automatically send batch input if available
        input_text = self.input_area.toPlainText()
        if input_text:
            if not input_text.endswith('\n'):
                input_text += '\n'
            self.process.write(input_text.encode())

    def _read_process_output(self):
        data = self.process.readAllStandardOutput().data().decode()
        # Append to terminal
        self.terminal.append_output(data)

    def _on_process_finished(self, exit_code, exit_status):
        self.loading_timer.stop()
        self.is_loading = False

        if hasattr(self.process, "cpu_time") and getattr(self.process, "rusage", None) is not None:
            exec_wall = self.process.wall_time
            exec_cpu = self.process.cpu_time
            exec_rss = self.process.rss_mb
        else:
            exec_wall = max(0.0001, time.perf_counter() - getattr(self, "exec_start_time", time.perf_counter()))
            exec_cpu = exec_wall
            exec_rss = 0.0
        self.record_action_telemetry("Execute Binary", exec_wall, exec_cpu, exec_rss)
        
        status_msg = f"STATUS: ● PROGRAM FINISHED (EXIT: {exit_code})"
        if exit_status == QProcess.ExitStatus.CrashExit:
            status_msg = f"STATUS: ● PROGRAM CRASHED (EXIT: {exit_code})"
            
        self.status_label.setText(status_msg)
        self.terminal.setReadOnly(True)
        if not self.terminal.toPlainText().strip():
            self.terminal.append_output(
                f"<span style='color:{TEXT_DIM}; font-style:italic; font-family:{FONT_FAMILY};'>"
                f"[Program finished with exit code {exit_code} (no output)]</span>",
                is_html=True
            )

    def _on_process_error(self, error):
        self.loading_timer.stop()
        self.is_loading = False
        self.status_label.setText("STATUS: ● PROCESS ERROR")

    def view_ast(self):
        # Save first
        if not self.save_file():
            return
        self.status_label.setText("STATUS: ● EXTRACTING AST...")
        self.loading_prefix = "STATUS: ● PARSING AST "
        self.loading_timer.start(300)
        
        ast_text = extract_ast(self.file_path)
        self.loading_timer.stop()
        
        if not ast_text:
            lbl = QLabel("Failed to extract AST. Make sure clang++ is installed and code is syntactically valid.")
            lbl.setStyleSheet(f"color: {PINK}; font-family: {FONT_FAMILY};")
            lbl.setWordWrap(True)
            self.error_cards_layout.addWidget(lbl)
            self.status_label.setText("STATUS: ● AST FAILED")
            return
            
        self.status_label.setText("STATUS: ● READY")
        tree_data = parse_ast_to_tree(ast_text, self.file_path)
        
        dialog = ASTViewerDialog(tree_data, self)
        dialog.exec()

    def load_file(self, filename=None):
        if not filename:
            filename, _ = QFileDialog.getOpenFileName(self, "Open C++ Source File", "", "C/C++ Files (*.cpp *.cc *.c *.h *.hpp);;All Files (*)")
        if filename:
            self.file_path = filename
            self.file_name = os.path.basename(filename)
            self.pane_left.set_title(f"<> {self.file_name.upper()}")
            self.compile_has_run = False
            self.errors_count = 0
            self.warnings_count = 0
            self._update_footer()
            self.latest_security_findings = []
            self.latest_security_report = ""
            
            try:
                self.editor.blockSignals(True)
                with open(filename, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.editor.setPlainText(content)
                self.editor.set_errors([]) 
                self.editor.blockSignals(False)
            except Exception:
                self.editor.blockSignals(False)
                pass 

    def save_file(self):
        if not self.file_path or self.file_name == "no file":
            self.file_name = "untitled.cpp"
            self.file_path = os.path.join(os.getcwd(), self.file_name)
        try:
            content = self.editor.toPlainText()
            with open(self.file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        except Exception:
            return False

    def analyze(self):
        if self.is_loading:
            return

        if not self.save_file():
            self.terminal.append_output(f"<div style='color:{PINK};'>ERROR: Could not save file before compiling.</div>", is_html=True)
            return
        self.terminal.clear()
        self.editor.clear_fixed_lines()
        self._record_execution()
        
        # Reset error cards container for fresh run
        for i in reversed(range(self.error_cards_layout.count())):
            widget = self.error_cards_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        
        self.is_loading = True
        self.loading_prefix = "STATUS: ● ANALYZING "
        self.loading_timer.start(300)

        script_dir = os.path.dirname(os.path.abspath(__file__))
        main_script = os.path.join(script_dir, "main.py")
        cmd = [sys.executable, main_script, self.file_path, "-j", "-v"]
        if hasattr(self, "cb_ai_explain") and self.cb_ai_explain.isChecked():
            cmd.extend(["--llm-explain", "--llm-enabled"])
        if hasattr(self, "input_instructions"):
            u_inst = self.input_instructions.text().strip()
            if u_inst:
                cmd.extend(["--user-instructions", u_inst])

        self.compiler_thread = CompilerWorker(cmd)
        self.compiler_thread.finished.connect(self._on_analysis_finished)
        self.compiler_thread.start()

    def on_code_changed(self):
        self.editor.clear_fixed_lines()
        if self.errors_count > 0 or self.warnings_count > 0 or getattr(self, "compile_has_run", False):
            self.editor.set_errors([])
            self.errors_count = 0
            self.warnings_count = 0
            self.compile_has_run = False
            self.status_label.setText("STATUS: ● WAITING FOR COMPILE")
            self._update_footer()
        self.latest_security_findings = []
        self.latest_security_report = ""
        self.syntax_timer.start(2000)

    def _run_syntax_check(self):
        code = self.editor.toPlainText()
        self.syntax_worker = SyntaxWorker(code, self.file_path)
        self.syntax_worker.finished.connect(self._on_syntax_finished)
        self.syntax_worker.start()

    def _on_syntax_finished(self, errors):
        if self.errors_count == 0 and self.warnings_count == 0:
            self.editor.set_errors(errors)

    def _on_analysis_finished(self, stdout, stderr, returncode):
        self.loading_timer.stop()
        self.is_loading = False

        if hasattr(self, "compiler_thread"):
            wall_s = getattr(self.compiler_thread, "wall_time", 0.0)
            cpu_s = getattr(self.compiler_thread, "cpu_time", 0.0)
            rss_mb = getattr(self.compiler_thread, "rss_mb", 0.0)
            self.record_action_telemetry("Compile & Analyze", wall_s, cpu_s, rss_mb)
        
        try:
            data = json.loads(stdout)
            self.render_json(data, stderr)
            if hasattr(self, "call_graph_page"):
                self.call_graph_page.update_from_code(self.editor.toPlainText())
            
            # Auto-generate the AST for the just-compiled source without changing pages.
            if self.file_path and os.path.exists(self.file_path):
                self.status_label.setText("STATUS: ● BUILDING AST...")
                self.ast_worker = ASTWorker(self.file_path)
                self.ast_worker.finished.connect(self._on_compile_ast_ready)
                self.ast_worker.start()
                
        except json.JSONDecodeError:
            self.compile_has_run = True
            self.errors_count = 1 if returncode != 0 else 0
            self.warnings_count = 0
            self._update_footer()
            err_block = f"<span style='color:{PINK};'>COMPILE ERRORS OR JSON DECODE ERROR:</span><br>{stdout}<br>{stderr}"
            self.terminal.append_output(f"<div style='white-space:pre-wrap; font-family:{FONT_FAMILY};'>{err_block}</div>", is_html=True)
            self.status_label.setText("STATUS: ● ERROR")

    def _on_compile_ast_ready(self, ast_tree):
        self.ast_page.update_tree(ast_tree)
        if ast_tree:
            self.status_label.setText("STATUS: ● AST READY")
        else:
            self.status_label.setText("STATUS: ● AST UNAVAILABLE")

    def render_json(self, data, raw_stderr):
        self.compile_has_run = True
        self.terminal.clear()
        for i in reversed(range(self.error_cards_layout.count())):
            widget = self.error_cards_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        status = data.get("status", "")
        findings = data.get("security_findings", [])
        report_text = data.get("security_report", "")
        errors = data.get("errors", [])
        agent_attacks = data.get("agent_security_detections", [])

        # Extract counts, computing from errors list if not directly provided
        self.errors_count = data.get('error_count', sum(1 for e in errors if e.get('error_type', e.get('type', 'error')).lower() == 'error'))
        self.warnings_count = data.get('warning_count', sum(1 for e in errors if e.get('error_type', e.get('type', 'error')).lower() == 'warning'))
        self.latest_agent_security_detections = agent_attacks

        # Render agent attack cards FIRST at top of message log (Task A1)
        for atk in agent_attacks:
            card = self._create_security_attack_card(atk)
            self.error_cards_layout.addWidget(card)

        # Clean compilation case: Genuinely ZERO errors AND ZERO warnings
        if not errors and self.errors_count == 0 and self.warnings_count == 0:
            if not findings and not agent_attacks:
                self.status_label.setText("STATUS: ● SUCCESSFUL")
                lbl = QLabel("NO ISSUES DETECTED.")
                lbl.setStyleSheet(f"color: {PINK}; font-weight: bold; font-family: {FONT_FAMILY}; font-size: 14px;")
                self.error_cards_layout.addWidget(lbl)
                self.terminal.append_output(f"<span style='color:{TEXT_MAIN};'>Compilation finished successfully. Zero errors and zero warnings.</span>", is_html=True)
                self.editor.set_errors([])
                self.errors_count = 0
                self.warnings_count = 0
                self._update_footer()
                self.latest_security_findings = []
                self.latest_security_report = ""
                self.security_page.update_report([], session_gate6_blocked=self.get_gate6_blocked_count())
                return
            elif agent_attacks and not findings:
                self.status_label.setText(f"STATUS: ● {len(agent_attacks)} ATTACK{'S' if len(agent_attacks) != 1 else ''} BLOCKED")
                self.terminal.append_output(f"<span style='color:#A855F7; font-weight:bold;'>Compilation successful, but {len(agent_attacks)} adversarial payload(s) intercepted & blocked by Agent Security:</span><br><br>", is_html=True)
                self.editor.set_errors([])
                self.errors_count = 0
                self.warnings_count = 0
                self._update_footer()
                self.latest_security_findings = []
                self.latest_security_report = ""
                self.security_page.update_report([], session_gate6_blocked=self.get_gate6_blocked_count())
                return
            else:
                self.status_label.setText(f"STATUS: ● {len(findings)} SECURITY ISSUE{'S' if len(findings) != 1 else ''} FOUND")
                self.terminal.append_output(f"<span style='color:{YELLOW}; font-weight:bold;'>Compilation finished successfully (0 compiler errors/warnings), but {len(findings)} security finding(s) detected:</span><br><br>", is_html=True)
                if report_text:
                    self.terminal.append_output(f"<div style='white-space:pre-wrap; font-family:{FONT_FAMILY}; color:{TEXT_MAIN};'>{html.escape(report_text)}</div>", is_html=True)
                security_error_items = []
                for sf in findings:
                    sec_card_dict = {
                        "file": sf.get("file"),
                        "line": sf.get("line"),
                        "column": sf.get("column"),
                        "error_type": "SECURITY",
                        "type": "SECURITY",
                        "message": f"{sf.get('vulnerability_type')}: {sf.get('description')}",
                        "category": sf.get("vulnerability_type", "security"),
                        "severity": sf.get("severity", "High").upper(),
                        "security_risk": sf.get("severity", "HIGH").upper(),
                        "suggestion": sf.get("recommendation", ""),
                        "hotspot": f"Line {sf.get('line')}" if sf.get('line') else "No specific line",
                    }
                    security_error_items.append(sec_card_dict)
                    card = self._create_error_card(sec_card_dict)
                    self.error_cards_layout.addWidget(card)
                self.editor.set_errors(security_error_items)
                self.errors_count = 0
                self.warnings_count = 0
                self._update_footer()
                self.latest_security_findings = findings
                self.latest_security_report = report_text
                self.security_page.update_report(findings)
                return

        # Status header
        if agent_attacks:
            self.status_label.setText(f"STATUS: ● {self.errors_count} ERRORS + {len(agent_attacks)} ATTACK BLOCKED")
        elif self.errors_count > 0:
            self.status_label.setText(f"STATUS: ● {self.errors_count} ERRORS FOUND")
        elif self.warnings_count > 0:
            self.status_label.setText(f"STATUS: ● {self.warnings_count} WARNINGS FOUND")
        else:
            self.status_label.setText("STATUS: ● ISSUES FOUND")
        self._update_footer()

        self.editor.set_errors(errors)
        self.latest_security_findings = findings
        self.latest_security_report = report_text
        self.security_page.update_report(findings, session_gate6_blocked=self.get_gate6_blocked_count())
        
        compiler_html = ""
        first_err_line = None

        if agent_attacks:
            compiler_html += f"<span style='color:#A855F7; font-weight:bold;'>[AGENT DEFENSE] {len(agent_attacks)} adversarial manipulation payload(s) intercepted & blocked:</span><br><br>"

        if self.errors_count == 0 and self.warnings_count > 0:
            compiler_html += f"<span style='color:{YELLOW}; font-weight:bold;'>Compilation completed successfully with {self.warnings_count} warning(s):</span><br><br>"

        
        # Render errors as root-cause collapsible groups in the error pane
        error_groups = group_view_model(errors) if errors else []
        for grp in error_groups:
            root_card = self._create_error_card(grp.root)
            self.error_cards_layout.addWidget(root_card)
            if grp.children:
                follow_on_widget = self._create_cascading_group_widget(grp.children)
                self.error_cards_layout.addWidget(follow_on_widget)

        if findings:
            for sf in findings:
                sec_card_dict = {
                    "file": sf.get("file"),
                    "line": sf.get("line"),
                    "column": sf.get("column"),
                    "error_type": "SECURITY",
                    "type": "SECURITY",
                    "message": f"{sf.get('vulnerability_type')}: {sf.get('description')}",
                    "category": sf.get("vulnerability_type", "security"),
                    "severity": sf.get("severity", "High").upper(),
                    "security_risk": sf.get("severity", "HIGH").upper(),
                    "suggestion": sf.get("recommendation", ""),
                    "hotspot": f"Line {sf.get('line')}" if sf.get('line') else "No specific line",
                }
                card = self._create_error_card(sec_card_dict)
                self.error_cards_layout.addWidget(card)

        for idx, e in enumerate(errors):
            etype = e.get("error_type", "error").lower()
            tag_color = RED if etype == "error" else YELLOW
            msg = e.get('message', 'Unknown Issue')
            file_name = e.get("file", "unknown")
            raw_line = e.get("line")
            raw_col = e.get("column")
            
            category = e.get('category', 'Syntax / Parser Error')
            confidence = e.get('confidence', 0.92)

            try:
                line_int = int(raw_line) if raw_line is not None and str(raw_line).strip() != "?" else None
            except (ValueError, TypeError):
                line_int = None

            try:
                col_int = int(raw_col) if raw_col is not None and str(raw_col).strip() != "?" else None
            except (ValueError, TypeError):
                col_int = None

            if first_err_line is None and line_int is not None:
                first_err_line = line_int

            base_file = os.path.basename(file_name) if file_name and file_name != "unknown" else ""
            if line_int is not None:
                loc_str = f"{base_file}:{line_int}" + (f":{col_int}" if col_int is not None else "")
            elif category == "linker_error" or e.get("category") == "linker_error":
                loc_str = f"{base_file} [linker error - no specific line]" if base_file else "[linker error - no specific line]"
            else:
                loc_str = f"{base_file} [no specific line]" if base_file else "[no specific line]"

            compiler_html += f"<span style='color:{tag_color};'>[{etype.upper()}]</span> {loc_str}: <span style='color:{tag_color};'>{etype}:</span> {msg}<br>"
            
            context = e.get("context") or {}
            lines = context.get("lines", []) if isinstance(context, dict) else []
            start = context.get("start_line", 1) if isinstance(context, dict) else 1
            
            if lines and type(lines) == list:
                for i, lt in enumerate(lines, start=start):
                    txt = lt.replace('<','&lt;').replace('>','&gt;').rstrip()
                    if line_int is not None and i == line_int:
                        compiler_html += f" <span style='color:{tag_color};'>&gt;</span> {i:3} | <b style='color:{TEXT_MAIN}'>{txt}</b><br>"
                        if col_int is not None and col_int > 0:
                            compiler_html += f"       {' ' * (len(str(i)) + 2 + col_int)}<span style='color:{tag_color}'>^</span><br>"
                    else:
                        compiler_html += f"   {i:3} | <span style='color:{TEXT_DIM}'>{txt}</span><br>"
            compiler_html += "<br>"

        compiler_html += f"<br>C++_ANALYZER_V2.0.1_READY > _"
        self.terminal.append_output(f"<div style='white-space:pre-wrap; font-family:{FONT_FAMILY};'>{compiler_html}</div>", is_html=True)


def main():
    app = QApplication(sys.argv)
    window = AppGUI()
    window.show()
    exit_code = app.exec()
    if CODECARBON_AVAILABLE and hasattr(window, 'tracker'):
        try:
            window.tracker.stop()
        except:
            pass
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
