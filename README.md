# Computer Vision Desktop Automation

A Windows desktop application built with Python that uses computer vision and optical character recognition to monitor visual events and coordinate actions across multiple application windows.

The project was developed for Fish! An Anime RNG on Roblox. It detects the Hallows’ Eve event, manages character selection, and identifies Dracula mutations from the visible interface. It demonstrates desktop integration, image processing, background monitoring, and recovery from uncertain visual input.

**Current version: 2.9**  
**Status: Active development**

## Features

1. **Visual event detection:** Monitors a small banner region using image matching, with OCR available for layouts that the visual matcher cannot recognize.
2. **Dynamic inventory detection:** Locates hotbar cards from their visual layout instead of relying on fixed screen coordinates. Character rotation begins at slot 2 and excludes recognized consumable items.
3. **Mutation recognition:** Uses colour filtering and Tesseract OCR to identify Dracula labels and choose the next eligible character. Unreadable labels remain uncertain rather than being treated as a negative result.
4. **Multiple window support:** Brings each tracked Roblox window forward for actions and focused scans, then restores the main window.
5. **Recovery and fallback:** Retries uncertain scans and temporarily unavailable interfaces. Persistent hotbar failures switch the affected window to manual key mode while other windows retain smart rotation.
6. **Desktop interface:** Provides a PySide6 interface with configuration controls, detection previews, character progress, and an activity log.
7. **Webhook notifications:** Supports optional Hallows’ Eve and confirmed Dracula alerts through a Discord compatible HTTPS webhook.
8. **Setup and packaging:** Checks dependencies on launch and includes scripts for building a Windows application with its Python runtime and Tesseract dependencies.

## Technologies

1. **Python:** Application logic, background workers, and automation coordination.
2. **OpenCV and NumPy:** Image processing, colour filtering, contour analysis, and template matching.
3. **Tesseract OCR:** Text recognition within selected screen regions.
4. **PySide6:** Desktop interface, settings, and diagnostic views.
5. **Windows API and PyAutoGUI:** Window management and keyboard input.
6. **MSS:** Screen capture.
7. **PyInstaller:** Windows application packaging.

## How It Works

The event detector captures the main window’s banner region and evaluates whether Hallows’ Eve is active. Background monitoring keeps detection separate from the sequence of window focus changes and character inputs.

During smart rotation, the application locates the hotbar, distinguishes characters from items, and reads mutation labels. Repeated readable observations are used to confirm the state before choosing a character. When the event ends, the application prioritizes putting away the last tracked character without waiting for another mutation OCR pass.

If hotbar scans remain uncertain for at least 40 seconds and three failed scan passes, the affected window switches to manual fallback for the remainder of the run. This mode uses the last tracked character key, or the configured manual key when no tracked key is available. It equips during the event and puts the character away afterward without scanning for mutations.

## Getting Started

1. Download the repository as a ZIP and extract it into a writable folder.
2. Install Python for Windows with the Python launcher if it is not already available.
3. Open Roblox, join the game, and arrange the windows you want to automate.
4. Double click `RUN_MACRO.cmd`.
5. Allow the first launch to install missing Python dependencies. Tesseract is located automatically or installed through Windows Package Manager when available. Missing dependencies require internet access, and installation may require approval.
6. Open **Diagnostics**, run the setup checks, and review the capture previews and activity log.
7. Configure **Automation**, including smart rotation, the manual character key, and optional notifications.
8. Start with **F6** and stop with **F7**, or use the interface controls.

Start with the character put away, particularly if the initial hotbar scan is uncertain. Keep event banners visible and avoid changing equipped slots manually while automation is running.

## Building the Windows Application

1. On a Windows PC with Python installed, run `BUILD_WINDOWS.cmd`.
2. The build script installs build dependencies and packages the application with PyInstaller.
3. By default, it includes Tesseract and its required files.
4. Share the complete application ZIP generated inside `dist`. Recipients should extract the entire archive and keep its files together.
5. Test the packaged application on the intended Windows system before distributing it more broadly.

An existing executable must be rebuilt after source changes. Replacing the Python file alone does not update a previously built executable.

## Notifications

Open **Automation → Webhook notifications**, enter a Discord compatible HTTPS webhook URL, and enable the desired alerts.

Dracula notifications are sent once per confirmed window and slot during each run, including mutations already present at startup. A window in manual fallback cannot report new mutation detections. Notification delivery runs in the background and is best effort.

Webhook URLs are stored in local settings. Do not commit personal settings or credentials to the repository.

## Diagnostics and Validation

The **Activity log** displays scan results and recovery messages. **Diagnostics** provides capture previews and setup checks.

A manual Dracula scan saves an annotated image, an unmarked capture, and slot readings as `hotbar_debug_N.png`, `hotbar_raw_N.png`, and `hotbar_readings_N.json`. These files are overwritten by subsequent scans for the same window, so preserve them immediately when investigating a failure.

Development checks include real captured images, different hotbar lengths, consecutive Dracula labels, selected slot detection, incomplete row rejection, and simulated input sequences. Version 2.9 adds checks for mutation crop alignment and potion recognition against bright scenery. Results are recorded in `VALIDATION.log`.

The current repository contains the validation record but does not yet include the test scripts and image fixtures needed to reproduce those checks. Automated checks used mocked Windows input where required; they do not establish live game accuracy or response times.

## Logs and Settings

1. Runtime logs: `%LOCALAPPDATA%\HallowsEveMacro\logs\macro.log`
2. Dependency setup log: `%LOCALAPPDATA%\HallowsEveMacro\setup.log`
3. Settings: `%LOCALAPPDATA%\HallowsEveMacro\hallows_macro_settings.json`
4. Build output log: `build.log` beside the build script.
5. Hotbar diagnostic captures: Saved beside the application.

## Current Limitations

1. The application supports Windows and the specific game interface it was developed against. It is not a general automation framework for arbitrary applications.
2. Detection depends on visible screen content. Interface changes, overlapping windows, animations, and display scaling can affect recognition.
3. Manual fallback follows commanded equipment state and cannot verify that every keypress was accepted or automatically skip newly mutated characters.
4. Hotbar uncertainty triggers retries and fallback. Separate faults, such as closed windows or prolonged event detection problems, can still pause automation.
5. Event recognition and equipment changes have different timing. Window focus changes, OCR, input verification, and the number of windows affect overall response time. No guaranteed latency or accuracy is claimed.

## Engineering Focus

This project explores how to turn uncertain visual observations into controlled desktop actions. The main challenges include aligning small text regions, distinguishing inventory items from characters, handling changing layouts, and preserving consistent equipment state across event transitions and scan failures.
