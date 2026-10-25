# Energy Telemetry Diagnostic Audit Report (Task 1)

**Date:** October 21, 2026  
**Auditor:** Independent Engineering Verification  
**Focus:** Diagnostic Audit of Energy Telemetry Panel, Error Card Badges, Status Bar, and CodeCarbon Configuration  
**Environment:** macOS (Apple Silicon arm64), Python 3.13.9, Apple Clang 21.0.0 (clang-2100.3.34.2)  

---

## 1. Executive Summary

A comprehensive forensic audit of `src/gui.py`, `src/heal_loop.py`, and related pipeline components was performed to evaluate the veracity of the "CODECARBON INDEX :: ENERGY TELEMETRY" panel, error card badges, and telemetry displays.

The audit reveals that **none of the numbers previously displayed on the Energy Telemetry panel or error cards represented valid, real-time measurements of compiler or execution activity on this machine**:
1. **Error Card CPU & Memory Badges**: Hardcoded static strings (`"2.5"` mWh and `"12 MB"`) pasted unconditionally onto every single error card, regardless of error type, file size, or compiler workload.
2. **Error Card CO₂ Badge**: Dynamically accumulated by adding `0.000005` on a modulo counter every 5 clicks of the compile/run button, completely decoupled from actual energy consumption.
3. **Execution Time**: Measured process uptime (`time.monotonic() - self.energy_started_at`) since the GUI was launched, resulting in a continuously increasing or stale idle duration rather than the runtime of the last compile/run operation.
4. **RAPL Reading**: Looked for Linux sysfs interface `/sys/class/powercap`, which does not exist on macOS Darwin, previously yielding "Unavailable" or "0.000 kWh" without clearly conveying platform incompatibility.
5. **Power Usage & Carbon Intensity**: In the absence of live samples, synthetic sine waves with pseudo-random jitter (`random.uniform(-18, 18)`) were computed and displayed to give the illusion of live activity. Furthermore, when reading `emissions.csv`, energy in kilowatt-hours (`kWh`) was multiplied by 1,000,000 to produce milliwatt-hours (`mWh`, energy), but erroneously labeled as `"Power Usage"` with unit `"mW"` (power).
6. **Metrics Graph**: Plotted each series normalized to its own local maximum with generic "High"/"Low" axis markers, producing an arbitrary ramp-and-flatline artifact for monotonic time and meaningless trends.
7. **Compiler Status Bar**: Hardcoded to `"Compiler: GCC 11.4"`, ignoring the actual host toolchain (`Apple clang version 21.0.0`).

---

## 2. Telemetry Value Source-of-Truth Table

| Telemetry Element | UI Display Location | Exact Source (File & Line) | Value Classification | Detailed Finding & Mechanism |
|---|---|---|---|---|
| **Power Usage** | Energy Panel (`self.power_value`) | `src/gui.py:4390-4393` | **(d) Random / Synthetic** | When no sample is available: `base_mw = 900.0`, `wave = 120.0 * sin(t/2.5) + ...`, `jitter = random.uniform(-18.0, 18.0)`. Pure mathematical simulation. |
| **Power Usage (CSV Polled)** | Energy Panel (`self.power_value`) | `src/gui.py:1498-1500` | **(c) Dimensional Unit Error** | Reads `energy_consumed` (kWh) from CSV, multiplies by 1e6, and labels the resulting mWh (energy) as "Power Usage" in "mW". |
| **Carbon Intensity** | Energy Panel (`self.carbon_value`) | `src/gui.py:4394` | **(d) Random / Synthetic** | Simulated via `max(0.05, 0.42 + 0.04 * math.sin(t / 4.0)) mgCO2/Wh`. |
| **Execution Time** | Energy Panel (`self.time_value`) | `src/gui.py:4364` | **(c) Misleading (GUI Uptime)** | Computed as `time.monotonic() - self.energy_started_at`. Measures total GUI application uptime, not action execution time. |
| **Execution Time (CSV Polled)** | Energy Panel (`self.time_value`) | `src/gui.py:1504` | **(c) Stale Historical** | Reads static `duration` column from old `emissions.csv` row (e.g. 19.405 s) while idle. |
| **RAPL** | Energy Panel (`self.rapl_value`) | `src/gui.py:100-117, 4401-4407` | **(a) Platform Unavailable** | Inspects `/sys/class/powercap`. On macOS Darwin this directory never exists. Returns `None` and displays "Unavailable". |
| **Per-Card CPU** | Message Log Error Card | `src/gui.py:3905, 3962` | **(c) Hardcoded Literal** | `cpu = "2.5"` labeled as `CPU: 2.5 mWh`. Hardcoded string literal on every card. |
| **Per-Card MEM** | Message Log Error Card | `src/gui.py:3906, 3963` | **(c) Hardcoded Literal** | `mem = "12 MB"`. Hardcoded string literal on every card. |
| **Per-Card CO₂** | Message Log Error Card | `src/gui.py:3901, 3915, 3965` | **(d) Synthetic Click Accumulator** | `self.manual_co2_offset += 0.000005` every 5 executions; card formats `(manual_co2_offset * 1e6):.2f mg`. |
| **Per-Card HOTSPOT** | Message Log Error Card | `src/gui.py:3907-3914, 3964` | **(a) Measured / Extracted** | Extracted from diagnostic error line (e.g. `Line 12`) or linker fallback. Genuinely corresponds to diagnostic location. |
| **Per-Card RISK** | Message Log Error Card | `src/gui.py:3916, 3966` | **(b) Estimated (Model/Rule)** | Extracted from security analyzer CWE assessment (`HIGH`, `MEDIUM`, `LOW`). |
| **Sparkline Graph** | Header Top Bar | `src/gui.py:270-282` | **(d) Random / Synthetic** | `noise = random.uniform(0, 2)` on 200ms timer; spikes injected via `random.uniform(15, 25)`. |
| **Metrics Graph Series** | Energy Panel Chart | `src/gui.py:329-397` | **(d) Synthetic / Misleading** | Normalizes Power, Carbon, and Time independently to `max(data)`. Y-axis has only "High"/"Low" labels without units. |
| **Compiler Version** | Status Bar Footer | `src/gui.py:3496, 4426` | **(c) Hardcoded Literal** | Literal string `"Compiler: GCC 11.4"` while the system compiler is Apple Clang 21.0.0. |

---

## 3. CodeCarbon Configuration Analysis on macOS

### 3.1 Powermetrics Monkey-Patch
In `src/gui.py` lines 3221–3226:
```python
if platform.system() == "Darwin":
    try:
        import codecarbon.core.powermetrics as powermetrics
        powermetrics.is_powermetrics_available = lambda: False
    except Exception:
        pass
```
On Apple Silicon macOS, CodeCarbon can only obtain real hardware power measurements if `powermetrics` is invoked with elevated root (`sudo`) privileges. To avoid prompting the user for passwords or crashing in non-interactive GUI environments, `is_powermetrics_available` was explicitly monkey-patched to return `False`.

### 3.2 Fallback Tracking Mode
In `src/gui.py` lines 3228–3235:
```python
self.tracker = EmissionsTracker(
    save_to_file=False,
    log_level="error",
    force_cpu_power=12,
    force_ram_power=3,
    force_mode_cpu_load=True,
    allow_multiple_runs=True,
)
```
Because `powermetrics` is forced to `False` and `/sys/class/powercap` does not exist on Darwin:
- CodeCarbon operates in fallback **TDP-based estimation mode**.
- It assumes a static CPU TDP of **12 Watts** (`force_cpu_power=12`) and RAM TDP of **3 Watts** (`force_ram_power=3`).
- It estimates energy consumption as:
  $$\text{Energy (kWh)} = \frac{(\text{CPU Load \%} \times 12\,\text{W} + 3\,\text{W}) \times \Delta t}{3\,600\,000}$$
- This is an **uncalibrated software model estimate**, not a physical measurement.

### 3.3 CSV Column Units & Dimensional Inconsistency
In CodeCarbon's standard `emissions.csv`:
- `duration`: elapsed tracking time in seconds ($s$).
- `emissions`: total emissions in kilograms of $\text{CO}_2$ ($kg$).
- `energy_consumed`: cumulative total energy consumed in kilowatt-hours ($kWh$).
- `cpu_energy`, `ram_energy`: cumulative energy consumed by CPU/RAM in kilowatt-hours ($kWh$).

In `src/gui.py` lines 1498–1506:
```python
energy_kwh = float(latest.get("energy_consumed", 0))
power_mw = energy_kwh * 1_000_000  # kWh to mWh
...
self.update_metrics(power_mw, intensity, duration, rapl_text, ...)
```
Converting $kWh \times 10^6$ gives **milliwatt-hours ($mWh$, energy)**. Displaying this value under the label **"Power Usage"** with unit **"mW" (power)** represents a fundamental dimensional error ($Power \neq Energy$).

### 3.4 Execution Time Mechanism
In `src/gui.py` line 3177:
```python
self.energy_started_at = time.monotonic()
```
And in line 4364:
```python
elapsed = max(0.0, time.monotonic() - getattr(self, "energy_started_at", time.monotonic()))
```
`energy_started_at` was recorded once at GUI startup. As a result:
- The "Execution Time" field tracked the total idle uptime of the GUI process.
- It did not reset when compiling, running code, or executing auto-heal.
- While the application sat idle with "READY TO ANALYZE", the timer continued to report irrelevant elapsed time.

---

## 4. Complete Codebase Grep for Telemetry Literals

A search across `src/gui.py` for all telemetry-related literals, random generators, and synthetic signals yields the following exact hits:

```text
src/gui.py:100: def _read_rapl_energy_joules():
src/gui.py:257: class SparklineGraph(QWidget):
src/gui.py:271:         noise = random.uniform(0, 2)
src/gui.py:281:         self.add_value(random.uniform(15, 25))
src/gui.py:282:         self.add_value(random.uniform(10, 15))
src/gui.py:3176:        self.manual_co2_offset = 0.0
src/gui.py:3178:        self.rapl_start_j = _read_rapl_energy_joules()
src/gui.py:3212:            self.sparkline = SparklineGraph()
src/gui.py:3223:                        import codecarbon.core.powermetrics as powermetrics
src/gui.py:3224:                        powermetrics.is_powermetrics_available = lambda: False
src/gui.py:3231:                    force_cpu_power=12,
src/gui.py:3232:                    force_ram_power=3,
src/gui.py:3496:        self.status_bar_left = QLabel("Compiler: GCC 11.4 | Language: C++17 | Errors: 1 | Warnings: 0 | File Name: file.cpp")
src/gui.py:3901:            self.manual_co2_offset += 0.000005
src/gui.py:3905:        cpu = "2.5" # Now in mWh
src/gui.py:3906:        mem = "12 MB"
src/gui.py:3915:        co2 = f"{(self.manual_co2_offset * 1e6):.2f}"
src/gui.py:4376:            emissions_mg = (emissions_kg + self.manual_co2_offset) * 1e6
src/gui.py:4391:                wave = 120.0 * math.sin(t / 2.5) + 45.0 * math.sin(t / 0.9)
src/gui.py:4392:                jitter = random.uniform(-18.0, 18.0)
src/gui.py:4394:                carbon_mg_per_wh = max(0.05, 0.42 + 0.04 * math.sin(t / 4.0))
src/gui.py:4401:            rapl_now = _read_rapl_energy_joules()
src/gui.py:4426:        text = f"Compiler: GCC 11.4 | Language: C++17 | Errors: {self.errors_count} | Warnings: {self.warnings_count} | File Name: {self.file_name}"
```

---

## 5. Architectural Corrective Actions Required

1. **Honest Idle State**:
   - Before any compile, run, or heal action occurs, the Energy Telemetry panel must display `"No run yet"` / `"No measurement yet"`.
   - The chart must display an empty state or explicit notice: `"No run recorded yet. Compile or run code to capture telemetry."`

2. **Accurate Action Scoping**:
   - Each action (Compile, Run Code, Auto-Heal) must independently track:
     - **Wall-clock duration**: `time.perf_counter()` elapsed between start and completion.
     - **CPU time**: Child process user + system CPU time delta via `resource.getrusage(resource.RUSAGE_CHILDREN)` or `psutil`.
     - **Peak memory**: Child process `ru_maxrss`. Crucially: on macOS `ru_maxrss` is reported in **bytes**; on Linux it is reported in **kilobytes**. The code must branch on `sys.platform == 'darwin'` to convert correctly to Megabytes ($MB$).

3. **Honest [measured] vs [estimated] Distinctions**:
   - Wall-clock time, CPU time, and Peak Memory are **[measured]**.
   - Energy (derived as $\text{CPU-seconds} \times \text{assumed TDP of } 15\,\text{W}$) is explicitly labeled **[estimated]**, stating the TDP assumption in the UI note.
   - Carbon (derived as $\text{Energy} \times \text{grid intensity}$) is explicitly labeled **[estimated]**.
   - RAPL on macOS displays: `"N/A (not supported on this OS)"` with tag **[unavailable]**.

4. **Error Card Badge Attribution Decision**:
   - One compilation processes the entire file and produces all diagnostics simultaneously. Attributing arbitrary CPU energy (e.g. 2.5 mWh) or memory (12 MB) to individual errors is scientifically invalid.
   - **Decision**: Remove the fake `CPU: 2.5 mWh`, `MEM: 12 MB`, and synthetic `CO₂` badges from individual error cards. Preserve `HOTSPOT` (diagnostic location) and `RISK` (security classification), which are legitimate per-error attributes. Display the action-level telemetry in the Energy Telemetry panel.

5. **Dynamic Compiler Version Detection**:
   - Replace `"Compiler: GCC 11.4"` with dynamic detection executing `clang++ --version` / `g++ --version` at initialization, returning `"Apple Clang 21.0.0"`.

6. **Chart & CSV Report Honesty**:
   - Replace the normalized 0..1 graph with real time-series / historical points for completed runs, clearly labeled with units ($s$, $MB$, $J$, $mg$).
   - The CSV download button must export the actual audit record with explicit columns: `action, wall_clock_s [measured], cpu_time_s [measured], peak_rss_mb [measured], energy_joules [estimated], carbon_mg [estimated], platform, timestamp`.
