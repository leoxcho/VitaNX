# VitaNX (pre-alpha)

**License:** MIT for project-owned code (see [LICENSE](LICENSE) and [licensing notes](docs/LICENSING.md)). Contributions are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).

**Experimental PlayStation Vita ARMv7 → Apple Silicon macOS translation research.**
The goal is an NXNative-next-style *command-line converter* that produces standalone native macOS `.app` games. VitaNX is **not yet a working general-purpose commercial-game converter**. This source-only development snapshot does not contain Vita firmware, decryption keys, commercial executables, ROMs, saves or game assets.

## Current capabilities and limitations

- ELF inspection, limited ARM32/Thumb2 → native translation, native-code caching, and synthetic homebrew app packaging are implemented.
- Partial Vita module-loading, services, GXM/Metal, audio and controller interfaces exist. They are not a complete Vita environment.
- Automatic installed-game discovery is read-only. The actual commercial-game conversion and gameplay pipeline is unfinished.
- A synthetic standalone `.app` smoke test is **not** evidence of commercial gameplay compatibility.
- No Vita3K installation, firmware, games, credentials or private paths are bundled.

## Platform and prerequisites

Use Python 3.12+ and Apple command-line development tools on Apple Silicon macOS. Some offline source/tests can run elsewhere; Metal and native macOS execution require suitable Apple hardware.

```sh
./vitanx-launch doctor
./vitanx-launch inspect /path/to/authorized/arm32.elf
./vitanx-launch smoke builds/new-smoke
./vitanx-launch convert /path/to/authorized/arm32.elf builds/new-conversion
```

`convert` builds a limited prototype standalone application from an authorized plaintext homebrew ELF; it does not reproduce a complete commercial PlayStation Vita runtime.

For read-only Vita3K game discovery, specify your own local installation path (no author-specific path is assumed):

```sh
./vitanx-launch list-games --app-root '/path/to/your/vita3k/ux0/app'
# Or export VITANX_APP_ROOT='/path/to/your/vita3k/ux0/app'
```

Advanced experimental multi-module execution is described in `docs/ARCHITECTURE.md` and the code under `scripts/`. Inputs must be provided locally by the user; encrypted game content is not supported by the public frontend. Do not upload your game files, logs containing private paths, saves, or personally identifying metadata to GitHub issues.

## Privacy, attribution, and release status

- Read [PRIVACY.md](PRIVACY.md) before sharing issues or diagnostic logs.
- Run `python3 scripts/audit_public_release.py` before committing or publishing.
- See [docs/LICENSING.md](docs/LICENSING.md) and [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md). Inherited VitaXNative source was not supplied with a verified project-wide redistribution license; publication requires a rights review and license decision. **Do not publish this snapshot until that review is complete.**
- VitaNX is independent of and not endorsed by Sony or Vita3K. PlayStation and PlayStation Vita are trademarks of their respective owners.

**Status: public-source candidate, not yet approved for GitHub publishing, and not a playable commercial-game release.**
