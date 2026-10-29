# Anti-idle correction · 3.5.1

## What was wrong

Version 3.5.0 put anti-idle inside `maintenance()`. The actual main loop could skip that entire function for as long as cleanup remained unresolved, while an early-cleanup guard waited for the event title to clear, or during an active event. The nominal four-minute interval therefore was not an independent deadline. In addition, `check_window()` did not check the return value from foreground activation before its old click path. Pixel ownership and receiving foreground game input are different conditions.

These are reproducible code defects that could explain idle disconnects. No log from the user's affected run was supplied, so the exact cause of those particular disconnections is not established.

## Changes

1. Add `service_anti_idle()` as an independent per-window scheduler on the existing foreground input worker. No competing focus thread is added. Use window handles and monotonic deadlines; excluded windows retain their original identities.
2. Service urgent equip/cleanup first, then at most one due anti-idle window. During ordinary idle time, process all due windows before slow maintenance/OCR. The scheduler also remains reachable during prolonged cleanup, early-end waiting and stable active events.
3. Replace the arbitrary world click with one 120 ms Space scan-code press. Confirm foreground ownership immediately before input and recheck event transitions after activation. It does not alter hotbar selection or click purchase/reward controls.
4. Use the existing key-up `finally` block and release-only retry. Advance the normal interval only after the complete input call returns. Focus/capture/input failure uses a ten-second retry and an explicit log message; it does not block the other windows.
5. Log enabled/disabled state at startup, every completed input, the actual gap since the last one, the next interval and deferred attempts. These messages explicitly do not claim game/server idle reset confirmation.
6. Add a standalone **Anti-idle** input diagnostic and update Maintenance descriptions. Preserve the saved enable/interval settings. Remove the obsolete wall-clock click timestamps from the maintenance path.

An event transition can interrupt focus acquisition before Space is sent. If the event changes after key-down, release completes after the short hold and the main loop services the transition next. The event watcher remains independent. Anti-idle is an intentional small exception to suspension of routine chores during an event; popup OCR and rebirth remain suspended. It does not run background input against unfocused game windows.

## Verification

`tests/test_anti_idle.py` extracts the production functions without loading Windows bootstrap. It exercises the actual scheduler and scan-code wrapper with simulated Windows calls and clock:

1. Four windows receive matched Space key-down/up, and none refocuses or repeats before its deadline.
2. Changing wall-clock time does not alter monotonic scheduling.
3. Refused focus retries after ten seconds; peers continue and unsuccessful input is not recorded as completed.
4. Focus loss, moved geometry and repeated key-up rejection do not consume the full configured interval. Release retries contain no extra key-down.
5. Event start, event end and Stop preempt a pending pulse, including an event ending during foreground activation. An event/Stop during the hold still releases Space.
6. Disconnected windows are skipped without remapping peers; disabled anti-idle remains disabled.
7. The real `job_macro()` loop runs three separate 30-minute simulated scenarios: unresolved cleanup, early-end waiting and stable active events. All four windows receive at least seven pulses in each, with gaps below 243 seconds for a configured 240-second interval. Urgent handlers run first. No character-slot input or slow maintenance is permitted in those replay paths.
8. The standalone diagnostic visits all four windows without popup OCR or mouse clicks.

The older event-priority test explicitly disables anti-idle to retain its exact routine-chore ordering assertions. Anti-idle ordering is covered in the new production-loop tests. The window-recovery test adopts the simplified maintenance signature; its disconnect/state assertions are unchanged. The real Qt harness includes the new diagnostic callback.

The complete run passed **12/12 suites**. See `VALIDATION_3_5_1.log`. Earlier validation files remain historical.

## Live check and limits

Run `RUN_MACRO.cmd` and verify the title is **3.5.1**. Existing EXEs must be rebuilt with `BUILD_WINDOWS.cmd`. In Maintenance, leave **Prevent idle disconnects** on. Run **Diagnostics → Tests → Anti-idle** while Roblox is visible, with chat and menus closed, and watch for one jump in each window. Then start automation and check one full configured interval in Activity log.

Sending Space successfully is not proof of a jump or a server idle timer reset. Menus, text focus, animations, game changes, Windows input restrictions, suspension/locking of the desktop or other client conditions can still prevent useful game interaction. These were not live-tested here. If the kick persists, provide the precise disconnect message, affected window, whether the jump test worked, and the preceding 10–15 minutes of `macro.log`. This will separate missing scheduling/focus/input from game-side rejection or a different disconnect reason.
