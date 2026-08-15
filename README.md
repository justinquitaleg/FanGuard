# 🌀 FanGuard — Acer Aspire 7 Auto Fan Control

Automatically boosts your fans to MAX when your CPU/GPU hits a temperature threshold, then returns to AUTO when it cools down. Runs silently in your system tray with a live temperature badge.

---

## 📋 Prerequisites

### 1. Keep NitroSense installed (but you don't need to open it)
FanGuard communicates directly with NitroSense's background service (`PSSvc`) to read temperatures, fan RPMs, and control fan speeds. The NitroSense app must be **installed**, but you never need to open it — FanGuard handles everything automatically.

> **No LibreHardwareMonitor required.** Temperature and RPM data is read directly from the NitroSense service pipe.

### 2. Python 3.10+
Download from: https://python.org

---

## 🚀 How to Run

### Option A — Double-click launcher (easiest)
1. Double-click **`Start FanGuard.bat`**
2. Accept the UAC elevation prompt (Administrator required)
3. The FanGuard icon will appear in your system tray

### Option B — Run manually
```
python fan_guard.py
```
(FanGuard will auto-elevate itself to Administrator)

---

## 🎮 System Tray

Once running, look for the FanGuard icon in the system tray (bottom-right, in "Show hidden icons").

| Icon | Meaning |
|------|---------|
| 🟢 Green circle with temp | Fan in AUTO mode — BIOS controls it |
| 🔴 Red circle with temp | Fan boosted to MAX speed |

**Double-click** the tray icon to open the settings window.  
**Right-click** for quick actions: Open Settings or Quit.

Closing the settings window does **not** exit FanGuard — it keeps running in the tray.

---

## 🖥 Settings Window

The GUI lets you:

- View **live CPU & GPU temperature** and **fan RPM** in real time
- Set the **boost threshold** — fan goes MAX when temp hits this (°C)
- Set the **cooldown temperature** — fan returns to AUTO when temp drops below this (°C)
- **Force MAX** fan speed manually (stays on MAX until you click Force AUTO)
- **Force AUTO** to hand control back to the automatic monitor

---

## ⚙ Configuration

Settings are saved automatically when you move the sliders. They're stored in `fan_guard_config.json`:

```json
{
  "temp_threshold": 70,
  "check_interval": 3,
  "cooldown_temp": 60,
  "monitor_type": "CPU"
}
```

| Key | Description |
|-----|-------------|
| `temp_threshold` | Boost fan when temp reaches this (°C) |
| `check_interval` | How often to check temperature (seconds) |
| `cooldown_temp` | Return to AUTO when temp drops below this (°C) |
| `monitor_type` | `"CPU"`, `"GPU"`, or `"BOTH"` |

---

## 🔁 Auto-Start on Boot

FanGuard automatically registers itself in **Windows Task Scheduler** the first time it runs. It will launch on every login with admin rights, with a 1-minute delay to let the NitroSense service load first.

To verify: open **Task Scheduler** and look for `FanGuard_AutoStart`.

---

## 🔧 Troubleshooting

### Temperatures or RPMs show `--`
- Make sure NitroSense is **installed** (the background service `PSSvc` must be running)
- Try restarting the NitroSense service: open **Services** (`services.msc`), find **PredatorSense Service** or **NitroSense Service**, and click **Restart**

### Fan doesn't respond to MAX / AUTO
- Ensure FanGuard is running as **Administrator** (the `.bat` launcher handles this)
- The NitroSense service must be running in the background

### Script won't start
Make sure Python is installed:
```
python --version
```
Install dependencies manually if needed:
```
pip install wmi pystray pillow pywin32
```

---

## 📁 Files

| File | Purpose |
|------|---------|
| `fan_guard.py` | Main app — tray icon, temperature monitor, fan control |
| `Start FanGuard.bat` | Easy launcher with admin elevation |
| `wmi_explorer.py` | Diagnostic tool — lists available WMI classes on your system |
| `fan_guard_config.json` | Settings file (auto-created on first run) |
| `fan_guard.log` | Activity log (auto-created) |

---

## ⚠ Important Notes

- Always run as **Administrator** — hardware access requires it
- Fan control works by communicating directly with the NitroSense background service via IPC named pipe
- FanGuard restores AUTO mode when you quit it cleanly via the tray menu
- Tested on: **Acer Aspire 7 N19C5** with NitroSense v3.01.3020
