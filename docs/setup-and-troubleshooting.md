# Setup & Troubleshooting

This is the actual working setup guide for the Open-Motion device. Consult it whenever the user mentions any install, driver, USB, enumeration, or "I just got the device" situation.

---

## Prerequisites

- Python **3.10+**
- `pip` (or `conda` / `uv` / `poetry` — but the SDK ships a requirements.txt so pip is the path of least resistance)
- Git
- **Admin access on the machine** — needed for USB driver installation on Windows, `udev` rules on Linux

---

## Step 1 — Clone the SDK

```bash
git clone https://github.com/OpenwaterHealth/openmotion-sdk.git
cd openmotion-sdk
```

The entire system revolves around this repo. Its `docs/` folder is the actual manual (Architecture.md, SciencePipeline.md, CameraArrangement.md, scan-sequencing.md, MOTION_Interface_API.md). When in doubt, point the user there.

---

## Step 2 — Install Python dependencies

```bash
pip install -r requirements.txt
```

This pulls `pyserial`, `pyusb`, `libusb1`, `crcmod`, `numpy`, `matplotlib`, `keyboard`, `requests`. Versions are pinned — don't casually upgrade numpy past 2.2 or you may hit compatibility issues.

Optionally build and install the `omotion` library as a wheel:

```bash
python -m pip install --upgrade build
python -m build
python -m pip install --force-reinstall dist/openmotion_sdk-*-py3-none-any.whl
```

This makes `from omotion.Interface import MOTIONInterface` work from anywhere.

---

## Step 3 — Install libusb (the #1 setup failure)

### Windows

1. Download `libusb-1.0.dll` from [libusb releases](https://github.com/libusb/libusb/releases) (take the MSVC x64 variant).
2. Copy it to `C:\Windows\System32`.
3. Install **Zadig** from [zadig.akeo.ie](https://zadig.akeo.ie).
4. Plug in the Open-Motion device.
5. In Zadig: *Options → List All Devices*. Find each sensor module (VID `0483`).
6. Change the driver to **WinUSB** or **libusbK** and click *Replace Driver*.
7. Leave the console module alone — it's a Virtual COM Port and Windows handles it natively.

### Linux

```bash
sudo apt install libusb-1.0-0  # or equivalent for your distro
```

Create `/etc/udev/rules.d/99-openmotion.rules`:

```
SUBSYSTEM=="usb", ATTRS{idVendor}=="0483", MODE="0666"
```

Reload:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

This avoids having to `sudo` every SDK call.

### macOS

```bash
brew install libusb
```

No driver binding needed. The VCP shows up as `/dev/tty.usbmodem*`.

### Verify libusb works

```bash
python -c "import usb, omotion.usb_backend as ub; print(ub.get_libusb1_backend())"
```

Should print a backend object. If it raises, libusb is not found or the DLL is in the wrong location.

---

## Step 4 — First connection

1. Plug in **console + both sensor modules**.
2. **Wait at least 10 seconds.** The aggregator boots slowly. Running anything before it's enumerated produces confusing errors.
3. Sanity-check:
   ```bash
   python scripts/test_connection.py
   ```
4. Check left/right assignment:
   ```bash
   python scripts/test_console_if.py
   ```
   Left/right is determined by USB port topology (`port_numbers[-1] == 2` → left, `== 3` → right). If they're swapped, physically swap the USB cables.

---

## Step 5 — Flash the cameras

Each of the 8 cameras per sensor module needs its iCE40 FPGA loaded with a bitstream and its OV2312 registers programmed. This is a one-time-per-boot operation.

```bash
python scripts/multicam_setup.py        # all 8 cameras, both sides
```

or for a single camera:

```bash
python scripts/flash_camera.py 1        # camera 1 only (valid: 1-8)
```

Cameras are numbered 1–8 and correspond to physical connectors **J1–J8** on the aggregator board. A failed flash usually means the camera isn't physically connected or the I²C mux is stuck — power-cycle the whole system.

---

## Step 6 — First scan

```bash
python scripts/capture_data.py --subject-id TEST --duration 30 --camera-mask 0xFF
```

Parameters:
- `--subject-id` — required, any string. Goes into filenames.
- `--duration` — seconds. Max 120 in the default script (patch `MAX_DURATION` if longer scans are needed).
- `--camera-mask` — bitmask. `0xFF` = all 8 cameras, `0x11` = cameras 0 and 4, etc.
- `--disable-laser` — disables external frame sync (for dark tests only).
- `--data-dir` — defaults to `scan_data/`.

Output files (in `scan_data/`):

```
scan_<subject>_<timestamp>_left_mask<hex>.csv    # raw histograms, left
scan_<subject>_<timestamp>_right_mask<hex>.csv   # raw histograms, right
scan_<subject>_<timestamp>_corrected.csv         # dark-corrected BFI/BVI/contrast/mean/temp
scan_<subject>_<timestamp>_telemetry.csv         # console health log
```

Scans shorter than the dark interval (15 s default) will have a sparse corrected CSV — the SDK's terminal-dark-flush handles this, but the best practice is to run at least 30 seconds.

---

## The error decision tree

Run through this in order when something breaks:

### libusb errors

| Symptom | Cause | Fix |
|---|---|---|
| `OSError: [WinError 126]` or "could not find DLL" | libusb DLL missing | Copy `libusb-1.0.dll` to `C:\Windows\System32`. |
| `NoBackendError` | pyusb can't find the backend | Same as above, plus verify `pip show libusb1` returns something. |
| Device enumerates but I/O times out | Wrong Windows driver | Run Zadig, rebind the sensor module to **WinUSB** or **libusbK**. Console stays VCP. |
| `Access denied` on Linux | udev rule missing | Add the rule from Step 3, reload, replug the device. |

### Enumeration errors

| Symptom | Cause | Fix |
|---|---|---|
| "No sensor modules found" | Too soon after plug-in | Wait 10 seconds, retry. |
| Only one sensor found | Cable / topology | Check both USB cables; the SDK assigns left/right from port topology. |
| Left/right swapped | Physical cabling | Swap the USB cables on the host side. |
| Console not found | Wrong COM port | `python -c "from serial.tools import list_ports; print([p.device for p in list_ports.comports()])"` and verify the VID is `0483`. |

### Scan errors

| Symptom | Cause | Fix |
|---|---|---|
| All frames rejected, `WARNING: histogram sum mismatch` | USB corruption or firmware-SDK version mismatch | Re-flash firmware (`motion-sensor-fw`, `motion-console-fw`). Check USB cable quality. |
| "First frame rejected as stale" | Sensor has old data buffered from a prior scan | Unplug / replug the sensor. SDK drops any frame whose first raw `frame_id` isn't 1. |
| Corrected CSV empty | Scan shorter than dark interval | Run ≥30 seconds. The terminal-dark-flush covers short scans but needs at least frame 10 + one more bright frame. |
| BFI clipped at 0 or 10 | Calibration arrays are stock defaults | Get per-device calibration from the vendor, or use raw contrast K directly. |
| Camera `N` all zeros | Camera physically disconnected or I²C mux stuck | Check J1–J8 connector for that camera. Power-cycle. |

### Camera flash errors

| Symptom | Cause | Fix |
|---|---|---|
| `flash_camera.py` hangs | I²C mux stuck | Power-cycle (unplug power, not just USB). |
| "FPGA verify failed" | Intermittent I²C | Retry once; if persists, the FPGA bitstream in the sensor firmware is corrupt — re-flash `motion-sensor-fw`. |
| "Camera not present" | Physical disconnect | Check J-connector. Each camera's `isPresent` is set by firmware after FPGA load. |

### Data quality warnings (not errors, but worth investigating)

| Indicator | Meaning |
|---|---|
| Many dropped frames (>5%) | USB bandwidth issue — try a different USB 3.0 port, direct connection (no hub) |
| Very high / very low pedestal | ADC drift; check temperature, let laser warm up |
| Flat BFI trace | Sensor not in contact with skin, or laser off — check the telemetry CSV for TEC/laser-good flags |
| Oscillating BFI at ~1 Hz | **This is normal.** It's the cardiac pulse. See `visualization-patterns.md` for how to extract heart rate from it. |

---

## When to re-flash firmware

Only re-flash if:
- The SDK rejects all frames with sum mismatch (likely version mismatch)
- A camera flash repeatedly fails (corrupt sensor firmware)
- The vendor has shipped a new firmware release with a feature you need

Firmware repos: `motion-sensor-fw`, `motion-console-fw`, `openmotion-console-v2`. All require STM32CubeIDE or equivalent ARM toolchain. Safety FPGA (`motion-safety-fpga`) requires Lattice Diamond. If the user is asking how to flash firmware, confirm they understand they're modifying a medical research device and are responsible for re-verifying safety operation afterwards.

---

## Useful SDK scripts beyond the basics

| Script | Purpose |
|---|---|
| `scripts/test_connection.py` | Check console + both sensors are visible |
| `scripts/test_console_if.py` | Query console version, fans, PDU |
| `scripts/test_sensor_if.py` | Query sensor modules |
| `scripts/test_live_stream.py` | Live histogram stream, useful for signal checks |
| `scripts/get_temperature.py` | Quick laser / TEC temperature readout |
| `scripts/test_fan_control.py` | Spin the cooling fans to check thermal path |
| `scripts/enter_dfu.py` | Put a module into DFU mode for firmware update |
| `scripts/soft_reset_console.py` | Soft reset without power cycle |
| `scripts/plot_telemetry.py` | Visualize a telemetry CSV (official) |

If the user reports something weird, running `test_live_stream.py` for 30 seconds and inspecting the spectrograms (with `data-processing/plot_all_spectrogram.py`) is the fastest way to localize the problem.

---

## Cross-references inside this skill

- CSV format details → `data-formats.md`
- Math behind BFI/BVI → `science-pipeline.md`
- How to plot → `visualization-patterns.md`
