# Architecture

## Overview

This repository is a small local desktop tool with one Python module:

- `selenium_takeover.py`

The module owns four responsibilities:

1. runtime configuration
2. Edge session startup and Selenium attachment
3. page scanning and appointment matching
4. Tkinter GUI and worker-thread orchestration

The code is intentionally compact because the application surface is narrow.

## Main Components

### `RuntimeConfig`

Loads operational settings from defaults plus optional environment variables:

- Edge executable path
- remote debugging port
- refresh interval
- Edge profile directory

This keeps machine-specific settings out of the GUI logic.

### `EdgeSession`

Owns the Selenium browser lifecycle:

- checks whether the debug port is already live
- starts Edge with the required flags when needed
- attaches Selenium to the running Edge instance
- closes the WebDriver cleanly on shutdown

The important distinction is that the app attaches to an existing browser session instead of driving a fresh isolated Selenium profile each time.

### `SCRAPE_SCRIPT`

JavaScript injected into the page through Selenium. It:

- validates that the browser is on the `Scegli la sede` page
- reads rows from the active table
- attempts to switch to `Comuni vicini a Roma`
- returns structured row data back to Python

The Python side then handles filtering, logging, and notification behavior.

### `WatcherWorker`

Background thread that:

- starts or attaches to Edge
- runs the page scan
- filters results by date range
- emits status, log, error, and match events back to the GUI
- refreshes the page on the configured interval

The worker keeps Selenium off the Tkinter main thread.

### `AppointmentWatcherGui`

Tkinter front end that:

- collects the user date range
- starts and stops the worker
- displays status text and activity logs
- renders the latest appointment match

It communicates with the worker through a `queue.Queue`.

## Control Flow

1. The GUI loads `RuntimeConfig`.
2. The user starts the watcher.
3. `WatcherWorker` starts in a background thread.
4. `EdgeSession` either:
   - attaches to an already-running debug session, or
   - launches Edge with remote debugging enabled
5. Selenium runs `SCRAPE_SCRIPT` against the target page.
6. Python filters rows by:
   - valid Italian date
   - selectable row
   - user-selected date range
7. Matching rows trigger logging and desktop notification.
8. The worker sleeps for the configured interval, refreshes, and repeats.

## Failure Model

Expected failure points:

- Edge executable not found
- debug port unavailable
- Selenium attachment failure
- site not yet at `Scegli la sede`
- DOM changes on the target page
- browser closed while the worker is still running

The current design reports these through GUI status/log messages and the local log file. It does not try to auto-heal every browser failure. Restarting the watcher is the normal recovery path.

## Operational Notes

- The app is Windows-only in practice because the desktop notification path uses PowerShell and `System.Windows.Forms`.
- The watcher assumes the user is performing the official flow manually.
- The page parser is DOM-dependent and may need updates if `Agenda CIE` changes its HTML structure or labels.

## Maintenance Notes

If you modify the app:

- keep browser/session logic separate from the GUI
- keep the scan result shape simple and explicit
- prefer configuration over new hardcoded machine-specific values
- preserve clean `driver.quit()` behavior on worker shutdown

## Future Improvements

Reasonable future work, if needed:

- package the app as a Windows executable
- split the single module into `config`, `browser`, `scanner`, and `gui` modules
- add smoke tests around date parsing and result matching
- make the scanner more resilient to minor DOM changes
