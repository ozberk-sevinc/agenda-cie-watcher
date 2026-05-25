# Agenda CIE Appointment Watcher

A local Windows/Selenium GUI watcher for the Italian Agenda CIE appointment flow.

The app is designed for the protected `Scegli la sede` step. You log in, solve CAPTCHA, and enter your real request details manually. Once the site shows the seat-selection table, the watcher refreshes and scans that visible table every minute. If it finds a selectable appointment inside your chosen date range, it updates the GUI, shows a large centered desktop alert, flashes the screen, and beeps.

## Why This Mode

Agenda CIE availability can depend on the details entered earlier in the official flow, including the document request type such as `Primo documento`. Earlier API-only checks can report generic availability that may not match the page produced by your actual request.

This watcher avoids that mismatch by reading the table shown after your manual choices.

## Requirements

- Windows
- Python `>=3.11`
- Microsoft Edge
- Tkinter, included with standard Python on Windows
- Selenium, declared in `pyproject.toml`

Selenium Manager handles the matching Edge driver automatically in normal setups.

## Install

From this folder:

```powershell
python -m pip install -e .
```

If Windows blocks script execution, run the Python file directly:

```powershell
python .\selenium_takeover.py
```

## Usage

Start the GUI:

```powershell
.\run_selenium_takeover.ps1
```

In the GUI, enter the acceptable date range using `DD/MM/YYYY` or `YYYY-MM-DD`, then click `Start Watcher`.

Then in the Edge window:

1. Log in manually.
2. Enter your request details manually.
3. Select `Primo documento` manually.
4. Continue until the page says `Scegli la sede`.
5. Leave the browser there.

The watcher scans:

- `Comune di Roma`
- `Comuni vicini a Roma`

It refreshes every 60 seconds and alerts only for selectable rows inside the date range set in the GUI.

## Privacy

The app does not ask for or store SPID/CIE credentials, passwords, codice fiscale, or copied cookies. Edge session data is stored locally in `edge-profile-selenium/`, which is ignored by Git.

## Files

- `selenium_takeover.py`: GUI and Selenium watcher
- `run_selenium_takeover.ps1`: Windows launcher
- `pyproject.toml`: Python dependency metadata
- `.gitignore`: excludes browser profile, logs, caches, and virtual environments

## Stop

Click `Stop` in the GUI, or close the GUI window.
