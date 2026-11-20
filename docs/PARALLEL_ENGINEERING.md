# Parallel engineering — 2026-11-10

All new work belongs in vitanx. Original ROMs, VitaXNative, NXNative and existing
applications remain read-only. `checkpoints/apputil-core-20261110.tar.gz` is retained;
`pre-parallel-media-20261110.tar.gz` captures the baseline before media integration.
Archives must be extracted into a new directory rather than over existing work.

| Stream | Owned modules | Interface and current boundary |
| --- | --- | --- |
| CPU | recompiler, fallback, dynamic guest state | Shared GuestState and runtime ABI; code writes trap before host-service yields. Exceptions and self-modifying execution remain unsupported. |
| OS | modules, apputil, common_dialog, power | Exact library/function import keys; power requests are virtual policy hints. Unknown imports trap. |
| Graphics | graphics.py, vita_gxm, vita_metal, vita_display | Optional media build; guest addresses resolve against the same memory backing. Exact GXP catalog matching; unsupported shaders fail. |
| Audio | vita_audio | AudioQueue PCM buffers, bounded guest spans and cooperative scheduler waits. Physical output needs separate observation. |
| Input | vita_window, vita_input | Cocoa/GameController state, physical-key aggregation, guest controller/touch layouts. |
| Integration | modules.py, run_vita_modules.py | `--media` opts into existing backends. Module lifecycle and original executable share runtime, memory and scheduler. |
| Automation | cli, diagnostics, compatibility_report.py | Existing conversion/packaging retained; read existing execution evidence without another launch. Live translation still needs Python/Clang. |

A runtime build manifest and exact source/catalog bytes determine media runtime
cache reuse; unchanged guest ABI permits native region reuse. Media imports use
the VFP-aware bridge, retaining scalar floating arguments. Media backends remain
disabled by default and devices open only when required by guest calls.

Independent tests should precede integration; one bounded original-game run then
checks the combined change. Additional dispatches are execution evidence, not
rendering, audible output or interactive gameplay. Continue the independent media
fixtures even when an unrelated commercial OS call stops execution.

Each media CLI session currently owns one backend instance. Loading multiple
media dylibs in a single Python process produces duplicate Objective-C class
registration warnings; concurrent application sessions should use separate
processes until backend classes have process-wide ownership.
