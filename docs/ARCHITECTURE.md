# Architecture

1. Explicit discovery and structural preflight: ELF32 little-endian ARM, bounded
   segments; no implicit ROM scanning. CLI SELF input is refused. The imported
   plaintext SELF extractor is available internally and tested independently.
2. Vita loader: module metadata, imports/exports/NIDs and supported relocations.
   ModuleSession connects the inherited SCE relocation/NID loader to live execution through scripts/run_vita_modules.py.
3. Static translator first: decode reachable ARM/Thumb instructions into C,
   preserving guest addresses, register state, flags and memory checks. Clang
   compiles that C into a native ARM64 Mach-O. This is binary recompilation,
   not recovery of original source and not direct execution of ARMv7 on ARM64.
4. Runtime: bounded guest memory, Vita ABI imports, cooperative kernel, TLS,
   reservations and diagnostics. Unsupported imports/instructions/targets trap.
5. Graphics: experimental GXP/USSE → Metal and GXM services preserved internally.
   No commercial rendering integration is advertised by this frontend.
6. Packaging: standalone ad-hoc-signed app, embedded guest bytes, isolated saves
   under ~/Library/Application Support/vitanx/<input-hash>. No installation into
   Applications, Dock changes, original app replacement or source project hooks.

Live translation/runtime fallback:
`vitanx.dynamic.NativeSession` starts the statically reachable graph as signed
native code. At an unknown executable PC, an opt-in yield preserves the exact
CPU context, memory and shared write-generation monitor. The host extends the
translation graph with observed ARM/Thumb targets, compiles/loads native code,
and resumes that context through the existing cooperative kernel scheduler.
No entry replay or instruction skipping occurs. Misses do not retire instructions
or consume reservations. All graphs share one runtime instance and monitor.
The default AOT backend retains its previous -3 unknown-target behavior.

This is bounded on-demand recompilation, not an in-process machine-code emitter.
The module backend compiles separate native regions and switches to an existing
region on a return/cross-module branch. It does not rebuild the entire growing
graph at every miss. The ordinary single-input runner retains its compatibility
path. The module runner bounds decoded instructions per region (1,024, yielding at the frontier) and loaded
cold targets (128 by default, configurable); runtime instruction budgets apply across phases and threads.
Loaded native libraries remain alive for the session. Generated guest stores are
rejected before changing executable bytes; import writes to code are detected at
service return. Self-modifying code and guest exception vectors remain unsupported.

ModuleImage maps PT_LOAD segments, applies supported Vita relocations, binds exact
library/function NID pairs and validates variable links. Loader updates are
transactional before guest execution. Original images are not modified. Lazy
providers come only from explicitly supplied paths; stable trap markers identify
missing imports. A lazy initializer uses the calling thread with a saved CPU
frame, then restores its pending function call without replaying entry. Guest
memory changes persist. Relinking invalidates native-region selection so changed
stubs cannot retain stale host bindings. All loaded regions share one monitor,
scheduler, memory backing and compatibility runtime.

Host-managed starts/stops are explicit lifecycle phases; root thread exit is
cleared between successful phases while process exit stops further phases. Main
process TLS reserves 32 isolated 4 KiB thread slices (0x800-byte kernel prefix),
copies initialized bytes and zeroes the remainder. Support-module TLS and TLS
variable imports are rejected. Heap capacity is explicit and bounded, allowing
real libc's observed 128 MiB allocation with a 256 MiB diagnostic backing.

runtime-nids.json records exact public VitaSDK library/function IDs already
implemented locally, plus a narrowly recorded legacy thread-exit alias observed
in original SceLibc imports. It never falls back to function NID alone. Unknown
functions trap with module/library/NID context. A bounded import ring records
actual arguments and results for failures; it does not influence those results.
Complete guest-driven Modulemgr calls, general linking/relocation forms and
commercial graphics are still open. Python and Clang are still needed by the live
route; standalone application conversion remains the separate AOT pipeline.

Vita3K reference: its actual vita3k/CMakeLists.txt separates cpu, mem, module,
modules/NIDs, kernel/threads, io, gxm, renderer and shader. vitanx follows those
responsibility boundaries, while retaining static translation as its primary
execution strategy. No Vita3K implementation source was copied or linked.
https://github.com/Vita3K/Vita3K/blob/master/vita3k/CMakeLists.txt

NXNative-next reference: scripts/nxconvert_next.py provides explicit discovery
and validation; scripts/nxconvert_standalone.py provides inventory/copy verification
and portable bundle concepts. Switch NSO/Horizon/NVN code is incompatible with
Vita ARMv7/Vita OS/GXM and is not carried over. Frontend is newly written; existing
VitaXNative packaging is reused. No upstream code is fetched at runtime.

Additional Vita3K interfaces inspected (reference only):
- cpu/include/cpu/state.h separates thread identity, memory and CPU interface.
- kernel/include/kernel/state.h owns threads, TLS, module state and import bindings;
  it distinguishes library-qualified export keys to avoid function-NID collisions.
These support explicit context ownership and exact library+function import keys
for future integration. Do not collapse imports to function NID alone.
https://github.com/Vita3K/Vita3K/blob/master/vita3k/cpu/include/cpu/state.h
https://github.com/Vita3K/Vita3K/blob/master/vita3k/kernel/include/kernel/state.h

Guest SceSysmodule load/query calls use exact 03fcf19d-qualified NIDs. Explicit
`--sysmodule ID=/authorized/plaintext.elf` mappings can load, relocate, link and
initialize a provider on the calling guest thread, then return to its original
LR with success. Initialization is not replayed for repeated requests. Already
initialized SceUlt/FiOS2 providers are tracked by known module identity. Missing
providers return SDK fatal-load errors; query reports unloaded. Final unload is
explicitly unsupported while memory/imports are pinned and returns failure.
Initializer failures stop diagnostics; concurrent lazy initialization remains open.
There is no implicit firmware search or decryption.

Separate dynamic host-service markers permit adding runtime services while reusing
unchanged generated native regions. Cache reuse checks exact generated code and
guest/runtime ABI headers; runtime reuse additionally checks runtime source bytes.
The ARM AAPCS snprintf bridge reads r3/guest stack with 64-bit alignment and Vita
32-bit word sizes, stages bounded output, and traps unsupported formats before
writing. sceIoLseek marshals signed 64-bit offset/results in aligned register
pairs and uses existing read-only app0 descriptor rules. GPO/GPI are independently
modeled registers. Known CATEGORY=gd assets select the modeled GAME application
type; IsGameProgram boolean semantics are inferred from the actual FIOS consumer,
not validated against original firmware. Unknown metadata remains unsupported.

2026-11-10 AppUtil integration: qualified dynamic services now include a partial
native AppUtil provider with lifecycle/configuration/events and isolated save
operations (docs/APPUTIL.md). Configured plaintext AppUtil providers take
precedence and disable this fallback. CommonDialog configuration retains validated
settings without synthesizing any dialog or rendered frame. Native clib memory
operations check backing spans and executable write protection before mutation.

An optional developer boundary_handler runs inside the live dispatch callback
before an unresolved import unwinds the native scheduler. It can supply an
explicit provider, then retry the original call with all state retained. One
attempt per boundary prevents recursive no-progress resolution. The CLI accepts
--boundary-handler /path/resolver.py exporting resolve(session, import_info,
cpu_pointer). This is a same-process engineering hook, not a serializable save
state or a way to swap a live runtime library. CPU JSON alone is not resumable.
