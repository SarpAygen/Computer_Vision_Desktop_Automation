# Historical release notes

These notes describe earlier versions. Use README.md for the current release. Historical validation files retain their original measurements and scope.

# Computer Vision Desktop Automation

A Windows desktop application built with Python that uses computer vision and optical character recognition to monitor visual events and coordinate actions across multiple application windows.

The project was developed for Fish! An Anime RNG on Roblox. It detects the Hallows’ Eve event, manages character selection, and identifies Dracula mutations from the visible interface. It demonstrates desktop integration, image processing, background monitoring, and recovery from uncertain visual input.

**Current version: 3.4.0**  
**Status: Active development**

## Input and Hotbar Improvements (3.4.0)

This release changes event actions into short visits: acquire foreground focus, read the current selection, press once when needed, and confirm the result before leaving the window. Two fresh matching readings are still required. Responsive windows finish in that visit, including when another Roblox window would cover their hotbar afterward. A missed input or unreadable hotbar stays pending; it never counts as success.

Newly focused windows receive an 80 millisecond activation grace, and event keys are held for 100 milliseconds. The normal focus delay setting does not apply to these actions. After a key, equip confirmation has a 160 millisecond observation window and put away confirmation has a 120 millisecond observation window. These are polling budgets; screenshot processing and Windows calls add overhead. Hidden hotbars yield immediately. One unresponsive window cannot spend several seconds waiting before the next window gets its first input.

Only unfinished windows are retried. Readable windows waiting for a late input do not need another focus change during the retry cooldown. Repeating a character slot can toggle it the wrong way, so both equip and character toggle cleanup retain a two second repeat guard and require fresh evidence. A positively recognized slot 1 rod or bat remains eligible for faster repeated cleanup, because selecting that tool cannot select a character. The macro never treats sending a key as proof that the game accepted it.

Idle maintenance and manual fallback now use the same slot aware cleanup logic as event end. This fixes an older manual verification path that could mistake a selected rod for a character and press the character key outside Hallows’ Eve. Cleanup uses the actually selected character slot. Idle recovery also reads mutation labels so it can prepare the next smart target before the event starts.

Smart rotation still verifies its prepared candidate against the current size, card layout and mutation label. A later unreadable slot no longer blocks an earlier confirmed eligible character; an uncertain earlier slot still prevents guessing. Missing plans, changed layouts and red or ambiguous mutation labels can require a full scan. Keep the inventory arrangement unchanged during a run.

Hotbar processing avoids duplicate row searches, reuses edge extraction within a single capture, classifies only each card’s rim, and scans blue selection edges with OpenCV. Every state observation still uses a fresh screenshot. On the supplied two slot fixture, local image processing fell from 3.687 to 1.937 milliseconds per snapshot, about 47.5%. This excludes screen capture, OCR, Windows input and game latency. Results are in `HOTBAR_BENCHMARK.log`.

### Run this version

1. Extract the entire ZIP into a new folder.
2. Open `HallowsEveMacro_Project/HallowsEveMacro` and run `RUN_MACRO.cmd`.
3. Confirm the title says **Macro Studio 3.4.0**. Saved settings remain in their existing location.
4. If you use a compiled executable, rebuild it with `BUILD_WINDOWS.cmd` to include these changes.

### Check the result

The Activity log reports `equip input sent`, `EQUIP CONFIRMED visually`, `put-away input sent` and `UNEQUIP CONFIRMED`. Pending equip messages now distinguish unavailable focus, hidden hotbars, changing selection and required mutation scans, and show the number of actual key inputs. Equip timings begin at confirmed event detection; cleanup timings begin at the cleanup request. The hotbar highlight confirms local UI state, not server acceptance.

Open **Activity log → Open saved log** for the live run log. `INPUT_TRANSACTION_VALIDATION.log` contains this release’s regression results. Historical validation files describe their corresponding older releases.

The regression suite covers dropped and late inputs, overlapping windows, hidden catch animations, safe tools, manual fallback, smart rotation, disconnected windows, event priority and key release after an interrupted hold. The delayed response replay confirmed four overlapping windows in 1.12 seconds for equip and 1.20 seconds for put away, using a simulated 130 millisecond game response. These are simulated timings, not measurements on a running Roblox client. The existing early countdown cleanup remains enabled by default. Live performance depends on game rendering, Windows activation, visibility and load.

The older release notes below document previous behavior. This section takes precedence for current input timing and confirmation behavior.

## Event Equip Recovery (3.3.2)

The first equip pass previously discarded skipped windows and then suspended all retries for the rest of the event. Every active window now receives an explicit equip result. A skipped window remains pending and is retried individually, with at least two seconds between its attempts. Windows that completed their equip pass are not toggled again. An unconfirmed previous unequip still blocks new input to that window.

Foreground activation is checked over a short interval because Windows can finish activating a window after the request returns. If needed, an asynchronous raise request preserves window coordinates, size, and topmost status. Focus uses no mouse click and does not attach the macro's input queue to the game's queue. A failed focus attempt is logged instead of silently skipping the window.

Only pending event equips run during the event; routine maintenance, rebirth, anti AFK, and mutation progress scans remain suspended. Event end interrupts pending retries, clears their queue, and starts priority put away. Retries retain covered banner protection, so a covered event monitor cannot silently suspend end detection while other characters are equipped.

Versions 3.3.2 and 3.3.3 applied the normal focus delay to initial equips. Version 3.3.4 removes that delay from both event equip and put-away paths.

`EQUIP_FIX_VALIDATION.log` contains the 3.3.2 results, including a three window scheduler replay where only the third window initially equips and the other two recover without toggling the third again. Focus calls and key input are simulated; this is not a live Roblox timing guarantee.

Windows activation behavior: [Microsoft explanation](https://devblogs.microsoft.com/oldnewthing/20161118-00/?p=94745/) and [SetWindowPos flags](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowpos).

## Window Switching Fix (3.3.1)

Window activation now uses Windows foreground APIs without moving the cursor or clicking the title bar. Already focused windows are left alone, and activation no longer toggles the window's always on top state. Character input still requires verified foreground ownership.

Visible idle hotbars are checked without changing focus. Covered hotbars receive a foreground audit about every 20 seconds, scheduled from the end of the previous audit, instead of cycling through every window once a second. Other scheduled actions, such as maintenance and mutation scans, can still switch windows when needed. Returning to the event monitor only changes focus if its banner is covered.

Event end cleanup still sends its first put away pass immediately and retains rapid visual confirmation. Hidden hotbars or refused focus use a 0.5 second retry interval to reduce repeated switching during animations. An unreadable hotbar remains unconfirmed, and a pending window cannot equip a new character. No global delay was added to event detection or urgent cleanup.

Extract the complete updated ZIP, open `HallowsEveMacro_Project/HallowsEveMacro`, and run `RUN_MACRO.cmd`. The title should show **Macro Studio 3.4.0**. If you normally use a compiled executable, run `BUILD_WINDOWS.cmd` to rebuild it; an older executable will not use these source changes.

The focused regression results are in `FOCUS_FIX_VALIDATION.log`. They cover mouse free activation, idle switching frequency, hidden hotbar recovery, dropped and delayed keypresses, disconnect handling, and event priority. Windows input is mocked; live Roblox acceptance and timing still require checking on your Windows machine.

## Halloween Interface and Performance

![Hallows’ Eve Macro Studio dashboard](docs/dashboard.png)

Version 3.3 gives the native desktop interface a charcoal and orange theme, vector icons, rounded controls, subtle eclipse animation, and clearer equipment status. Existing settings and the confirmed cleanup behavior from version 3.2 are preserved. No browser, web server, or additional runtime is needed.

1. **Dashboard:** See event counters, each window’s equipment state, confirmed Dracula progress, and current cleanup status. Start and Stop remain available on every page.
2. **Automation:** Settings are grouped into **Event & characters**, **Maintenance**, **Notifications**, and **App settings**. Short descriptions explain manual fallback, the early put away margin, and which checks always remain active.
3. **Diagnostics:** Switch between **Live view**, **Tests**, and **Support & exports**. Tests distinguish screen reading from actions that send input.
4. **Activity log:** Search messages or filter events, equipment, and warnings. Confirmations appear in green, event messages in orange, and warnings in red. Unconfirmed unequips are included in warnings.

Log updates are batched and appended without rebuilding the entire document for every message. The visible log remains limited to 1,500 messages, while rotating log files retain more history. Preview images are converted only when the capture or display size changes. Diagnostic image publication is limited to five times per second; loss and restoration of visibility are published immediately.

The event detector continues checking fresh frames at its existing rate. Only fixed reference templates are reused; event verdicts and equipment readings are not cached. Decorative animation stops while a job runs, while the dashboard is hidden, or while the application is inactive or minimized. **App settings → Reduce motion** also disables control transitions.

The interface was checked at 1280 × 900 and 1000 × 700 logical pixels. Pages scroll on smaller windows, and the initial window size adapts to the available desktop. Performance measurements in `VALIDATION.log` are local replay results, not whole application CPU or live game latency guarantees.

## Event Priority and Confirmed Put Away

Version 3.2 separates sending a key from confirming that Roblox accepted it. An older path marked characters put away after sending input and could ignore later evidence that a character remained selected. Cleanup now keeps each window pending until two fresh, readable hotbar observations confirm that no character is selected.

The banner watcher targets a visual check every 40 milliseconds. When the event title disappears, multiple absent frames trigger cleanup without waiting for mutation OCR. Low priority tasks can be interrupted immediately, and end requests remain pending across successive events.

**Automation → Event & characters → Unequip before timer ends** defaults to **2 seconds**. A separate event timer reader requires two decreasing, time consistent countdown readings before estimating the deadline. Cleanup then begins before that deadline to give all windows time to respond. This deliberately gives up the final part of the event to reduce exposure to the following event. Set the margin to zero to disable early cleanup. If the timer cannot be read, visual end detection remains active. Timer OCR errors do not stop the visual detector.

Cleanup makes a quick first pass across all windows before retrying missed inputs. At startup, the macro can recognize the reserved slot 1 rod or bat using known artwork or a readable tool name. Switching to that tool puts the character away; repeating it selects or puts away the tool without selecting a character. A rod or bat may therefore remain held after cleanup. Unknown items and consumables are not selected as replacement tools. Keep your inventory arrangement unchanged during a run.

If no replacement tool is recognized, retries use fresh evidence of the selected character. A hidden hotbar remains unconfirmed. During a catch animation, a recognized replacement tool can still be requested, but visual confirmation waits until the hotbar returns. Without a recognized replacement tool, the macro makes one best effort tracked toggle and waits for readable evidence before toggling again.

Unconfirmed windows remain in priority recovery and cannot equip for a new event. Other confirmed windows can participate in subsequent events. Slow maintenance and mutation scans wait while idle cleanup remains unresolved. An idle equipment check also catches characters that appear after an earlier confirmation. A window that temporarily refuses focus remains in recovery; a genuinely disconnected or closed window is excluded.

If a recognized popup blocks keypresses, cleanup checks for it after the fast input pass has reached the other windows. Popup recovery is rate limited and its OCR wait can be interrupted by another event end.

The Activity log distinguishes **put-away input sent**, **UNEQUIP CONFIRMED**, and **UNEQUIP UNCONFIRMED**. Timings are measured from the cleanup request to input or visual confirmation. They do not measure server acceptance. Extended loss of banner visibility after the equip pass triggers a protective put away, and the old event title cannot re-equip characters after early cleanup.

All tracked windows must share the same event timing: the active main banner controls the session. Window focus, rendering delays, hidden interfaces, and game updates can affect detection and input acceptance. No live game timing or mutation outcome is guaranteed.

## Window Recovery and Daily Rewards

A disconnected, closed, minimized, or unavailable Roblox window is marked **Skipped** for the rest of the run. The remaining windows keep running with their original character settings. If the skipped window supplied the event banner, monitoring moves to the first remaining window. Event cleanup tries the working windows before retrying a window that refuses focus. An open window with unconfirmed equipment remains in recovery so it is not silently abandoned while holding a character.

Reconnect the skipped window, then stop and start the macro to include it again. The macro does not reconnect or rejoin games automatically. If no usable windows remain, it stops and asks you to reconnect. Other event detection problems can still trigger the existing recovery pause.

**Automation → Maintenance → Close Daily Rewards popups** is enabled by default. The macro checks once at startup and then about every two minutes per window during idle maintenance. It verifies the Daily Rewards title and the red X against fresh screenshots, then clicks that X. Reward and paid skip buttons are outside the detection strip. Routine checks wait until Hallows’ Eve cleanup finishes and can be interrupted by a new event. An unresolved put away can also request a targeted popup check after the first input pass.

Connection messages must be readable to be recognized. A covered window is checked when it next becomes visible or is brought forward for maintenance. Popup detection is based on the supplied layout; if the interface changes or recognition is uncertain, it leaves the popup alone.

## Features

1. **Visual event detection:** Monitors a small banner region using image matching, with OCR available for layouts that the visual matcher cannot recognize.
2. **Dynamic inventory detection:** Locates hotbar cards from their visual layout instead of relying on fixed screen coordinates. Character rotation begins at slot 2 and excludes recognized consumable items.
3. **Mutation recognition:** Uses colour filtering and Tesseract OCR to identify Dracula labels and choose the next eligible character. Unreadable labels remain uncertain rather than being treated as a negative result.
4. **Multiple window support:** Brings each active Roblox window forward for actions and focused scans, then restores the event source. Disconnected windows are skipped, and the event source is replaced when necessary.
5. **Recovery and fallback:** Retries uncertain scans and temporarily unavailable interfaces. Persistent hotbar failures switch the affected window to manual key mode while other windows retain smart rotation. Only retries needed to finish pending equips run during an active event.
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

During smart rotation, the application locates the hotbar, distinguishes characters from items, and reads mutation labels. Repeated readable observations are used to confirm the state before choosing a character. When cleanup is requested, the application prioritizes putting characters away and confirms the resulting selection without mutation OCR.

If hotbar scans remain uncertain for at least 40 seconds and three failed scan passes, the affected window switches to manual fallback for the remainder of the run. This mode uses the last tracked character key, or the configured manual key when no tracked key is available. It equips during the event without mutation scans. Both equip confirmation and event cleanup still check the selected outline, so sending a key is not reported as a visually confirmed state.

## Getting Started

1. Download the repository as a ZIP and extract it into a writable folder.
2. Install Python for Windows with the Python launcher if it is not already available.
3. Open Roblox, join the game, and arrange the windows you want to automate.
4. Double click `RUN_MACRO.cmd`.
5. Allow the first launch to install missing Python dependencies. Tesseract is located automatically or installed through Windows Package Manager when available. Missing dependencies require internet access, and installation may require approval.
6. Select **Setup guide** and run the checks, then review **Diagnostics → Live view** and **Activity log**.
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

Open **Automation → Notifications**, enter a Discord compatible HTTPS webhook URL, and enable the desired alerts.

Dracula notifications are sent once per confirmed window and slot during each run, including mutations already present at startup. A window in manual fallback cannot report new mutation detections. Notification delivery runs in the background and is best effort.

Webhook URLs are stored in local settings. Do not commit personal settings or credentials to the repository.

## Diagnostics and Validation

An event priority regression test is included in `tests/test_event_priority.py`, with narrow banner fixtures in `tests/fixtures`. From the project folder, run `python tests/test_event_priority.py` after OpenCV and NumPy are installed. It checks slow OCR interruption, visual and OCR assisted starts, stale OCR rejection, countdown changes, manual key tracking, and successive events. Windows focus and input are mocked.


Version 3.1 adds `tests/test_window_recovery.py`. Run `python tests/test_window_recovery.py` with OpenCV, NumPy, pytesseract, and Tesseract installed. It checks per window exclusion, main window failover, startup and maintenance disconnects, cleanup continuity, stale input and OCR rejection, and Daily Rewards detection using a narrow crop from the supplied screenshot. It also checks popup timing and event deferral. Windows focus and input are mocked.

Version 3.2 adds `tests/test_confirmed_cleanup.py`. Run `python tests/test_confirmed_cleanup.py` to replay dropped and delayed inputs, unknown hotbars, refused focus, blocking popups, slot 10, cleanup without duplicate toggles, idle recovery, real hotbar and tool artwork, timer recognition, and early cleanup across consecutive events. The input timing model is simulated; screenshot processing, Tesseract, and detector threads are real.

Version 3.3 adds `tests/test_frontend.py` and `tests/test_performance.py`. The frontend test uses real offscreen PySide6 widgets to check navigation, setting persistence, controls, cleanup status, log filtering and batching, previews, and reduced motion. It uses temporary settings and logs and does not launch installers or send Windows input. The performance test checks preview publication, visibility transitions, immutable capture copies, shared reference templates, and fresh banner verdicts.

The **Activity log** displays scan results and recovery messages. **Diagnostics** provides capture previews and setup checks.

A manual Dracula scan saves an annotated image, an unmarked capture, and slot readings as `hotbar_debug_N.png`, `hotbar_raw_N.png`, and `hotbar_readings_N.json`. These files are overwritten by subsequent scans for the same window, so preserve them immediately when investigating a failure.

Development checks include real captured images, different hotbar lengths, consecutive Dracula labels, selected slot detection, incomplete row rejection, and simulated input sequences. Version 2.9 added checks for mutation crop alignment and potion recognition against bright scenery. Results are recorded in `VALIDATION.log`.

The included tests reproduce event priority, window recovery, confirmed cleanup, the desktop interface, and performance checks. Earlier validation records refer to development tests that are not all packaged here. Local replay timings do not establish live game accuracy or response times.

## Logs and Settings

1. Runtime logs: `%LOCALAPPDATA%\HallowsEveMacro\logs\macro.log`
2. Dependency setup log: `%LOCALAPPDATA%\HallowsEveMacro\setup.log`
3. Settings: `%LOCALAPPDATA%\HallowsEveMacro\hallows_macro_settings.json`
4. Build output log: `build.log` beside the build script.
5. Hotbar diagnostic captures: Saved beside the application.

## Current Limitations

1. The application supports Windows and the specific game interface it was developed against. It is not a general automation framework for arbitrary applications.
2. Detection depends on visible screen content. Interface changes, overlapping windows, animations, and display scaling can affect recognition.
3. Manual fallback cannot automatically skip newly mutated characters. Cleanup requires readable visual confirmation; hidden or ambiguous equipment stays pending.
4. Hotbar uncertainty triggers retries and fallback. Unavailable windows are skipped. No usable windows, prolonged event detection problems, and other faults that affect the whole run can still pause automation.
5. Event recognition and equipment changes have different timing. Window focus changes, OCR, input verification, and the number of windows affect overall response time. No guaranteed latency or accuracy is claimed.

## Engineering Focus

This project explores how to turn uncertain visual observations into controlled desktop actions. The main challenges include aligning small text regions, distinguishing inventory items from characters, handling changing layouts, and preserving consistent equipment state across event transitions and scan failures.

## Updating to Version 3.3

Close the old macro, extract the updated project, and launch `RUN_MACRO.cmd`. Confirm that the application title says Macro Studio 3.3. Rebuild any executable using `BUILD_WINDOWS.cmd`. Existing settings are preserved. Confirmed cleanup is automatic. The countdown margin still defaults to two seconds and is under Automation → Event & characters. Window exclusion, event source failover, and Daily Rewards closing remain available.
