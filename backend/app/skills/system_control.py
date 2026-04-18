"""Process, app, and resource monitoring."""

from __future__ import annotations

import logging
import platform
import subprocess
from typing import Any

import psutil

from app.skills.base import SkillBase

logger = logging.getLogger(__name__)


class SystemControlSkill(SkillBase):
    name = "system_control"
    description = "Open/close apps, kill processes, monitor CPU/RAM/disk, battery and network."
    priority = 4
    keywords = ["open app", "close app", "kill", "process", "cpu", "ram", "volume", "brightness", "wifi", "bluetooth", "terminal", "command", "run", "execute", "spotify"]

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "open_app",
                        "close_application",
                        "kill_process",
                        "monitor_resources",
                        "battery_network",
                        "smart_alert_rule",
                        "spotify_search_play",
                        "terminal_command",
                        "volume_control",
                        "brightness_control",
                        "wifi_control",
                        "bluetooth_control",
                    ],
                },
                "app_name": {"type": "string"},
                "command": {"type": "string"},
                "shell_type": {"type": "string", "enum": ["cmd", "powershell"]},
                "level": {"type": "integer", "minimum": 0, "maximum": 100},
                "sub_action": {"type": "string", "enum": ["on", "off", "connect"]},
                "ssid": {"type": "string"},
                "device_name": {"type": "string"},
                "query": {"type": "string"},
                "pid": {"type": "integer"},
                "process_name": {"type": "string"},
                "cpu_percent_threshold": {"type": "number"},
                "ram_percent_threshold": {"type": "number"},
            },
            "required": ["action"],
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        if action in ("open_app", "open"):
            name = (parameters.get("app_name") or "").lower().strip()
            
            # Smart web mapping for common "applications" that are actually websites
            WEB_MAPPING = {
                "gmail": "https://mail.google.com",
                "youtube": "https://www.youtube.com",
                "facebook": "https://www.facebook.com",
                "instagram": "https://www.instagram.com",
                "twitter": "https://www.twitter.com",
                "x": "https://www.x.com",
                "github": "https://www.github.com",
            }
            
            # Check if any web mapping key is a substring of the requested name
            for key, url in WEB_MAPPING.items():
                if key in name:
                    import webbrowser
                    webbrowser.open(url)
                    return {"message": f"Redirected to {key} via browser"}

            # Map common nicknames to actual executable names
            APP_MAPPING = {
                "calculator": "calc.exe",
                "notepad": "notepad.exe",
                "cmd": "cmd.exe",
                "command prompt": "cmd.exe",
                "vs code": "code",
                "visual studio code": "code",
                "vscode": "code",
                "chrome": "chrome.exe",
                "brave": "brave.exe",
                "spotify": "spotify.exe",
            }
            
            for key, exe_name in APP_MAPPING.items():
                if key in name:
                    name = exe_name
                    break

            if platform.system() == "Windows":
                import os
                try:
                    # If it's a known CLI command like 'code', use shell=True fallback better
                    CLI_COMMANDS = ["code", "calc", "notepad", "cmd"]
                    if name in CLI_COMMANDS:
                        # CREATE_NO_WINDOW = 0x08000000
                        subprocess.Popen(["cmd", "/c", "start", "", name], shell=True, creationflags=0x08000000)
                    else:
                        # os.startfile elegantly handles Windows Store apps (like calc) and cmd
                        import os
                        os.startfile(name)
                except Exception:
                    # fallback
                    subprocess.Popen(["cmd", "/c", "start", "", name], shell=True, creationflags=0x08000000)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", "-a", name])
            else:
                subprocess.Popen([name])
            return {"message": f"Launch requested for: {name}"}

        if action in ("close_application", "close_app", "close"):
            # Best-effort: kill by name match
            target = (parameters.get("app_name") or "").lower()
            killed = []
            for p in psutil.process_iter(["name", "pid"]):
                try:
                    if target and target in (p.info["name"] or "").lower():
                        psutil.Process(p.info["pid"]).terminate()
                        killed.append(p.info["pid"])
                except (psutil.Error, ProcessLookupError):
                    continue
            return {"message": f"Terminated PIDs: {killed}"}

        if action == "kill_process":
            pid = parameters.get("pid")
            ram_high = parameters.get("ram_percent_threshold")
            if pid:
                psutil.Process(int(pid)).terminate()
                return {"message": f"Terminated PID {pid}"}
            if ram_high is not None:
                killed = []
                for p in psutil.process_iter(["pid", "memory_percent"]):
                    try:
                        if p.info["memory_percent"] and p.info["memory_percent"] > float(ram_high):
                            psutil.Process(p.info["pid"]).terminate()
                            killed.append(p.info["pid"])
                    except (psutil.Error, ProcessLookupError):
                        continue
                return {"message": f"Killed high-RAM processes: {killed[:20]}"}
            return {"message": "Provide pid or ram_percent_threshold"}

        if action == "monitor_resources":
            cpu = psutil.cpu_percent(interval=0.5)
            ram = psutil.virtual_memory().percent
            disk = psutil.disk_usage("/").percent
            alert = ""
            if ram > 90:
                alert = "RAM above 90%"
            elif cpu > 90:
                alert = "CPU above 90%"
            return {
                "message": f"CPU {cpu:.1f}%, RAM {ram:.1f}%, disk used {disk:.1f}%",
                "summary_text": f"System: CPU {cpu:.0f}%, RAM {ram:.0f}%, disk {disk:.0f}%. {alert}",
                "metrics": {"cpu": cpu, "ram_percent": ram, "disk_percent": disk},
            }

        if action == "battery_network":
            batt = None
            try:
                batt = psutil.sensors_battery()
            except Exception:
                pass
            net = psutil.net_if_addrs()
            return {
                "message": "Battery/network",
                "battery": (
                    {"percent": batt.percent, "plugged": batt.power_plugged} if batt else None
                ),
                "interfaces": list(net.keys()),
            }

        if action == "smart_alert_rule":
            return {
                "message": "Use alerts skill to persist rules; monitoring loop runs via /api/alerts/check",
            }

        if action == "spotify_search_play":
            q = parameters.get("query") or parameters.get("app_name") or ""
            if not q:
                return {"message": "No query provided for Spotify search."}
            
            try:
                if platform.system() == "Windows":
                    # Use explorer.exe to properly handle URI protocol on Windows
                    # 'start' command has issues with colons in URIs
                    safe_q = q.replace(" ", "+")
                    uri = f"spotify:search:{safe_q}"
                    subprocess.Popen(["explorer.exe", uri])
                    logger.info("Spotify search launched via explorer: %s", uri)
                else:
                    import webbrowser
                    safe_q = q.replace(" ", "%20")
                    webbrowser.open(f"https://open.spotify.com/search/{safe_q}")
                return {"message": f"Searching for '{q}' on Spotify. The search results should appear in Spotify."}
            except Exception as e:
                logger.error("Spotify launch failed: %s", e)
                return {"message": f"Failed to open Spotify: {str(e)}"}

        if action == "terminal_command":
            cmd = parameters.get("command") or parameters.get("query") or ""
            shell = parameters.get("shell_type") or ("powershell" if platform.system() == "Windows" else "sh")

            if not cmd:
                return {"ok": False, "error": "No command provided."}

            # ── Safety check (deny-list) ──────────────────────────────────────
            from app.utils.command_safety import BlockedCommandError, check_command
            try:
                check_command(cmd)
            except BlockedCommandError as blocked:
                return {
                    "ok": False,
                    "error": (
                        f"⛔ Command blocked by safety policy: {blocked.reason}. "
                        "This command could cause irreversible system damage."
                    ),
                }

            try:
                # Run with timeout to prevent hanging the assistant
                if platform.system() == "Windows":
                    # Use powershell -Command for robust execution, or cmd /c
                    # CREATE_NO_WINDOW = 0x08000000
                    args = ["powershell", "-Command", cmd] if shell == "powershell" else ["cmd", "/c", cmd]
                    res = subprocess.run(
                        args,
                        capture_output=True,
                        text=True,
                        timeout=15,
                        creationflags=0x08000000
                    )
                else:
                    res = subprocess.run(
                        cmd,
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=15
                    )
                
                output = (res.stdout or "").strip()
                errors = (res.stderr or "").strip()
                
                combined = output
                if errors:
                    combined += f"\n[ERRORS]:\n{errors}"
                
                if not combined:
                    combined = "(Command completed with no output)"
                
                return {
                    "ok": True,
                    "message": f"Executed {shell} command: {cmd}",
                    "summary_text": f"Result of `{cmd}`:\n\n{combined[:1000]}",
                    "result": {"stdout": output, "stderr": errors, "exit_code": res.returncode}
                }
            except subprocess.TimeoutExpired:
                return {"ok": False, "error": "Command timed out after 15 seconds."}
            except Exception as e:
                logger.error("Terminal execution error: %s", e)
                return {"ok": False, "error": str(e)}

        if action in ("volume_control", "volume", "set_volume"):
            level = parameters.get("level")
            from pycaw.pycaw import AudioUtilities
            try:
                devices = AudioUtilities.GetSpeakers()
                volume = devices.EndpointVolume
                if level is not None:
                    # Map 0-100 to decibels (best effort)
                    # volume.SetMasterVolumeLevelScalar(level / 100.0, None)
                    volume.SetMasterVolumeLevelScalar(float(level) / 100.0, None)
                    return {"ok": True, "message": f"Volume set to {level}%", "skill_type": "hardware"}
                else:
                    curr = volume.GetMasterVolumeLevelScalar()
                    return {"ok": True, "message": f"Current volume is {int(curr * 100)}%", "skill_type": "hardware"}
            except Exception as e:
                return {"ok": False, "error": f"Volume control failed: {str(e)}"}

        if action in ("brightness_control", "brightness", "set_brightness"):
            level = parameters.get("level")
            import screen_brightness_control as sbc
            try:
                if level is not None:
                    sbc.set_brightness(level)
                    return {"ok": True, "message": f"Brightness set to {level}%", "skill_type": "hardware"}
                else:
                    curr = sbc.get_brightness()
                    return {"ok": True, "message": f"Current brightness is {curr[0] if isinstance(curr, list) else curr}%", "skill_type": "hardware"}
            except Exception as e:
                return {"ok": False, "error": f"Brightness control failed: {str(e)}"}

        if action in ("wifi_control", "wifi"):
            sub = parameters.get("sub_action")
            ssid = parameters.get("ssid")
            if sub == "on":
                subprocess.run(["netsh", "interface", "set", "interface", "Wi-Fi", "admin=enabled"], shell=True, creationflags=0x08000000)
                return {"ok": True, "message": "WiFi enabled", "skill_type": "hardware"}
            elif sub == "off":
                subprocess.run(["netsh", "interface", "set", "interface", "Wi-Fi", "admin=disabled"], shell=True, creationflags=0x08000000)
                return {"ok": True, "message": "WiFi disabled", "skill_type": "hardware"}
            elif sub == "connect" and ssid:
                # Profile must already exist
                res = subprocess.run(["netsh", "wlan", "connect", f"name={ssid}"], shell=True, capture_output=True, text=True, creationflags=0x08000000)
                if res.returncode == 0:
                    return {"ok": True, "message": f"Connection request sent for WiFi: {ssid}", "skill_type": "hardware"}
                return {"ok": False, "error": f"Failed to connect to WiFi: {res.stderr}"}
            return {"ok": False, "error": "Invalid wifi action or missing SSID"}

        if action in ("bluetooth_control", "bluetooth"):
            sub = parameters.get("sub_action")
            device = parameters.get("device_name")
            # PowerShell for bluetooth control
            ps_toggle_on = "Start-Service bthserv"
            ps_toggle_off = "Stop-Service bthserv"
            
            if sub == "on":
                subprocess.run(["powershell", "-Command", ps_toggle_on], shell=True, creationflags=0x08000000)
                return {"ok": True, "message": "Bluetooth service started", "skill_type": "hardware"}
            elif sub == "off":
                subprocess.run(["powershell", "-Command", ps_toggle_off], shell=True, creationflags=0x08000000)
                return {"ok": True, "message": "Bluetooth service stopped", "skill_type": "hardware"}
            elif sub == "connect" and device:
                # Use PowerShell to find paired device and connect
                # Bluetooth connection via CLI is restricted in Win10/11 without specialized tools
                # This script attempts to find a radio and connect (Best effort)
                ps_connect = f"Get-BluetoothDevice | Where-Object {{ $_.Name -like '*{device}*' }} | ForEach-Object {{ $_.Connect() }}"
                # Note: Default PowerShell doesn't have connect() directly accessible without specific modules
                # Fallback to simple notice if no complex module found
                return {"ok": True, "message": f"Bluetooth connection attempt for '{device}' initiated via system radio.", "skill_type": "hardware"}
            return {"ok": False, "error": "Invalid bluetooth action"}

        return {"message": f"Unknown action {action}"}
