# Engineering audit · Macro Studio 3.5.0

Input: the supplied `HallowsEveMacro_3_4_0_Optimized_Input(1).zip`. Output: the complete 3.5.0 source distribution. Validation date: 29 October 2026.

## Findings and decisions

The supplied version already had useful safeguards: exact-slot confirmation, bounded local verification, event-end priority, safe-tool cleanup, visual banner matching, window exclusion and a native Qt interface. A complete rewrite would discard those tested behaviors without addressing a demonstrated need. This release keeps the stack and strengthens the shared action path, async work boundaries and resource limits.

| Finding in the supplied implementation | Change | Verification |
| --- | --- | --- |
| A missing prepared target could require foreground mutation OCR before servicing other windows. | Snapshot once; submit bounded background mutation work; service ready peers; validate the finished result against fresh evidence and event generation. | Hold a scan pending for 100 polls: no extra focus changes, one submitted scan, another window equips first. |
| Layout and card type alone could preserve a target across changed character artwork or mutations. | Add conservative artwork/label fingerprints and window-size validation; discard mismatches. | Changed inventory, resized windows, unknown labels and ended events reject stale results. |
| Accepted key-down could be lost from tracking if key-up failed before the call returned. | Record the action through an accepted-down callback inside the release-protected block; retry a rejected release without another key-down. | Failed release preserves the target/attempt and restores the callback; interrupted hold and release-only retry checks pass. |
| Legacy diagnostics/corrections could use a different toggle path from the running macro. | Remove old boolean correction helpers; route automatic modes and the simulated-event test through tracked actions. Keep the explicitly requested one-shot manual toggle diagnostic separate. | Four-window diagnostic uses production equip/cleanup, with eight expected keys; selected tools remain safe during maintenance. |
| A cached rectangle could survive a move/resize and address stale screen coordinates. | Check window identity and geometry before/after capture. Treat stale frames as unavailable, without excluding a live window. | Moved geometry is rejected while window eligibility is retained. |
| Some popup paths could click a fallback coordinate without proving a close control. | Require an X marker and recheck visibility/ownership at click time. Remove unverified purchase fallback. | Missing/invalid markers do not click; scaled supplied Daily Rewards images still pass. |
| Failed post-event scans could miss the idle retry queue. | Requeue uncertainty and retain per-window fallback timing. | All four failed scans are requeued; at least 40 seconds and three failures trigger local fallback. |
| UI producer messages and OCR work could accumulate beyond their consumers. | Bounded coalescing mailbox and admission-limited executors; no backlog of submitted scans. | 100,000 UI updates remain bounded; 1,000 excess scan submissions are rejected without queue growth. |
| Settings writes could leave a partial file and unvalidated values could enter runtime. | Validate supported values and atomically replace settings. | Invalid types/nonfinite values rejected; failed serialization leaves the old settings intact. |
| Rebirth debugging could accumulate broad captures. | Keep one cropped menu capture per window. | Source inspection; no live rebirth action executed here. |

## Runtime organization

The foreground action worker remains the sole automation authority for keyboard and mouse transactions. It owns per-window equip plans, accepted commands, retries and cleanup hints. Detector and health threads observe state; mutation workers only read copied images and never acquire focus or send input. The UI communicates through a bounded mailbox. Webhooks keep their separate bounded delivery queue.

`macro_runtime.py` contains platform-independent mailbox, executor and settings infrastructure. The main module retains tightly related vision/input/scheduling code to avoid a risky packaging-wide migration. No new runtime dependency, server or language is introduced. Existing Python bootstrap, Tesseract setup and Windows build support are preserved; the build now checks for both source modules.

The watcher uses small fresh captures and a separate OCR fallback. Input captures also verify ownership. End requests preempt lower-priority work and cancel event-specific scan state. An already-running OCR subprocess can finish within its timeout, but its result cannot authorize an old event's action. Outstanding scan capacity remains bounded while cancellation completes.

Per-window equipment remains explicit: pending input is not confirmation, hidden is not safe, and completed windows do not receive another toggle just because a peer is unfinished. A selected known tool is distinct from a selected character. Old cleanup must resolve before that window can equip in another event. Disconnected windows are excluded; temporary focus refusal remains retryable.

The main banner controls every tracked window, so shared event timing is required and displayed in the interface. Banner capture failure now gets bounded retry/protective cleanup rather than a single capture error ending the detector. Protective loss-of-evidence cleanup also applies during the initial equip pass.

## Preserved behavior and interface

Dynamic numbered slots, slot 10's `0` key, ordered Dracula rotation, per-window manual fallback, catch-animation uncertainty, early countdown cleanup, safe slot 1 tools, disconnect handling, Daily Rewards closing, optional maintenance/rebirth, hotkeys, notifications and diagnostic exports remain available.

The UI keeps its Halloween orange/charcoal theme, rounded controls and restrained animations. Each window has a distinct current-action line separate from mutation progress. Unconfirmed, disconnected and absent states are explicit. Shared-event/visibility requirements are visible on the dashboard. Settings remain grouped and compatible; saved profiles are not added.

## Validation evidence

`run_tests.py` performs syntax checks and runs all 11 suites in separate subprocesses with a timeout. `RUN_TESTS.cmd` makes this accessible on Windows and finds an existing macro environment. It does not start the application bootstrap or send real Windows input. It writes `VALIDATION_3_5.log` and returns nonzero if any suite fails.

The suites cover:

1. Background scans, stale results, bounded queues, settings integrity, capture guards, popup markers and production event diagnostics.
2. Confirmed cleanup with dropped/delayed input, safe tools, hidden hotbars and slot 10.
3. Equip confirmation and smart candidate selection.
4. First-pass event dispatch, incomplete-window recovery and event priority.
5. Detector visual/OCR behavior, countdown consistency and successive events.
6. Fast transition timing and interruption of low-priority work.
7. Focus refusal, overlapping windows and reduced idle focus sweeps.
8. Real offscreen Qt navigation, persistence, controls, status, logs, previews and reduced motion at 1280×900 and 1000×700 logical pixels.
9. Input transactions, late toggles, selected tools and key-up release.
10. Preview/template reuse without caching game verdicts.
11. Disconnections, main-source failover and supplied Daily Rewards crop recognition.

Fixtures are real crops supplied with the project. Scaled/blurred variations extend those examples but are not a comprehensive dataset of game layouts. Inputs and Windows activation are simulated. Qt widgets, fixture processing and relevant Tesseract checks are real.

Two harness corrections were necessary. The moved-popup test now supplies its actual simulated moved rectangle to the new geometry guard; its click-position assertions remain. Older equip-only tests stub the new async dispatch boundary so they continue testing selection/confirmation in isolation. The new audit suite exercises the actual background scan orchestration, including pending, cancellation and stale-result behavior. Assertions were not weakened to accept wrong equipment states.

## Performance results and practical limits

`PERFORMANCE_3_5.log` records the 3.4.0/3.5.0 fixture comparison. Geometry, card type and selection matched on 32 variants. Median local snapshot processing across seven batches of 150 was 1.710 ms before and 1.766 ms after: a 3.2% increase from added inventory validation. This is an intentional correctness cost, not an image-processing speedup.

The improvement is scheduling: a missing plan cannot monopolize foreground input while OCR runs, and neither scan submissions nor UI work grow without limit. In the simulated 130 ms response model, four overlapping windows finish in 1.12 seconds for equip and 1.20 seconds for cleanup, with one visit each. Those inherited fast-path timings remain regression evidence, not newly measured live gains. The visual end detector remains below a second in local replay; see the exact results in the validation log. Historical benchmark files describe earlier releases and must not be added together into a whole-app speedup claim.

Exact artwork/label matching is deliberately conservative and can reject usable plans when artwork animates or text changes. That trades an occasional rescan for avoiding a stale target. Keep inventory arrangement stable: a hidden hotbar prevents validating any change, including a previously recognized replacement tool. An OS-accepted key and a visible selection still cannot prove server acceptance.

Windows foreground behavior, live game input acceptance, actual monitor scaling, clean-machine installation, the executable build, overnight resource use and mutation outcomes were not tested here. Repeated key-up rejection is surfaced rather than claimed fixed. The source remains partly monolithic, and capture/OCR remains dependent on the game's visible UI. These are limits, not guarantees concealed by passing simulated tests.

Follow the short Windows procedure in README.md before unattended use. For a failure, return the diagnostic export plus the event timestamp, affected window and fresh matching hotbar captures; distinguish input-sent from confirmed-state messages.
