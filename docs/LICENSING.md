# Licensing and provenance

Vita3K is GPLv2. Its README, COPYING.txt and architectural build file were reviewed:
https://github.com/Vita3K/Vita3K
https://github.com/Vita3K/Vita3K/blob/master/COPYING.txt
https://github.com/Vita3K/Vita3K/blob/master/vita3k/CMakeLists.txt

No Vita3K implementation, third-party proprietary source, firmware, game asset,
ROM, key or save was imported. Referencing architecture does not establish a
license grant for copied implementation. If Vita3K code is integrated later,
record the exact upstream revision/path, retain copyright/license notices, mark
modifications, include GPLv2 text and comply with corresponding-source and
redistribution obligations for the combined derivative work. Review dependency
licenses individually; do not assume every upstream file has identical terms.

NXNative-next is MIT licensed; the complete license is retained in
NXNATIVE_MIT_LICENSE.txt. Its implementation is reference-only in this milestone.

VitaXNative is the user's existing local source, reused under the user's explicit
instruction for this private project. No top-level license was found in the
inspected root. Existing per-file notices remain intact. This import is not a
claim that all legacy code can be relicensed or publicly redistributed. Audit
legacy provenance and choose a compatible project-wide license before publishing.
No public release or blanket relicensing was performed. The plaintext synthetic
fixture's own manifest records its original homebrew provenance.

provenance.json records exact imported paths/hashes and reference-only files.
vitaxnative/build.py is modified to isolate saves and default bundle identity.
vitaxnative/__main__.py retains only legacy manifest-validation helpers and
delegates execution to the new CLI. Dated notices mark these modifications.
New vitanx frontend/cache/tests/docs are independently written for this project.

2026-11-09 live-execution changes: recompiler.py adds opt-in miss yields, shared
monitor linkage and executable-store guards. New runtime/vitanx_dynamic.c and
vitanx/dynamic.py implement native context resumption and runtime ownership.
No new upstream implementation or proprietary code was imported.

Multi-module milestone: ModuleImage/ModuleSession are new orchestration around
existing user-provided commercial_loader.py, which is unchanged. Public Vita3K
load_self.cpp and VitaSDK modulemgr/processmgr interfaces were consulted for
behavior and architecture only. No implementation text was copied. The runtime
NID registry records factual numeric ABI identifiers, source URLs and SHA256s;
update_runtime_nids.py matches only APIs already implemented locally. The legacy
thread-exit library alias is separately marked rather than using unqualified NIDs.
References:
https://github.com/Vita3K/Vita3K/blob/master/vita3k/kernel/src/load_self.cpp
https://github.com/vitasdk/vita-headers/blob/master/include/psp2/kernel/modulemgr.h
https://github.com/vitasdk/vita-headers/blob/master/include/psp2/kernel/processmgr.h

Further independent runtime additions: DebugLed numeric ABI/docs, ARM AAPCS32
variadic calling rules, VitaSDK snprintf/IO interfaces and SceSysmodule IDs/error
contracts were consulted. Vita3K SceSysmodule.cpp was reference-only (GPLv2+); no
implementation copied or linked. System-module availability is based on actual
configured providers, not Vita3K's optional unconditional HLE registration.
https://docs.vitasdk.org/group__SceDebugLedUser.html
https://github.com/ARM-software/abi-aa/blob/main/aapcs32/aapcs32.rst
https://github.com/vitasdk/vita-headers/blob/master/include/psp2/kernel/clib.h
https://github.com/vitasdk/vita-headers/blob/master/include/psp2/io/fcntl.h
https://github.com/vitasdk/vita-headers/blob/master/include/psp2/sysmodule.h
https://github.com/Vita3K/Vita3K/blob/master/vita3k/modules/SceSysmodule/SceSysmodule.cpp

2026-11-10: vitanx/apputil.py and runtime/vitanx_memory.c are original host
implementations based on VitaSDK API layouts/numeric identifiers, standard memory
semantics and explicit local device settings. The inspected Vita3K AppUtil code
was reference only; no implementation copied. Its GPLv2+ init is unimplemented.
Source interfaces and model assumptions are listed in docs/APPUTIL.md. No claim
of original firmware behavior or permission to redistribute commercial inputs.
CommonDialog configuration is also original host code, based on public VitaSDK
common_dialog.h layouts/errors/default sentinels; the inspected Vita3K setter is
unimplemented. Power was researched but no implementation or success stub added.
