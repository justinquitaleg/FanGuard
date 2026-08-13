"""
wmi_explorer.py  –  Acer WMI namespace explorer
================================================
Run this FIRST (as Administrator) to discover which WMI classes and methods
are available on YOUR specific laptop model.

This will print every class in root\\WMI and root\\LibreHardwareMonitor
so you can verify that FanGuard can see your hardware.

Usage:
    python wmi_explorer.py
"""

import sys

try:
    import wmi
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "wmi"])
    import wmi

import ctypes

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def explore_namespace(namespace: str):
    print(f"\n{'='*60}")
    print(f"  Namespace: {namespace}")
    print(f"{'='*60}")
    try:
        w = wmi.WMI(namespace=namespace)
        classes = w.classes
        if not classes:
            print("  (no classes found)")
            return
        for cls_name in sorted(classes):
            print(f"  CLASS: {cls_name}")
            try:
                cls = getattr(w, cls_name)
                instances = cls()
                for inst in instances:
                    # Print methods
                    methods = [m for m in dir(inst) if not m.startswith("_")]
                    if methods:
                        print(f"    Methods/props: {', '.join(methods[:20])}")
                    break  # just show first instance
            except Exception as e:
                print(f"    (could not inspect: {e})")
    except Exception as e:
        print(f"  Error: {e}")

def check_lhm_temps():
    print(f"\n{'='*60}")
    print("  Temperature sensors (LibreHardwareMonitor)")
    print(f"{'='*60}")
    try:
        w = wmi.WMI(namespace="root\\LibreHardwareMonitor")
        sensors = w.query("SELECT Name, Value, SensorType FROM Sensor WHERE SensorType = 'Temperature'")
        if not sensors:
            print("  No temperature sensors found.")
            print("  → Is LibreHardwareMonitor running? Did you enable Options > Enable WMI?")
        for s in sensors:
            print(f"  {s.Name:<40} {s.Value:.1f}°C")
    except Exception as e:
        print(f"  Error: {e}")
        print("  -> LibreHardwareMonitor may not be running or WMI is not enabled.")

def main():
    # Fix Windows console encoding
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    print("FanGuard WMI Explorer")
    print("=====================")
    if not is_admin():
        print("WARNING: Not running as Administrator. Some results may be incomplete.")

    # Check temperatures
    check_lhm_temps()

    # Explore Acer-related WMI namespaces
    explore_namespace("root\\WMI")

    print("\n\nDone. Share this output if you need help configuring FanGuard.")
    input("\nPress Enter to exit...")

if __name__ == "__main__":
    main()
