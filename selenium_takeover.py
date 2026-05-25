import datetime as dt
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk

from selenium import webdriver
from selenium.common.exceptions import JavascriptException, WebDriverException
from selenium.webdriver.edge.options import Options


ROOT = Path(__file__).resolve().parent
LOG_PATH = ROOT / "appointment_notifier.log"
START_URL = "https://www.prenotazionicie.interno.gov.it/cittadino/a/sc/wizardAppuntamentoCittadino/sceltaSede"
DEFAULT_DEBUG_PORT = 9333
DEFAULT_CHECK_INTERVAL_SECONDS = 60
DEFAULT_PROFILE_DIR = ROOT / "edge-profile-selenium"
DEFAULT_EDGE_PATHS = (
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)
TARGET_PATH_FRAGMENT = "/wizardAppuntamentoCittadino/sceltaSede"


@dataclass(frozen=True)
class RuntimeConfig:
    start_url: str = START_URL
    debug_port: int = DEFAULT_DEBUG_PORT
    check_interval_seconds: int = DEFAULT_CHECK_INTERVAL_SECONDS
    profile_dir: Path = DEFAULT_PROFILE_DIR
    edge_exe: Path | None = None

    @classmethod
    def load(cls):
        edge_path = os.environ.get("AGENDA_CIE_EDGE_PATH", "").strip()
        port_value = os.environ.get("AGENDA_CIE_DEBUG_PORT", "").strip()
        interval_value = os.environ.get("AGENDA_CIE_CHECK_INTERVAL_SECONDS", "").strip()

        return cls(
            debug_port=parse_int_env(port_value, DEFAULT_DEBUG_PORT, "AGENDA_CIE_DEBUG_PORT"),
            check_interval_seconds=parse_int_env(
                interval_value,
                DEFAULT_CHECK_INTERVAL_SECONDS,
                "AGENDA_CIE_CHECK_INTERVAL_SECONDS",
            ),
            profile_dir=Path(os.environ.get("AGENDA_CIE_PROFILE_DIR", DEFAULT_PROFILE_DIR)),
            edge_exe=Path(edge_path) if edge_path else discover_edge_executable(),
        )


def parse_int_env(value, default, name):
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc
    if parsed <= 0:
        raise RuntimeError(f"{name} must be greater than zero.")
    return parsed


def discover_edge_executable():
    edge_from_path = shutil.which("msedge")
    if edge_from_path:
        return Path(edge_from_path)
    for candidate in DEFAULT_EDGE_PATHS:
        if candidate.exists():
            return candidate
    return None


def log(message):
    line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {message}"
    print(line, flush=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return line


def desktop_flash(title, message):
    ps_message = message.replace("'", "''")
    subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-WindowStyle",
            "Normal",
            "-Command",
            (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "Add-Type -AssemblyName System.Drawing;"
                "for ($i = 0; $i -lt 4; $i++) { [console]::beep(1200,250); Start-Sleep -Milliseconds 120 };"
                "$flash = New-Object System.Windows.Forms.Form;"
                "$flash.FormBorderStyle = 'None';"
                "$flash.BackColor = [System.Drawing.Color]::Yellow;"
                "$flash.Opacity = 0.45;"
                "$flash.TopMost = $true;"
                "$flash.WindowState = 'Maximized';"
                "$flash.ShowInTaskbar = $false;"
                "$flash.Show();"
                "Start-Sleep -Milliseconds 650;"
                "$flash.Close();"
                "$form = New-Object System.Windows.Forms.Form;"
                "$form.Text = 'Carta identita appointment found';"
                "$form.Size = New-Object System.Drawing.Size(680,320);"
                "$form.StartPosition = 'CenterScreen';"
                "$form.TopMost = $true;"
                "$form.BackColor = [System.Drawing.Color]::White;"
                "$label = New-Object System.Windows.Forms.Label;"
                "$label.Text = @'"
                f"{ps_message}"
                "'@;"
                "$label.Font = New-Object System.Drawing.Font('Segoe UI',14,[System.Drawing.FontStyle]::Bold);"
                "$label.AutoSize = $false;"
                "$label.TextAlign = 'MiddleCenter';"
                "$label.Dock = 'Fill';"
                "$button = New-Object System.Windows.Forms.Button;"
                "$button.Text = 'OK';"
                "$button.Dock = 'Bottom';"
                "$button.Height = 46;"
                "$button.Add_Click({ $form.Close() });"
                "$form.Controls.Add($label);"
                "$form.Controls.Add($button);"
                "$form.Activate();"
                "$form.ShowDialog() | Out-Null;"
            ),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def parse_user_date(value):
    value = value.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError("Use DD/MM/YYYY or YYYY-MM-DD.")


def parse_italian_date(text):
    match = re.search(r"(\d{2})/(\d{2})/(\d{4})", text)
    if not match:
        return None
    day, month, year = map(int, match.groups())
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def is_debug_port_ready(debug_port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{debug_port}/json/version", timeout=2) as response:
            json.loads(response.read().decode("utf-8"))
        return True
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return False


class EdgeSession:
    def __init__(self, config):
        self.config = config
        self.driver = None

    def ensure_debug_browser(self):
        if is_debug_port_ready(self.config.debug_port):
            return
        if not self.config.edge_exe:
            raise RuntimeError(
                "Microsoft Edge was not found automatically. "
                "Set AGENDA_CIE_EDGE_PATH to the full msedge.exe path."
            )

        self.config.profile_dir.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(
            [
                str(self.config.edge_exe),
                f"--remote-debugging-port={self.config.debug_port}",
                f"--user-data-dir={self.config.profile_dir}",
                "--no-first-run",
                "--start-maximized",
                self.config.start_url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(30):
            if is_debug_port_ready(self.config.debug_port):
                return
            time.sleep(1)
        raise RuntimeError("Edge did not open the remote debugging port.")

    def connect(self):
        self.ensure_debug_browser()
        options = Options()
        options.debugger_address = f"127.0.0.1:{self.config.debug_port}"
        driver = webdriver.Edge(options=options)
        if "prenotazionicie.interno.gov.it" not in driver.current_url:
            driver.get(self.config.start_url)
        self.driver = driver
        return driver

    def close(self):
        if not self.driver:
            return
        try:
            self.driver.quit()
        except WebDriverException as exc:
            log(f"Driver shutdown failed: {exc}")
        finally:
            self.driver = None


def build_driver(session):
    return session.connect()


SCRAPE_SCRIPT = r"""
const done = arguments[arguments.length - 1];

function text(el) {
  return (el?.innerText || el?.textContent || "").replace(/\s+/g, " ").trim();
}

async function wait(ms) {
  await new Promise(resolve => setTimeout(resolve, ms));
}

async function scanActiveTable(scope) {
  const rows = Array.from(document.querySelectorAll(".tab-pane.active table tbody tr, table tbody tr"));
  return rows.map(row => {
    const cells = Array.from(row.querySelectorAll("th, td")).map(text);
    const radio = row.querySelector('input[type="radio"]');
    const locked = Boolean(row.querySelector(".fa-lock, .it-lock"));
    return {
      scope,
      cells,
      selectable: Boolean(radio) && !locked,
      checked: Boolean(radio && radio.checked)
    };
  });
}

(async () => {
  if (!location.href.includes("/wizardAppuntamentoCittadino/sceltaSede")) {
    done({
      ok: false,
      reason: "Waiting for the Scegli la sede page. Complete login/details manually first.",
      url: location.href,
      rows: []
    });
    return;
  }

  const result = [];
  result.push(...await scanActiveTable("Comune di Roma"));

  const nearbyTab = Array.from(document.querySelectorAll("a, button"))
    .find(el => text(el).toLowerCase().includes("comuni vicini"));
  if (nearbyTab) {
    nearbyTab.click();
    await wait(2500);
    result.push(...await scanActiveTable("Comuni vicini a Roma"));
  }

  done({ ok: true, url: location.href, rows: result });
})().catch(error => done({ ok: false, reason: error.message, rows: [] }));
"""


def scan_page(driver):
    driver.set_script_timeout(30)
    return driver.execute_async_script(SCRAPE_SCRIPT)


def matching_rows(scan, start_date, end_date):
    matches = []
    for row in scan.get("rows", []):
        joined = " | ".join(row.get("cells", []))
        date_value = parse_italian_date(joined)
        if date_value and start_date <= date_value <= end_date and row.get("selectable"):
            matches.append(
                {
                    "date": date_value,
                    "scope": row.get("scope", ""),
                    "details": joined,
                }
            )
    matches.sort(key=lambda item: item["date"])
    return matches


class WatcherWorker:
    def __init__(self, start_date, end_date, events, config):
        self.start_date = start_date
        self.end_date = end_date
        self.events = events
        self.config = config
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.session = EdgeSession(config)
        self.seen = set()

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def emit(self, kind, message, payload=None):
        self.events.put((kind, message, payload))

    def run(self):
        self.emit("status", "Starting Edge. Log in manually, enter details, then stop on Scegli la sede.")
        try:
            driver = build_driver(self.session)
        except Exception as exc:
            self.emit("error", f"Could not start Edge/Selenium: {exc}")
            return

        try:
            while not self.stop_event.is_set():
                try:
                    scan = scan_page(driver)
                except JavascriptException as exc:
                    self.emit("log", f"Could not scan page: {exc}")
                    scan = {"ok": False, "reason": str(exc), "rows": []}
                except WebDriverException as exc:
                    self.emit("error", f"Browser session failed: {exc}")
                    break

                if not scan.get("ok"):
                    self.emit("status", scan.get("reason", "Waiting for Scegli la sede page."))
                else:
                    matches = matching_rows(scan, self.start_date, self.end_date)
                    if not matches:
                        self.emit("log", "Scanned table: no selectable date in selected range.")
                    for match in matches:
                        key = f"{match['date'].isoformat()}|{match['details']}"
                        if key in self.seen:
                            continue
                        self.seen.add(key)
                        message = (
                            f"Selectable appointment: {match['date']:%d/%m/%Y}\n"
                            f"{match['scope']}\n{match['details']}"
                        )
                        log(f"NOTIFICATION: {message.replace(chr(10), ' | ')}")
                        desktop_flash("Carta identita appointment found", message)
                        self.emit("match", message, match)

                if self.stop_event.wait(self.config.check_interval_seconds):
                    break
                try:
                    if TARGET_PATH_FRAGMENT in driver.current_url:
                        driver.refresh()
                        time.sleep(5)
                except WebDriverException as exc:
                    self.emit("error", f"Refresh failed: {exc}")
                    break
        finally:
            self.session.close()
            self.emit("status", "Stopped.")


class AppointmentWatcherGui:
    def __init__(self, root):
        self.config = RuntimeConfig.load()
        self.root = root
        self.root.title("Agenda CIE Appointment Watcher")
        self.root.geometry("760x520")
        self.root.minsize(680, 460)

        self.events = queue.Queue()
        self.worker = None

        today = dt.date.today()
        default_end = today + dt.timedelta(days=21)

        self.start_var = tk.StringVar(value=today.strftime("%d/%m/%Y"))
        self.end_var = tk.StringVar(value=default_end.strftime("%d/%m/%Y"))
        self.status_var = tk.StringVar(value="Choose a date range, then start the watcher.")

        self.build_ui()
        self.root.after(200, self.process_events)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def build_ui(self):
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)

        title = ttk.Label(outer, text="Agenda CIE Appointment Watcher", font=("Segoe UI", 16, "bold"))
        title.pack(anchor="w")

        subtitle = ttk.Label(
            outer,
            text="Log in and enter details manually. The app watches the Scegli la sede table.",
            foreground="#555555",
        )
        subtitle.pack(anchor="w", pady=(2, 14))

        controls = ttk.Frame(outer)
        controls.pack(fill="x")

        ttk.Label(controls, text="From").grid(row=0, column=0, sticky="w")
        ttk.Entry(controls, textvariable=self.start_var, width=16).grid(row=1, column=0, sticky="w", padx=(0, 14))

        ttk.Label(controls, text="To").grid(row=0, column=1, sticky="w")
        ttk.Entry(controls, textvariable=self.end_var, width=16).grid(row=1, column=1, sticky="w", padx=(0, 18))

        self.start_button = ttk.Button(controls, text="Start Watcher", command=self.start_watcher)
        self.start_button.grid(row=1, column=2, padx=(0, 8))

        self.stop_button = ttk.Button(controls, text="Stop", command=self.stop_watcher, state="disabled")
        self.stop_button.grid(row=1, column=3)

        ttk.Label(outer, textvariable=self.status_var, foreground="#0b5cad").pack(anchor="w", pady=(16, 8))

        self.alert_frame = tk.Frame(outer, bg="#fff3cd", highlightthickness=1, highlightbackground="#f0c36d")
        self.alert_text = tk.Label(
            self.alert_frame,
            text="No appointment found yet.",
            bg="#fff3cd",
            fg="#5c4400",
            justify="left",
            anchor="w",
            font=("Segoe UI", 11, "bold"),
            wraplength=680,
            padx=12,
            pady=10,
        )
        self.alert_text.pack(fill="x")
        self.alert_frame.pack(fill="x", pady=(0, 12))

        ttk.Label(outer, text="Activity").pack(anchor="w")
        self.log_box = tk.Text(outer, height=13, wrap="word", state="disabled")
        self.log_box.pack(fill="both", expand=True, pady=(4, 0))

    def add_log(self, message):
        line = log(message)
        self.log_box.configure(state="normal")
        self.log_box.insert("end", line + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def start_watcher(self):
        if self.worker and self.worker.thread.is_alive():
            messagebox.showinfo("Watcher running", "The watcher is already running.")
            return
        try:
            start_date = parse_user_date(self.start_var.get())
            end_date = parse_user_date(self.end_var.get())
        except ValueError as exc:
            messagebox.showerror("Invalid date", str(exc))
            return
        if start_date > end_date:
            messagebox.showerror("Invalid range", "The start date must be before or equal to the end date.")
            return

        self.alert_text.configure(text="No appointment found yet.", bg="#fff3cd", fg="#5c4400")
        self.alert_frame.configure(bg="#fff3cd", highlightbackground="#f0c36d")
        self.worker = WatcherWorker(start_date, end_date, self.events, self.config)
        self.worker.start()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status_var.set(f"Watching for selectable appointments from {start_date:%d/%m/%Y} to {end_date:%d/%m/%Y}.")
        self.add_log("Watcher started.")

    def stop_watcher(self):
        if self.worker:
            self.worker.stop()
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.add_log("Stop requested.")

    def process_events(self):
        while True:
            try:
                kind, message, payload = self.events.get_nowait()
            except queue.Empty:
                break

            if kind == "status":
                self.status_var.set(message)
                self.add_log(message)
            elif kind == "log":
                self.add_log(message)
            elif kind == "error":
                self.status_var.set(message)
                self.add_log(message)
                self.start_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
                self.worker = None
            elif kind == "match":
                self.status_var.set("Appointment found.")
                self.alert_text.configure(text=message, bg="#d1e7dd", fg="#0f5132")
                self.alert_frame.configure(bg="#d1e7dd", highlightbackground="#75b798")
                self.add_log(message)
                continue

            if kind == "status" and message == "Stopped.":
                self.start_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
                self.worker = None

        self.root.after(200, self.process_events)

    def on_close(self):
        if self.worker:
            self.worker.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    app = AppointmentWatcherGui(root)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
