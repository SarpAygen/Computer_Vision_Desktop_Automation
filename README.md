# Hallows' Eve Macro Studio — 2.9

Windows desktop macro for Fish! An Anime RNG.

Version 2.9 corrects mutation-label crops that follow inner card artwork, using the continuous coloured top frame to align the label. It also separates potion lettering from bright scenery before classifying items. Unreadable red lettering still remains unknown; it is never treated as permission to select a character. The supplied top-right label regions and bottom-left potion capture pass the regression checks, and the earlier real Dracula label is still detected. Live Windows/gameplay verification remains necessary.

Dracula scan now distinguishes unknown card types from confirmed items in the Activity log. Alongside hotbar_debug_N.png, it saves hotbar_raw_N.png (without annotations) and hotbar_readings_N.json (exact boxes and per-slot results). These are overwritten on each manual scan; copy them immediately after a failure.

Version 2.8 adds automatic per-window manual fallback after at least 40 seconds and three failed scan passes (each pass samples up to eight frames). Other windows keep Smart rotation. Fallback lasts until the next run, uses the last tracked character key when known, and sends once per event transition without hotbar verification. If startup cannot read the hotbar, it uses the Manual character key and assumes the character starts put away. Keep it put away before starting and avoid manually changing equipment during fallback. Disconnect/closed-window/event-detector faults can still pause.

Event-end cleanup uses the last tracked slot without OCR and a short 150 ms focus settle. An event ending interrupts ongoing equip work. A sent put-away command is not blindly repeated because of an uncertain highlight. Actual timing and key acceptance depend on Windows/Roblox; manual fallback cannot verify a missed keypress.

Webhook setup: Automation > Webhook notifications. Paste a Discord-compatible HTTPS webhook URL, enable Hallows' Eve alerts and/or Dracula alerts, and start the macro. The URL is masked but stored in local settings; diagnostic exports redact it. No extra dependency is required. The JSON payload contains content and allowed_mentions. Delivery uses a bounded background queue and five-second HTTP timeout; failures log without exposing the URL or stopping automation. No automatic HTTP retries, so delivery is best effort. Dracula alerts occur once per confirmed window/slot per run, including mutations already present at startup. No new mutation alerts are possible for a window in manual fallback. Hallows alerts follow the event detector.

The session log named hotbar_failure_2.zip for the latest top-right visual failure; that archive is still needed to reproduce its exact image pattern. This version changes recovery and timing rather than claiming that unseen pattern is fixed.

Version 2.7 adds a 40-second grace period for a missing or obscured hotbar, including at startup. The affected window gets no slot input while unreadable; the other windows continue. Retries are scheduled two seconds after a failed scan and run when the action worker is available. Recovery uses the latest detected event state, not the state at the start of the animation. The grace period starts at the first failed focused scan. Persistent failures still pause and save diagnostics. Visible but uncertain mutation text remains a separate failure. This detects HUD unavailability, not a particular animation.

Version 2.6 fixes the failure reproduced from hotbar_failure_1.zip: status icons beside the hotbar were contaminating the grid fit. Candidate slot centers are now bounded by the maximum centered ten-slot span. All eight actual failed frames detect ten slots, and the inactive-event replay completes without a needless keypress. Previous image, rotation, transient-failure, and incomplete-row checks pass. Live Windows behavior is not tested here.

Version 2.5 confirms two agreeing readable observations across up to eight frames, tolerates inner/outer border variation, and avoids mutation OCR when putting away a confirmed selected character. Persistent focused runtime failures still pause, but now save hotbar_failure_N.zip beside the macro with the exact eight hotbar crops and readings. Only narrow hotbar strips are saved locally; the next failure for that window replaces its archive. Use Diagnostics > Open debug folder to find it. The latest failure log alone cannot establish the exact visual cause; this update improves transient handling and captures evidence for remaining failures.

Version 2.4 fixes additional purple-star fringes mistaken for unreadable mutation text and fits bounded border-size/position variations. Smart rotation startup passes on crops from the latest screenshot with Windows focus/visibility mocked. The logged window-2 zero-slot capture was not reproduced from the desktop screenshot; send the new hotbar_debug_2.png if that remains.

Version 2.3 fixes zero-slot scans using independent neutral outlines, duplicate-contour removal, whole-row spacing estimates, and a small shared alignment correction. It also filters tiny red fringes around purple rarity stars. Validated on the actual debug captures: windows 1/2/3 detect 10/4/10 slots, exclude items, and select slot 2. Live Windows/game behavior still needs local verification.

Version 2.2 added verified grid recovery for merged selection/star contours, checks only actual card pixels for visibility, retries transient focused scans, and prevents background hotbar failures from stopping manual mode or rotation. Rotation still verifies the foreground hotbar before pressing a slot key. The event detector no longer depends on hotbar readability.

Version 2.1 fixed mixed character/item hotbars (including grey potion borders), excludes identified consumables from Dracula rotation, and fixes overlap-related pauses plus the bottom-edge visibility check. Slot 1 remains reserved; place characters to rotate from slot 2 onward. Start with `RUN_MACRO.cmd` (Python required), or build the shareable Windows app once using `BUILD_WINDOWS.cmd`.

## Run the source version

1. Extract this project ZIP into a folder you can write to.
2. Install Python for Windows with the **Python launcher** and **Tcl/Tk** components if you do not already have it.
3. Double-click **RUN_MACRO.cmd**, or run `python hallows_eve_macro.py`.
4. First launch checks dependencies, installs missing Python packages in a private environment, and finds or installs Tesseract through Windows Package Manager. Internet is needed for missing dependencies; Windows may request installer approval.
5. The guided setup opens automatically until checks pass. Open Roblox, join the game, arrange your windows, close popups, and move the macro away from their banners and hotbars. Click **Run checks**.
6. Review **Automation**, then press **Start macro** (default F6). Stop with **F7** or the Stop button.

Setup brings each Roblox window forward in turn and restores the main window; it does not select characters. During an inactive event it can verify capture but cannot prove event recognition. Run it again during Hallows' Eve to inspect the match. The macro also performs fresh health/hotbar checks before each start or resume.

## What changed

- **Fast event detection:** small banner crop, orange title shape matching, about 80 ms polling, and confirmation over several frames. The last successful template is reused first. A background OCR worker checks unsupported layouts without blocking the visual loop; an incompatible title switches that session to slower OCR. Disable Fast event detection to use OCR throughout.
- **Live detection preview:** Diagnostics shows the actual banner and selectable per-window hotbar crops, status, match score and stale-image age. Use Start read-only preview when the macro is stopped. The shared Stop button ends it. “Match” is image similarity, not a calibrated probability.
- **Guided setup:** dependencies/English OCR, window discovery, banner capture and hotbar recognition. Available again in Diagnostics.
- **Safe recovery:** stop game inputs when a tracked window closes/minimizes, a visible connection warning is recognized, a focused rotation scan remains unreadable after retries, or event detection stays unknown. Background hotbar failures are deferred to the next focused scan; they do not stop manual key mode. A reason appears on Overview. Fix the problem and use **Resume / recheck**, which rescans windows and reruns fresh checks. The macro does not click Reconnect or resume blindly.
- **Dracula progress:** each window reports its observed selected slot, completed/total visible characters, and Dracula slot numbers. Dynamic hotbar positions remain supported, including slot 10 (key 0). Progress refreshes during startup, equipment changes and maintenance, not every video frame.
- **Optional completion stop:** enable **Stop when all characters have Dracula** in Automation. Every tracked window must have fresh, confirmed complete readings. It only covers the currently visible hotbar, not characters in storage. A completion message and optional sound indicate the stop. This option starts off disabled so old runs do not unexpectedly end.
- **Diagnostic ZIP export:** Diagnostics → Export diagnostic bundle. Contains settings, recent/persisted logs, version details, recovery reason and last progress. Screenshot crops are **off by default**. Logs may include account names/local paths; review them before sharing. Your configured Tesseract path is omitted from exported settings.

## Timing and visibility

The visual confirmation thresholds are 0.20 seconds for start and 0.45 seconds for end, plus capture/processing/poll scheduling. Local screenshot simulations measured approximately **0.28 s start / 0.60 s end**, including a deliberately slow parallel OCR task. This is not a live Windows/Roblox benchmark or a guaranteed maximum. OCR fallback uses slower confirmation, including 3 seconds for end.

A covered event banner, minimized window or ambiguous capture cannot provide reliable event timing. Overlapping tracked Roblox windows are supported: covered hotbars are deferred until that window is raised; each startup/setup scan raises windows in sequence. Unknown readings preserve the previous verdict and reset pending confirmation; persistent uncertainty from unrelated obstructions pauses the run. Normal overlap from another tracked Roblox window does not trigger that timeout. If an event lasts more than 600 seconds, the macro pauses for review instead of inventing an end. Keep the main event banner visible when possible and move Macro Studio away from the game. The main window is restored after equip/unequip passes. Background monitors never steal focus. The health monitor scans visible connection dialogs periodically; it cannot guarantee recognition of every Roblox message or a warning hidden behind another app.

Detection and game actions have separate timing. Focus delay, mutation OCR, verification and the number of windows still affect how quickly all characters are equipped. Existing focus/action timings are preserved.

## Build the Windows app for friends

**Build on a Windows PC with Python.** This source package does not contain a prebuilt executable. PyInstaller builds for the operating system it runs on: https://pyinstaller.org/en/stable/usage.html#supporting-multiple-operating-systems

1. Double-click **BUILD_WINDOWS.cmd**. Build progress is written to **build.log** in this folder.
2. The script creates a dedicated `.build-venv`, installs the build requirements, and builds a folder containing **HallowsEveMacro.exe**, Python runtime and app dependencies.
3. It finds Tesseract or installs it with winget, then copies its **complete folder**, including DLLs, English data and bundled notices, into the app folder. Approve the standard Windows installer prompt if shown. For a custom install: `py -3 build_windows.py --tesseract-dir "C:\path\Tesseract-OCR"`.
4. Share **dist\HallowsEveMacro-Windows.zip**. Friends extract the entire ZIP and double-click **HallowsEveMacro.exe**. They do not need Python; the default build includes Tesseract. Keep every extracted file together.
5. Test the ZIP on a Windows account without Python/Tesseract before distributing it broadly. The build script checks bundled OCR language discovery, but does not perform live game tests or a clean-PC launch test.

Optional: `py -3 build_windows.py --without-tesseract` produces a smaller bundle that attempts to install Tesseract through winget on first launch. This variant requires internet/installer approval when OCR is missing. If winget is unavailable, the setup window provides the Tesseract download link and path selection.

The build copies installed package license/notice metadata and records exact installed versions in `build-versions.txt`. Keep those and the complete Tesseract distribution notices with the app.

## Logs and settings

- In-app results: **Activity log**; Diagnostics test results appear there.
- Runtime logs: `%LOCALAPPDATA%\HallowsEveMacro\logs\macro.log` (rotates with three backups).
- First-run dependency setup: `%LOCALAPPDATA%\HallowsEveMacro\setup.log`.
- Settings: `%LOCALAPPDATA%\HallowsEveMacro\hallows_macro_settings.json`. Old settings beside the script are migrated on the next successful save.
- Windows build: `build.log` beside BUILD_WINDOWS.cmd.
- Some existing image diagnostics save debug crops beside the app; run from a writable folder.

## Validation performed for this update

- Python syntax checks for app/build scripts.
- Real OpenCV matching against the supplied event/non-event screenshots at five simulated scales, plus blank/color negative images.
- Event transition tests: brief flicker, unknown/covered intervals, fresh end confirmation, and slow OCR running separately.
- Completion checks across all windows, stale data rejection, and disconnect cancellation before input.
- Existing Dracula rotation regression checks: 2/3/5/7/10-card layouts, consecutive Dracula labels, selected-slot detection and key 0.
- Real Qt offscreen rendering and UI checks for preview, settings, setup messages, progress and diagnostic ZIP contents, including crops excluded by default.

Actual Windows input/focus, installer execution, built executable launch and live game timing could not be tested in the development environment. Use guided setup and a supervised run on your computer first.

## Updating to 2.9

Close the old process before replacing files. Run RUN_MACRO.cmd from this extracted folder and verify the title says Macro Studio 2.9. Rebuild any older EXE with BUILD_WINDOWS.cmd; updating the source file does not update an already built EXE. Settings are preserved. Manual key mode stays manual; enable Smart Dracula rotation in Automation if you want Dracula-based slot skipping.
