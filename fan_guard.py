"""
FanGuard - Acer Aspire 7 / Nitro Auto Fan Control
--------------------------------------------------
Monitors CPU/GPU temperature and automatically switches fan to MAX (CoolBoost)
when the temp exceeds your threshold, then back to AUTO when it cools down.

Temperature sources (tried in order):
  1. LibreHardwareMonitor Web Server (Enable 'Remote Web Server' in Options)
"""

import sys
import os
import time
import threading
import ctypes
import json
import logging
import subprocess
import struct
import winreg
from pathlib import Path

# ── dependency check & auto-install ──────────────────────────────────────────
MISSING = []
try:
    import wmi as _wmi_test
except ImportError:
    MISSING.append("wmi")
try:
    import pystray as _pt_test
except ImportError:
    MISSING.append("pystray")
try:
    from PIL import Image as _img_test
except ImportError:
    MISSING.append("pillow")

if MISSING:
    print(f"Installing: {', '.join(MISSING)} ...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet"] + MISSING)
    print("Packages installed. Restarting...")
    os.execv(sys.executable, [sys.executable] + sys.argv)

import wmi
import pystray
from PIL import Image, ImageDraw, ImageFont
import tkinter as tk
from tkinter import ttk, messagebox

# ── paths ─────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "fan_guard_config.json"
LOG_FILE    = BASE_DIR / "fan_guard.log"

DEFAULT_CONFIG = {
    "temp_threshold":  70,      # °C  → trigger max fan
    "check_interval":  3,       # seconds between checks
    "cooldown_temp":   60,      # °C  → return to auto
    "monitor_type":   "CPU",    # "CPU" | "GPU" | "BOTH"
}

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("FanGuard")


# ═════════════════════════════════════════════════════════════════════════════
#  Config
# ═════════════════════════════════════════════════════════════════════════════
def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception as e:
            log.warning(f"Config load error ({e}), using defaults.")
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


# ═════════════════════════════════════════════════════════════════════════════
#  Pipe query helpers
# ═════════════════════════════════════════════════════════════════════════════
_PIPE_NAMES = ["PredatorSense_service_namedpipe", "NitroSense_service_namedpipe"]


def _query_pipe_index(index: int):
    """Query a single hardware data index from the PredatorSense named pipe.
    Opens a fresh connection each call (the service closes after every reply).
    Returns the decoded integer value, or None on failure."""
    try:
        import win32file
        input_code = 1 | (index << 8)
        arg = struct.pack("<I", input_code)
        msg = bytearray()
        msg += struct.pack("<H", 13)        # cmd_code = query info
        msg += struct.pack("<B", 1)         # num args
        msg += struct.pack("<I", len(arg))  # arg length
        msg += arg
        for pipe_name in _PIPE_NAMES:
            try:
                handle = win32file.CreateFile(
                    rf"\\.\pipe\{pipe_name}",
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    0, None, win32file.OPEN_EXISTING, 0, None
                )
                win32file.WriteFile(handle, bytes(msg))
                win32file.FlushFileBuffers(handle)
                _, raw = win32file.ReadFile(handle, 13)
                win32file.CloseHandle(handle)
                raw_val = struct.unpack_from("<Q", raw, 5)[0]
                if (raw_val & 0xFF) == 0:
                    return (raw_val >> 8) & 0xFFFF
                return None
            except Exception:
                pass
    except ImportError:
        pass
    return None


# ═════════════════════════════════════════════════════════════════════════════
#  Temperature reading  (no LibreHardwareMonitor required)
# ═════════════════════════════════════════════════════════════════════════════
def _get_temps_pipe() -> dict:
    """Read CPU and GPU temps directly from the PredatorSense service pipe.
    Index 1 = CPU temperature (°C), Index 10 = GPU temperature (°C)."""
    result = {"CPU": None, "GPU": None}
    cpu_raw = _query_pipe_index(1)
    gpu_raw = _query_pipe_index(10)
    if cpu_raw is not None and cpu_raw > 0:
        result["CPU"] = float(cpu_raw)
    if gpu_raw is not None and gpu_raw > 0:
        result["GPU"] = float(gpu_raw)
    return result


def _get_temps_wmi_fallback() -> dict:
    """Fallback: read temps from OpenHardwareMonitor WMI if the pipe is unavailable."""
    result = {"CPU": None, "GPU": None}
    try:
        w = wmi.WMI(namespace="root\\OpenHardwareMonitor")
        for sensor in w.Sensor():
            if sensor.SensorType == "Temperature":
                name = sensor.Name.upper()
                val  = float(sensor.Value)
                if any(k in name for k in ("CPU", "CORE", "PACKAGE", "TDIE")):
                    if result["CPU"] is None or val > result["CPU"]:
                        result["CPU"] = val
                if any(k in name for k in ("GPU", "HOTSPOT")):
                    if result["GPU"] is None or val > result["GPU"]:
                        result["GPU"] = val
    except Exception as e:
        log.debug(f"WMI temp fallback: {e}")
    return result


def get_temps(monitor_type: str = "CPU") -> dict:
    """Returns {'CPU': float|None, 'GPU': float|None}.
    Reads directly from the PredatorSense service pipe — no external software needed.
    Falls back to OpenHardwareMonitor WMI if the pipe is unavailable."""
    result = _get_temps_pipe()
    if result["CPU"] is None and result["GPU"] is None:
        result = _get_temps_wmi_fallback()
    return result


# ═════════════════════════════════════════════════════════════════════════════
#  Fan RPM reading
# ═════════════════════════════════════════════════════════════════════════════
def get_rpms() -> dict:
    """Read CPU and GPU fan RPMs from the PredatorSense named pipe.
    Index 2 = CPU fan RPM, Index 6 = GPU fan RPM (Acer Aspire/Nitro)."""
    return {
        "CPU": _query_pipe_index(2),
        "GPU": _query_pipe_index(6),
    }




# ═════════════════════════════════════════════════════════════════════════════
#  Fan control
# ═════════════════════════════════════════════════════════════════════════════
FAN_AUTO = 0
FAN_MAX  = 1

# ── Method 1: AcerBiosConfigurationTool WMI ──────────────────────────────────
def _fan_via_acer_bios_wmi(mode: int) -> bool:
    try:
        w = wmi.WMI(namespace="root\\WMI")
        instances = w.AcerBiosConfigurationTool()
        if not instances:
            return False
        inst = instances[0]
        data_auto = [0x00, 0x01, 0x00]
        data_max  = [0x01, 0x01, 0x00]
        data = data_max if mode == FAN_MAX else data_auto
        data_bytes = (ctypes.c_ubyte * len(data))(*data)
        result = inst.SetBiosOptions(Data=list(data_bytes), Password="", PasswordLen=0)
        log.debug(f"AcerBiosConfigurationTool result: {result}")
        return True
    except Exception as e:
        log.debug(f"AcerBiosConfigurationTool: {e}")
        return False


# ── Method 2: ACERWMI_GamingFanControlObject ──────────────────────────────────
def _fan_via_gaming_wmi(mode: int) -> bool:
    try:
        w = wmi.WMI(namespace="root\\WMI")
        for cls_name in ("ACERWMI_GamingFanControlObject", "Acer_GamingFanSpeed"):
            try:
                for inst in getattr(w, cls_name)():
                    for meth in ("SetGamingFanSpeed", "SetGamingFanBehavior"):
                        try:
                            getattr(inst, meth)(mode)
                            log.debug(f"{cls_name}.{meth}({mode})")
                            return True
                        except Exception:
                            pass
            except AttributeError:
                pass
    except Exception as e:
        log.debug(f"Gaming WMI: {e}")
    return False


# ── Helper: write to NitroSense registry with the correct 64-bit flag ─────────
def _nitrosense_reg_write(**values):
    """Write DWORD values to HKLM\\SOFTWARE\\OEM\\NitroSense\\FanControl.
    KEY_WOW64_64KEY is required — without it the 32-bit view is addressed and
    the PredatorSense service (64-bit) never sees the changes."""
    try:
        KEY_FLAGS = winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY
        key = winreg.CreateKeyEx(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\OEM\NitroSense\FanControl",
            0, KEY_FLAGS
        )
        for name, val in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, val)
        winreg.CloseKey(key)
        log.debug(f"Registry write OK: {values}")
        return True
    except Exception as e:
        log.debug(f"Registry write failed: {e}")
        return False


# ── Method 3: IPC Named Pipe ──────────────────────────────────────────────────
def _fan_via_ipc(mode: int) -> bool:
    """Send fan speed to PredatorSense/NitroSense service via named pipe.
    Uses exact NitroSensual packet format:
        struct.pack('<HBIQ', 16, 1, 8, (percent << 8) | fan_group_type)
    CPU = group 1, GPU = group 4.
    Each command needs its own pipe connection."""
    try:
        import win32file

        percent = 100 if mode == FAN_MAX else 0
        success = False

        for pipe_name in ["PredatorSense_service_namedpipe", "NitroSense_service_namedpipe"]:
            try:
                for fan_group_type in [1, 4]:   # 1 = CPU, 4 = GPU
                    data   = (percent << 8) | fan_group_type
                    packet = struct.pack("<HBIQ", 16, 1, 8, data)
                    handle = win32file.CreateFile(
                        rf"\\.\pipe\{pipe_name}",
                        win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                        0, None, win32file.OPEN_EXISTING, 0, None
                    )
                    win32file.WriteFile(handle, packet)
                    win32file.ReadFile(handle, 9)
                    win32file.CloseHandle(handle)

                log.debug(f"IPC OK via {pipe_name} (CPU+GPU {percent}%)")
                success = True
                break
            except Exception as e:
                log.debug(f"IPC {pipe_name}: {e}")

        return success
    except ImportError:
        log.warning("win32file not found — IPC method skipped.")
        return False


# ── Method 4: plain registry fallback ────────────────────────────────────────
def _fan_via_registry_fallback(mode: int) -> bool:
    written = False
    for path in (
        r"SOFTWARE\OEM\NitroSense\FanControl",
        r"SOFTWARE\Acer\NitroSense\FanControl",
        r"SOFTWARE\Acer\PredatorSense\FanControl",
    ):
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                key = winreg.OpenKey(hive, path, 0, winreg.KEY_SET_VALUE)
                for val_name in ("CurrentFanMode", "FanMode", "CoolBoost"):
                    try:
                        winreg.SetValueEx(key, val_name, 0, winreg.REG_DWORD, mode)
                        written = True
                    except Exception:
                        pass
                winreg.CloseKey(key)
            except Exception:
                pass
    return written


# ── Unified fan setter ────────────────────────────────────────────────────────
def set_fan(mode: int) -> bool:
    mode_str = "MAX" if mode == FAN_MAX else "AUTO"
    log.info(f"Fan → {mode_str}")

    if mode == FAN_MAX:
        # 1) Write registry to official MAX mode (CurrentFanMode=1)
        _nitrosense_reg_write(
            CurrentFanMode=1,       # 1 = Max
            CPUFanCustomAuto=0,     # 0 = manual
            GPU1FanCustomAuto=0,    # 0 = manual
            CPUFanPercentage=0,
            GPU1FanPercentage=0,
        )
    else:
        # 1) Write registry to official AUTO mode (CurrentFanMode=0)
        _nitrosense_reg_write(
            CurrentFanMode=0,       # 0 = Auto
            CPUFanCustomAuto=1,     # 1 = Auto
            GPU1FanCustomAuto=1,    # 1 = Auto
            CPUFanPercentage=0,
            GPU1FanPercentage=0,
        )

    # 2) Try WMI methods (usually fail silently on newer firmware, harmless)
    _fan_via_acer_bios_wmi(mode)
    _fan_via_gaming_wmi(mode)

    # 3) IPC Named Pipe — trigger the service to reload registry values
    if _fan_via_ipc(mode):
        log.info(f"Fan {mode_str} via IPC.")
        return True

    # 4) Plain registry fallback
    if _fan_via_registry_fallback(mode):
        log.info(f"Fan {mode_str} via registry fallback.")
        return True

    log.warning("Fan control: no method succeeded. Ensure NitroSense service is running.")
    return False


# ═════════════════════════════════════════════════════════════════════════════
#  GUI Application
# ═════════════════════════════════════════════════════════════════════════════
class FanGuardGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.fan_boosted = False
        self.manual_override = False
        self.cpu_temp = None
        self.gpu_temp = None
        self.cpu_rpm  = None
        self.gpu_rpm  = None
        self.running = True
        self._lock = threading.Lock()

        self.title("FanGuard - Acer Fan Control")
        self.geometry("340x460")
        self.resizable(False, False)
        self.configure(padx=20, pady=20)
        
        # Intercept close event to minimize to tray
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # ── UI Elements ──
        
        # Status Frame
        status_frame = ttk.LabelFrame(self, text=" Live Status ", padding=10)
        status_frame.pack(fill="x", pady=(0, 15))

        self.lbl_cpu = ttk.Label(status_frame, text="CPU: -- °C  |  -- RPM", font=("Segoe UI", 12))
        self.lbl_cpu.pack(anchor="w", pady=2)

        self.lbl_gpu = ttk.Label(status_frame, text="GPU: -- °C  |  -- RPM", font=("Segoe UI", 12))
        self.lbl_gpu.pack(anchor="w", pady=2)

        self.lbl_fan = ttk.Label(status_frame, text="Fan Mode: AUTO", font=("Segoe UI", 12, "bold"), foreground="green")
        self.lbl_fan.pack(anchor="w", pady=6)

        # Settings Frame
        settings_frame = ttk.LabelFrame(self, text=" Settings ", padding=10)
        settings_frame.pack(fill="x", pady=(0, 15))

        ttk.Label(settings_frame, text="Boost Fan when temp hits (°C):").pack(anchor="w")
        threshold_frame = ttk.Frame(settings_frame)
        threshold_frame.pack(fill="x", pady=(0, 10))
        self.var_threshold = tk.IntVar(value=self.threshold)
        ttk.Scale(threshold_frame, from_=40, to_=95, variable=self.var_threshold,
                  command=self.update_threshold_label).pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.lbl_thresh_val = ttk.Label(threshold_frame, text=f"{self.threshold}°C", width=4)
        self.lbl_thresh_val.pack(side="right")

        ttk.Label(settings_frame, text="Return to AUTO when temp drops below (°C):").pack(anchor="w")
        cooldown_frame = ttk.Frame(settings_frame)
        cooldown_frame.pack(fill="x")
        self.var_cooldown = tk.IntVar(value=self.cooldown)
        ttk.Scale(cooldown_frame, from_=35, to_=90, variable=self.var_cooldown,
                  command=self.update_cooldown_label).pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.lbl_cool_val = ttk.Label(cooldown_frame, text=f"{self.cooldown}°C", width=4)
        self.lbl_cool_val.pack(side="right")

        # Manual Control Frame
        manual_frame = ttk.LabelFrame(self, text=" Manual Control ", padding=10)
        manual_frame.pack(fill="x")
        btn_frame = ttk.Frame(manual_frame)
        btn_frame.pack(fill="x")
        ttk.Button(btn_frame, text="Force AUTO", command=self.force_auto).pack(side="left", expand=True, fill="x", padx=(0, 5))
        ttk.Button(btn_frame, text="Force MAX",  command=self.force_max).pack(side="right", expand=True, fill="x", padx=(5, 0))

        # Setup and start System Tray Icon
        self.tray_icon = None
        self.setup_tray_icon()

        threading.Thread(target=self.monitor_loop, daemon=True).start()

    # ── Config Properties ──
    @property
    def threshold(self):
        return self.cfg.get("temp_threshold", 70)

    @property
    def cooldown(self):
        return self.cfg.get("cooldown_temp", 60)

    @property
    def interval(self):
        return self.cfg.get("check_interval", 3)

    @property
    def monitor_type(self):
        return self.cfg.get("monitor_type", "CPU")

    def relevant_temp(self) -> float | None:
        vals = []
        if self.monitor_type in ("CPU", "BOTH") and self.cpu_temp is not None:
            vals.append(self.cpu_temp)
        if self.monitor_type in ("GPU", "BOTH") and self.gpu_temp is not None:
            vals.append(self.gpu_temp)
        return max(vals) if vals else None

    # ── System Tray Integration ──
    def create_tray_image(self) -> Image.Image:
        """Create a dynamic 64x64 icon showing the current highest temperature."""
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Circle color: red if boosted, green if auto
        color = (220, 50, 35, 255) if self.fan_boosted else (20, 150, 110, 255)
        draw.ellipse([4, 4, 60, 60], fill=color)

        t = self.relevant_temp()
        t_str = f"{int(t)}°" if t is not None else "?°"
        try:
            font = ImageFont.truetype("arial.ttf", 26)
        except Exception:
            font = ImageFont.load_default()

        # Center text inside the circle
        bb = draw.textbbox((0, 0), t_str, font=font)
        w, h = bb[2] - bb[0], bb[3] - bb[1]
        draw.text(((64 - w) / 2, (64 - h) / 2 - 2), t_str, fill="white", font=font)
        return img

    def setup_tray_icon(self):
        try:
            self.tray_icon = pystray.Icon(
                "FanGuard",
                self.create_tray_image(),
                "FanGuard — Monitoring Active",
                menu=pystray.Menu(
                    pystray.MenuItem("Open Settings", self.restore_gui, default=True),
                    pystray.MenuItem("Quit FanGuard", self.quit_app)
                )
            )
            # Run the tray icon loop in a daemon thread
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
            log.info("System Tray icon initialized.")
        except Exception as e:
            log.warning(f"Could not setup System Tray icon: {e}")

    def restore_gui(self, icon=None, item=None):
        self.after(0, self.deiconify)

    def quit_app(self, icon=None, item=None):
        log.info("Quit requested via System Tray. Restoring fan to AUTO.")
        self.running = False
        if self.tray_icon:
            self.tray_icon.stop()
        set_fan(FAN_AUTO)
        self.after(0, self.destroy)

    # ── UI Callbacks ──
    def update_threshold_label(self, event=None):
        val = int(self.var_threshold.get())
        self.lbl_thresh_val.config(text=f"{val}°C")
        if val != self.threshold:
            self.cfg["temp_threshold"] = val
            save_config(self.cfg)

    def update_cooldown_label(self, event=None):
        val = int(self.var_cooldown.get())
        self.lbl_cool_val.config(text=f"{val}°C")
        if val != self.cooldown:
            self.cfg["cooldown_temp"] = val
            save_config(self.cfg)

    def force_auto(self):
        self.manual_override = False
        set_fan(FAN_AUTO)
        self.fan_boosted = False
        self.update_ui_state()

    def force_max(self):
        self.manual_override = True
        set_fan(FAN_MAX)
        self.fan_boosted = True
        self.update_ui_state()

    # ── Background Monitor ──
    def monitor_loop(self):
        log.info(f"Monitoring started | threshold={self.threshold}°C cooldown={self.cooldown}°C")
        lhm_warned = False

        while self.running:
            try:
                temps = get_temps(self.monitor_type)
                rpms  = get_rpms()
                with self._lock:
                    self.cpu_temp = temps["CPU"]
                    self.gpu_temp = temps["GPU"]
                    self.cpu_rpm  = rpms["CPU"]
                    self.gpu_rpm  = rpms["GPU"]

                if self.cpu_temp is None and self.gpu_temp is None and not lhm_warned:
                    log.warning("No temperature data — enable LHM Remote Web Server.")
                    lhm_warned = True
                elif self.cpu_temp is not None or self.gpu_temp is not None:
                    lhm_warned = False

                # Only auto-control if not manually overridden by user clicking 'Force MAX/AUTO'
                if not self.manual_override:
                    t = self.relevant_temp()
                    if t is not None:
                        if not self.fan_boosted and t >= self.threshold:
                            log.info(f"Temp {t:.1f}°C >= {self.threshold}°C -> BOOST FAN")
                            set_fan(FAN_MAX)
                            self.fan_boosted = True
                        elif self.fan_boosted and t <= self.cooldown:
                            log.info(f"Temp {t:.1f}°C <= {self.cooldown}°C -> RESTORE AUTO")
                            set_fan(FAN_AUTO)
                            self.fan_boosted = False

                self.after(0, self.update_ui_state)

            except Exception as e:
                log.error(f"Monitor error: {e}")

            time.sleep(self.interval)

    def update_ui_state(self):
        with self._lock:
            cpu_t = f"{self.cpu_temp:.1f}" if self.cpu_temp is not None else "--"
            gpu_t = f"{self.gpu_temp:.1f}" if self.gpu_temp is not None else "--"
            cpu_r = f"{self.cpu_rpm}"      if self.cpu_rpm  is not None else "--"
            gpu_r = f"{self.gpu_rpm}"      if self.gpu_rpm  is not None else "--"
            self.lbl_cpu.config(text=f"CPU: {cpu_t} °C  |  {cpu_r} RPM")
            self.lbl_gpu.config(text=f"GPU: {gpu_t} °C  |  {gpu_r} RPM")

        if self.fan_boosted:
            self.lbl_fan.config(text="Fan Mode: MAX", foreground="red")
        else:
            self.lbl_fan.config(text="Fan Mode: AUTO", foreground="green")

        # Update System Tray Icon image dynamically to display current temp
        if self.tray_icon:
            self.tray_icon.icon = self.create_tray_image()

    def on_closing(self):
        # Hide the main window instead of terminating, making it run completely in background
        log.info("Settings window closed. FanGuard is running in System Tray.")
        self.withdraw()


# ═════════════════════════════════════════════════════════════════════════════
#  Entry
# ═════════════════════════════════════════════════════════════════════════════
def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def register_startup():
    """Register FanGuard in Task Scheduler to auto-launch on login with admin rights."""
    try:
        task_name  = "FanGuard_AutoStart"
        script_path = str(Path(__file__).resolve())
        python_exe  = sys.executable
        cmd = [
            "schtasks", "/create",
            "/tn", task_name,
            "/tr", f'"{python_exe}" "{script_path}"',
            "/sc", "ONLOGON",
            "/rl", "HIGHEST",
            "/f",
            "/delay", "0001:00",  # 1-minute delay so PSSvc loads first
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            log.info("Startup task registered — FanGuard will auto-launch on next login.")
        else:
            log.warning(f"Startup task registration failed: {result.stderr.strip()}")
    except Exception as e:
        log.warning(f"Could not register startup task: {e}")


def main():
    if not _is_admin():
        log.warning("Not Administrator — requesting elevation...")
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas",
            sys.executable,
            " ".join(f'"{a}"' for a in sys.argv),
            None, 1,
        )
        sys.exit(0)

    log.info("=" * 60)
    log.info("  FanGuard GUI Started")
    log.info("=" * 60)

    register_startup()

    app = FanGuardGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
