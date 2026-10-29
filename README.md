# Computer Vision Desktop Automation

A Windows application for Fish! An Anime RNG on Roblox, using Python, OpenCV, Tesseract OCR, Windows input APIs and PySide6 to detect Hallows’ Eve and manage characters across up to four windows.

**Current version: 3.5.1 · Macro Studio**

![Macro Studio interface preview](docs/dashboard.png)

## Run the updated project

1. Close the old macro. Extract the entire ZIP into a new, writable folder.
2. Open `HallowsEveMacro_Project/HallowsEveMacro` and double click `RUN_MACRO.cmd`.
3. Confirm the window title says **Macro Studio 3.5.1**. Keep `macro_runtime.py` beside `hallows_eve_macro.py`; do not copy only the main script.
4. Open the **Setup guide**, finish its checks, and review **Automation**. Existing compatible settings are preserved.
5. Open and arrange one to four game windows. Start with characters put away. Keep the main window’s event banner visible and the inventory arrangement unchanged during a run.
6. Start with **F6**, stop with **F7**, or use the interface controls. Hotkeys are configurable.

All tracked windows must share the same event timing. One main banner controls the run; unrelated server events are not monitored independently. Overlapping hotbars are supported through checked foreground visits, but a covered banner or hidden game interface cannot provide reliable event evidence.

This source launcher requires Python for Windows with the Python launcher and Tcl/Tk. First launch installs missing Python packages into a private environment using PyPI. It locates Tesseract or attempts installation through Windows Package Manager. Internet access and Windows installer approval may be needed. If automatic OCR installation fails, use the setup window’s download and executable-path options. Windows security protections should remain enabled.

An existing EXE does not use these source changes. Run this version’s `BUILD_WINDOWS.cmd` on Windows to rebuild it, then share the complete generated ZIP in `dist`. The build includes Tesseract by default, its language data and notices. A compiled distribution can run without a separate Python installation; test it on the intended computer before sharing. The build and clean-machine installation were not executed in the Linux validation environment.

## Anti-idle fix in 3.5.1

Anti-idle now has its own schedule for each window instead of depending on the popup/maintenance cycle. The previous cycle could be skipped indefinitely while equipment cleanup stayed unconfirmed or while the event-end guard waited for the old title to clear. The old click path also did not require confirmed foreground focus before advancing its timer.

The new action is a **120 ms Space press with confirmed foreground focus**, using the same scan-code input and guaranteed release attempt as equipment keys. It does not click the world, select a character or use popup OCR. Each due window is serviced individually between urgent equipment actions, including during prolonged recovery and stable active events. Event-start/end transitions take priority; Space is always released if a transition occurs during its short hold. Routine popup and rebirth work remains suspended during events.

The saved **Prevent idle disconnects** option and interval are preserved (default: four minutes per window). Scheduling uses monotonic time, so a computer clock adjustment cannot postpone input. Refused focus or failed input retries after ten seconds without consuming the full interval. A failed window does not block its peers. Start-up logs explicitly state whether anti-idle is enabled.

To check it on your computer:

1. Launch **3.5.1**, open **Automation → Maintenance**, and ensure **Prevent idle disconnects** is enabled.
2. Stop automation and select **Diagnostics → Tests → Anti-idle**. With Roblox visible and chat/menus closed, watch each character for a jump. The test sends one Space press per window and does not equip or unequip units.
3. Open **Activity log** and search `anti-idle`. Expect a per-window `diagnostic anti-idle Space sent` result. `NOT sent` or `deferred` identifies a focus/input problem.
4. Start the macro and watch a complete interval. Runtime messages show `anti-idle input sent`, the elapsed time since the previous input and the next due interval. Input-sent messages mean the OS call completed; they do not prove that the server reset its idle timer.
5. If a window still disconnects, return the activity log covering the preceding 10–15 minutes, the affected window and the exact disconnect message. Also report whether the standalone test produced a visible jump there.

`ANTI_IDLE_FIX_3_5_1.md` explains the fix and test evidence. All **12/12 regression suites passed**, including actual-scheduler replays of 30 simulated minutes in each of three prolonged states. Live Roblox idle timing is not verified by these simulations.

## Audit improvements retained from 3.5.0

1. **Background mutation scans:** Missing smart-rotation plans no longer make the foreground action worker wait for a full OCR scan. Ready windows can equip while a bounded two-worker pool reads copied hotbar crops. Pending scans do not repeatedly focus their window.
2. **Fresh inventory validation:** Prepared targets and completed scans are checked against current window size, card layout, artwork and mutation-label fingerprints. Changed or stale results are discarded. Every equipment confirmation still requires fresh visible observations.
3. **One confirmed input path:** Automatic manual mode, fallback, maintenance and the simulated-event diagnostic now use the same tracked equip/cleanup logic. Accepted key-down is recorded before key-up so cleanup retains the intended slot even if release fails. A rejected key-up gets a release-only retry.
4. **Capture and click guards:** A moved/resized window rejects a stale capture instead of reading old screen coordinates. Popup closing requires a recognized close marker; unverified purchase-popup fallback clicks have been removed. Mouse actions recheck ownership after moving the cursor.
5. **Recovery and bounded resources:** Failed post-event scans are scheduled again, focus refusal does not exclude a live window, and banner capture errors get bounded recovery. Scan queues and UI messages cannot grow without limit. Settings use validated values and atomic replacement; rebirth debug captures use a bounded cropped file per window.
6. **Clearer interface:** Each window now has a separate current-action line, explicit unconfirmed states and a visible shared-event requirement. The charcoal/orange theme, rounded controls, reduced-motion setting and grouped navigation are preserved.

See `AUDIT_3_5.md` for the causes, architecture, validation evidence and remaining limitations. `RELEASE_HISTORY.md` contains earlier notes. Older validation logs describe their corresponding releases.

## Event and equipment behavior

A dedicated watcher checks a small banner region, using visual matching for frequent checks and separate OCR assistance when needed. Event work interrupts idle maintenance. End requests cancel stale equip plans and pending mutation scans; unresolved cleanup has priority over new equips.

For each responsive window, the input worker acquires foreground ownership without clicking the title bar, reads its actual selection, sends a key only when needed, and observes the result during the same visit. Confirmation requires two fresh matching readings. A key being sent is not proof of success.

The existing fast input timing remains: 80 ms activation grace, 100 ms event key hold, and bounded local observation windows of 160 ms for equip and 120 ms for cleanup. These are budgets, not guarantees; captures, Windows and game rendering add overhead. Character-toggle retries retain a two-second guard and fresh evidence to avoid reversing delayed input. Only unfinished windows retry.

**Automation → Event & characters → Unequip before timer ends** defaults to two seconds. Two consistent decreasing countdown readings are required before using a deadline. This starts cleanup early to allow time for multiple windows. Setting the margin to zero disables early cleanup; visual end detection remains active. Sustained loss of banner evidence also requests protective cleanup, including during initial equip.

A positively recognized slot 1 rod or bat can replace a held character. Its recognition is invalidated when a readable inventory fingerprint changes. Unknown items and consumables are not assumed safe. Without a recognized replacement tool, cleanup uses the actual selected character or a tracked first attempt, and waits for readable evidence before repeating a toggle. A tool may remain held after the character is put away.

## Smart rotation and temporary uncertainty

Smart Dracula rotation locates cards dynamically and starts with slot 2. Confirmed Dracula characters are skipped. An unknown earlier candidate blocks guessing; an unreadable later slot does not block an earlier confirmed eligible one. Slot 10 uses the `0` key. Normal manual mode uses the configured character key.

Rare-catch animations can hide the hotbar for roughly 30 seconds. Hidden equipment remains unconfirmed, while other windows and event monitoring continue. After at least 40 seconds and three unsuccessful passes, a window can enter manual fallback for the rest of the run. It uses the last tracked character key, or the configured key if no prior key is available. Fallback cannot skip newly mutated characters, but still uses tracked input and confirmation when visible.

A window with unresolved cleanup cannot equip for a new event. Disconnects and unavailable windows are excluded without stopping healthy windows. Reconnect a skipped window and restart the macro to include it again. Temporary focus refusal remains retryable. No available windows or a fault affecting the whole run can still stop or pause automation.

Daily Rewards checks run at startup and about every two minutes per window during idle maintenance. The recognized title and close control must still be present before clicking. Unknown popup layouts are left alone. Urgent event work takes priority over routine popup checks.

## Interface and notifications

1. **Dashboard:** Event history, per-window confirmed equipment, mutation progress and current action.
2. **Automation:** Event and characters, maintenance, notifications and app settings. No saved-profile feature is added.
3. **Diagnostics:** Live captures, read-only checks, input diagnostics and support exports. The event test sends real input when run on Windows; regression tests do not.
4. **Activity log:** Search and filter events, equipment and warnings; open the saved rotating log.

Decorative animation pauses during automation and while hidden/inactive. Reduced motion is available. The UI retains 1,500 visible log lines; its worker mailbox is also bounded and coalesces old state updates. Overflow is reported rather than blocking input.

Optional Discord-compatible HTTPS webhooks report detected Hallows’ Eve events and confirmed Dracula slots. Delivery is asynchronous and best effort, with a bounded queue. Dracula alerts are deduplicated per window/slot per run and can include mutations already present at startup. Manual fallback cannot report unscanned new mutations. The URL is stored in local settings and redacted from diagnostic exports; do not share personal settings files.

## Tests and logs

Run `RUN_TESTS.cmd` after dependency setup, or `python run_tests.py`. This executes all 12 regression suites without starting Roblox input or the application installer. It uses the installed macro environment when available and writes `VALIDATION_3_5_1.log` beside the launcher. A failed suite produces a nonzero exit code. `--no-ui` explicitly skips the Qt suite and records that omission.

Included validation: **12/12 suites passed** with real fixture image processing, OCR and offscreen Qt, plus simulated Windows input/timing. Coverage includes slow/stale mutation OCR, moved windows, delayed/dropped keys, slot 10, hidden hotbars, safe tools, event interruption, manual fallback, disconnected windows and popup guards. `PERFORMANCE_3_5.log` contains the local comparison: image validation added about 3.2% to snapshot processing; the responsiveness gain comes from removing foreground OCR waits and queue growth, not a claimed whole-app speedup.

Runtime messages distinguish `equip input sent`, `EQUIP CONFIRMED visually`, `put-away input sent` and `UNEQUIP CONFIRMED`. They include window/slot, retries and elapsed timing. **Activity log → Open saved log** opens the actual run history.

| File | Location or purpose |
| --- | --- |
| `macro.log` | `%LOCALAPPDATA%\HallowsEveMacro\logs`, with rotation |
| `setup.log` | `%LOCALAPPDATA%\HallowsEveMacro` |
| `hallows_macro_settings.json` | `%LOCALAPPDATA%\HallowsEveMacro` |
| `VALIDATION_3_5_1.log` | Current regression test output beside the launcher |
| `build.log` | Build output beside the build script |
| `hotbar_debug_N.png`, `hotbar_raw_N.png`, `hotbar_readings_N.json` | Manual scan diagnostics beside the app; overwritten by the next scan of that window |

## Check on your Windows computer

1. Launch 3.5.1, finish setup and run a read-only Dracula scan. Confirm the detected cards and candidate slots match each window.
2. Use the **Diagnostics → Tests** event simulation with the game windows visible. It now uses the live equip and cleanup paths. Watch for confirmed states, then verify characters are actually put away. Stopping a diagnostic stops input; inspect and put away any remaining held character manually.
3. Observe two or three real events before leaving it overnight. Confirm healthy windows equip promptly and all show confirmed put-away before the next event. Keep the early cleanup margin enabled initially.
4. Test one disconnected window and, when available, a catch animation. Other windows should continue; hidden equipment should stay unconfirmed.
5. If something fails, export diagnostics immediately and record the event time, affected window, whether its banner/hotbar was visible, and whether the log says input sent or visually confirmed. Preserve the matching hotbar captures before running another scan.

Live Windows focus behavior, Roblox acceptance, actual monitor DPI, new game layouts, overnight mutation outcomes and the packaged installer have not been validated here. Local UI confirmation cannot prove server acceptance. No subsecond action guarantee across every window or zero unwanted-mutation guarantee is claimed.
