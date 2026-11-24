# vitanx

Independent experimental Vita ARMv7 → C → Apple Silicon ARM64 recompiler.
This repository is separate from VitaXNative and NXNative-next. It does not
convert arbitrary commercial games and does not include decryption or keys.

Run with Python 3.12+ and Apple command line tools on Apple Silicon macOS:

```
./vitanx-launch doctor
./vitanx-launch inspect /absolute/path/to/authorized.elf
./vitanx-launch discover /absolute/path/to/explicit-directory
./vitanx-launch convert /absolute/path/to/authorized.elf builds/new-build
./vitanx-launch smoke builds/new-smoke
./vitanx-launch run-native /absolute/path/to/authorized.elf builds/new-execution
```

Conversion does not run the executable. `smoke` runs the bundled original
synthetic ABI fixture; `run-native` explicitly runs the supplied plaintext ELF
with bounded on-demand translation. Optional `--imports manifest.json` supplies
homebrew import bindings when module metadata is absent. Each output must be new. The smoke output contains a signed
standalone `.app`, generated C, embedded guest image, diagnostics and hashes.
This tests a fixed-address ARM ELF and Vita stdout ABI, not a full VitaSDK title.
A Finder window, graphics, sound, input and gameplay are not validated.

Run focused regressions:

```
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests python3 -m unittest -v test_vitanx test_elf_segments test_elf_dependencies test_self_parser test_self_extract test_vita_module test_recompiler test_indirect test_guest_context test_exclusive test_neon_fp test_packaging
```

See [architecture](docs/ARCHITECTURE.md), [inventory](docs/INVENTORY.md),
[licensing and provenance](docs/LICENSING.md), [status](docs/STATUS.md), and
[rollback](docs/ROLLBACK.md). Legacy `vitaxnative` is an internal compatibility
package retained so imported regressions remain unchanged. Its version string is
not vitanx's version. Source-project paths in historical notes are references,
not installation dependencies. The original launcher and recovery/decryption
workflows were deliberately not imported into the active tool.


Multi-module native execution (no application packaging):

```
python3 scripts/run_vita_modules.py /path/main.elf builds/new-module-run \
  --module /path/support.elf --heap-mib 256 --instruction-limit 50000
```

Use `--deferred /path/support.elf` for an explicitly authorized library to load
on first unresolved function call. Inputs must be plaintext ELF or explicitly
plaintext SELF. Encryption is rejected. `--diagnostic-unresolved` retains missing
functions as traps on reach; it does not invent service results. Module starts
run in the supplied order; support stops run in reverse order after normal return.
Guest SceSysmodule load/query calls are connected to explicit providers via
`--sysmodule 15=/path/authorized/plaintext-provider.elf`. The provider is mapped,
linked and initialized before success; missing providers return load errors.
Already initialized ULT/FiOS2 modules are tracked. Final unload remains unsupported
while mappings/imports are pinned. Full Vita Modulemgr syscalls remain incomplete.


AppUtil now has a bounded native compatibility provider, with initialization,
configuration, queued events and isolated save storage. See docs/APPUTIL.md for
supported APIs and model assumptions. `--apputil-config /path/config.json` selects
explicit local device settings. Unsupported functions still stop diagnostics.

Optional live media integration: add `--media` to `scripts/run_vita_modules.py`
to compile and connect the existing GXM/Metal, Core Audio and Cocoa/controller
bridges to the same guest memory and scheduler. This is a bounded compatibility
subset; it does not establish commercial frames or gameplay. See
[parallel workstreams](docs/PARALLEL_ENGINEERING.md) and [power policy](docs/POWER.md).
Summarize existing run evidence without a new launch:
`python3 scripts/compatibility_report.py builds/<run>/execution.json`.

## Interactive Terminal launcher

Run `vitanx` to open the interactive conversion menu.

Option 3 creates signed standalone ARM64 macOS applications.
The default output directory is
`~/Applications/PlayStation Vita Games/`.

Set the `VITANX_APP_ROOT` environment variable to configure
your installed Vita game library.

Encrypted titles require existing plaintext executables.

## Current development status

Standalone application packaging is functional. CPU translation,
Metal graphics, shader translation, audio and system service
compatibility remain under active development.

Commercial gameplay is not yet verified. Successful conversion
does not guarantee playable games.

Community contributions are welcome.
