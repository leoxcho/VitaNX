# Live native execution milestone — 2026-11-09

Implemented live indirect-target translation with persistent guest state and one
shared compatibility runtime. Default AOT behavior remains unchanged.

The newly assembled, stripped plaintext ARMv7/Thumb-2 executable in
fixtures/dynamic/interwork.S executes an ARM→Thumb function-pointer call, an IT
conditional instruction and ADD.W, returns to ARM, preserves raw VFP register
payloads and FPSCR, completes LDREX/STREX across the translation boundary, updates
guest data 41→42, restores the stack, calls the Vita stdout ABI and returns 42.
Evidence: evidence/live-translation/interwork-execution.json and interwork.elf.
Result: status 0; 33 guest dispatches (IT and its controlled instruction are fused
by the existing translator), one service call, one miss at tagged PC 0x10055
after nine dispatches; stdout “vitanx live translation”. This is original synthetic
homebrew assembly, not a retail game or evidence of commercial compatibility.

Validation: four new targeted execution scenarios plus two affected default-AOT
checks passed (evidence/dynamic-tests.log). The extended ABI/FP-state case then
passed separately (dynamic-abi-test.log), and the process-wide instruction-budget
change passed its affected scenario (dynamic-budget-test.log). No full-suite,
packaging, GPU, commercial startup or existing game launch was repeated.
Original repositories, ROMs, apps and saves were not changed. Earlier rollback
checkpoint is untouched; work/*.before-live-fallback.py retain local pre-edit
translator/cache sources. No commit or publication.

Remaining: no new unsupported-opcode implementation is provided by this fallback;
unsupported decoding still stops. Live execution is a single bounded ELF graph,
not general relocated multi-module loading. Arbitrary thread-entry discovery,
self-modifying code, guest exception vectors and commercial graphics remain open.
The live route currently needs Python/Clang and is not embedded in standalone apps.

Next blocker: integrate the existing Vita module loader's relocation and exact
library+function NID bindings into live memory and dispatch, so support-library
code can execute in the same address space without synthetic address hooks.

---

# Earlier preserved milestone

# Status — 2026-11-09

Completed milestone: independent plaintext static-recompilation foundation.

- Exact NXNative-next checkout located and inspected; Vita3K source architecture
  and license reviewed; VitaXNative current source, tests and checkpoint inspected.
- Copied translator/loaders/runtime/graphics experiments and regression sources.
  No dependency on installed VitaXNative/NXNative code at execution time.
- New explicit CLI: doctor, inspect, one-directory discover, convert, smoke.
- Original synthetic plaintext ARM ELF translated into C and compiled/signed as
  a standalone ARM64 macOS app. Seven guest instructions statically translated;
  expected stdout and return value 46 verified; host exit 0.
- codesign --verify --strict passes; file confirms thin ARM64 Mach-O; otool shows
  only /usr/lib/libSystem.B.dylib. Smoke app embeds guest bytes, no original paths
  required. No Finder/GUI/gameplay claim.
- 99 focused tests: 97 passed, 2 skipped, no failures/errors. Skips require official
  VitaSDK GCC/vita-elf-create. Includes native instruction/indirect/context,
  exclusive-memory and NEON FP tests, ELF/SELF/module validation, packaging and
  signed standalone/no-overwrite test. evidence/regressions.log is final.
- An initial run exposed a missing legacy manifest-helper import; compatibility
  helpers were retained without restoring the old CLI. Initial failed log is
  retained, and final rerun passes.
- 3,770 selected original source/document hashes unchanged in three source trees.
  ROMs, saves, game apps and original checkpoints were not modified or launched.

Remaining work:
- Live dynamic translation fallback/JIT is not implemented. The bounded on-demand
  translation cache is tested, including native execution of returned code, but
  is not connected to guest resumption. Unknown targets trap rather than replay.
- Commercial module initialization, full import/service coverage, native game
  rendering/audio/input, complete Vita OS and general compatibility remain open.
- Graphics/USSE/GXM experiments are preserved, not newly GPU-verified here.
- CLI accepts authorized plaintext ELF only; no decryptor or license keys included.
- Legacy source licensing requires a provenance audit before public redistribution.
  No Vita3K implementation copied; no source publication or Git commit requested.

Next engineering step: implement dispatcher-to-cached-native-block resumption
with exact shared context/FP/exclusive-monitor/thread state and executable-memory
validation; first prove a synthetic indirect ARM↔Thumb transition with no restart.
Then broaden supported original VitaSDK fixtures before considering commercial
initialization. Keep original checkpoints and games untouched.

2026-11-10 parallel integration: optional live media backends connected; power
policy request retained;409002 Gravity Rush dispatches,737/738 regions reused.
Next exact import: SceScreenShot f26fc97d/76e674d1. Zero scenes, frames or audio
buffers; no commercial gameplay verification. See RESUME_NEXT_SESSION.md.
