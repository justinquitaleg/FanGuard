# 🌀 FanGuard — Acer Aspire 7 Auto Fan Control

Auto-boosts your fan to MAX when your CPU/GPU hits a temperature threshold, then returns to AUTO when it cools down.

---

## 📋 Prerequisites

### 1. Install LibreHardwareMonitor
**This is required for temperature reading.**

1. Download from: https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases
2. Extract and run `LibreHardwareMonitor.exe` **as Administrator**
3. In the menu: **Options → Remote Web Server → Run** ✅
4. In the menu: **Options → Run On Windows Startup** ✅ (so it stays running)
5. Minimize to tray — it must stay running in the background

### 2. Keep NitroSense installed
NitroSense provides the underlying drivers that talk to the embedded controller.
You don't need to have it open, but it must be installed.

### 3. Python 3.10+
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

Once running, look for the FanGuard icon in the system tray (bottom-right).

| Icon | Meaning |
|------|---------|
| 🟢 Green circle with temp | Fan in AUTO mode — BIOS controls it |
| 🔴 Red circle with temp + "MAX" | Fan boosted to MAX speed |

**Right-click the icon to:**
- See live CPU + GPU temperatures
- Force MAX or AUTO fan mode manually
- Change the temperature threshold (default: 70°C)
- Change the cooldown temperature (default: 60°C)
- Open the log file
- Quit (automatically restores AUTO mode)

---

## ⚙ Configuration

Edit `fan_guard_config.json` (or use the tray menu):

```json
{
  "temp_threshold": 70,    ← Boost fan when temp >= this (°C)
  "check_interval": 3,     ← Check temperature every N seconds
  "cooldown_temp": 60,     ← Return to AUTO when temp <= this (°C)
  "monitor_type": "CPU",   ← "CPU", "GPU", or "BOTH"
  "show_log": true
}
```

---

## 🔧 Troubleshooting

### Temperatures show "N/A"
- Make sure LibreHardwareMonitor is running
- Make sure **Options → Remote Web Server → Run** is checked in LHM
- Make sure nothing else is using port 8085

### Fan doesn't change
Run the WMI explorer to check what's available on your laptop:
```
python wmi_explorer.py
```
Then share the output so the fan control can be tuned for your exact model.

### Script won't start
Make sure Python is installed:
```
python --version
```
Install dependencies manually:
```
pip install wmi pystray pillow
```

---

## 🔁 Auto-Start on Boot (optional)

To have FanGuard start automatically with Windows:

1. Press `Win + R`, type `shell:startup`, press Enter
2. Create a shortcut to `Start FanGuard.bat` in that folder
3. Or use Task Scheduler (recommended for proper admin elevation):
   - Open Task Scheduler
   - Create Task → check "Run with highest privileges"
   - Trigger: At logon
   - Action: `pythonw.exe` with argument `"C:\path\to\fan_guard.py"`

---

## 📁 Files

| File | Purpose |
|------|---------|
| `fan_guard.py` | Main app — tray icon + temperature monitor + fan control |
| `Start FanGuard.bat` | Easy launcher |
| `wmi_explorer.py` | Diagnostic tool — shows available WMI classes |
| `fan_guard_config.json` | Settings (auto-created/updated) |
| `fan_guard.log` | Activity log (auto-created) |

---

## ⚠ Important Notes

- Always run as **Administrator** — hardware access requires it
- The fan control attempts 3 methods: Acer WMI → PowerShell WMI → Registry
- If NitroSense updates, fan control may need reconfiguring (run `wmi_explorer.py`)
- FanGuard restores AUTO mode when you quit it cleanly
- Tested architecture: Acer Aspire 7 N19C5 series
