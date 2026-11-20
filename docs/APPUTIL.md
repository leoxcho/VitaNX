# AppUtil native compatibility — 2026-11-10

`vitanx/apputil.py` is original host code integrated into the live native CPU
runner. Guest calls use exact library 48e01d74 and public VitaSDK NIDs. It adds no
firmware dependency and copies no Vita3K implementation. This is partial OS
compatibility for translated guest code; Python/Clang remain required by this
engineering runner, separate from standalone AOT packaging.

Implemented:

- Checked, nonoverlapping 64/40-byte zero-initialized init parameters; host-owned
  work storage, ordinary local boot attributes, explicitly configured boot version.
  Duplicate init returns busy. Every remaining implemented API requires init.
- Per-process lifecycle, RLock-protected state/event/save operations and explicit
  shutdown. Root descriptors close on both guest shutdown and runner cleanup.
- Configurable language, enter-button assignment, username, date/time formats,
  timezone, daylight savings, boot values and save quota. Defaults are a modeled
  English local device (UTC), not host or original Vita settings. Configure with
  `--apputil-config /path/config.json`; unknown/out-of-range values are rejected.
  Valid positive SAVEDATA_MAX_SIZE metadata supplies the quota unless overridden.
- Bounded 32-event queue, raw 1028-byte receives, no invented launch events.
  Invalid output leaves events queued. Empty queue is represented by zero type
  and payload; this local convention has not been verified against firmware.
- Default savedata mount: slot create/get/set/delete; 64KiB safe memory save/load;
  bounded file offset writes/truncation, directory create, file/empty-directory
  removal and quota queries. Fifth save argument is marshaled from the guest
  AAPCS stack, and 64-bit offsets keep their Vita alignment.
- All access is relative to held no-follow directory descriptors under this run's
  `native/saves`. AppUtil metadata uses `.vitanx-apputil`, including slots and safe
  memory. Relative paths and savedata0 paths are accepted; other devices, parent
  traversal and symlinked parents are rejected. app0 never becomes writable.
- Inputs and paths are prevalidated before a batch starts; each file replacement
  is atomic. Metadata/safe memory consume quota. A disk error halfway through a
  multi-file batch can leave earlier files committed; no transaction guarantee.

Limits: alternate mounts, recursive removal, parent directories created in the
same batch, slot search, event payload parsing, DRM/entitlements, media mounting,
background downloads and launch helpers remain unsupported. Unsupported NIDs trap;
no blanket success provider is installed. SceSysmodule reports the partial native
provider available, while AppUtil initialization itself is independently tracked.
An explicit plaintext provider for system module15 takes load precedence.

Boot field values and zero guest scratch are deliberate native model choices,
not recovered firmware values. Original `sceAppUtilInit` behavior is not available
from the inspected Vita3K implementation (currently UNIMPLEMENTED). The SDK
specifies layouts, zero initialization and errors, but not all edge behavior.

Saved CPU JSON checkpoints are diagnostic comparisons, not restorable process
snapshots: scheduler state, open files and guest heap/memory are not serialized.
Existing native regions are reused with exact source and ABI validation. Do not
restore CPU registers alone or claim that is continuing the original process.

Sources (reference only):
https://github.com/vitasdk/vita-headers/blob/master/include/psp2/apputil.h
https://github.com/vitasdk/vita-headers/blob/master/include/psp2/system_param.h
https://github.com/vitasdk/vita-headers/blob/master/db/360/SceAppUtil.yml
https://github.com/Vita3K/Vita3K/blob/master/vita3k/modules/SceAppUtil/SceAppUtil.cpp
https://github.com/ARM-software/abi-aa/blob/main/aapcs32/aapcs32.rst
