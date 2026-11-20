# VitaNX engineering status — public snapshot 2026-11-20

**Status: experimental pre-alpha. Not a release of playable commercial Vita games.**

## Implemented or partially implemented

- ARMv7/Thumb-2 translation to native code, dynamic execution regions, and native cache reuse for reached code paths.
- Plaintext ELF inspection, homebrew conversion and synthetic native `.app` smoke tests.
- Partial Vita module loading, library-qualified imports, kernel memory services, power, screenshot, AppUtil and CommonDialog support.
- Partial GXM/Metal, display, audio, controller and touch adapters.
- Read-only Vita3K installed-title discovery with optional patch and DLC inventory.

## Not yet verified or implemented

- Playable commercial game execution or authentic rendered frames.
- Complete GXM queues, guest callbacks, shader translation and Metal presentation.
- Full Vita CPU, kernel, scheduler and system-call compatibility.
- Standalone commercial-game conversion through the same workflow as homebrew.
- Broad title compatibility, updates, DLC, gameplay saves and hardware testing.

User-owned games and executable inputs must be supplied locally; this repository does not contain firmware, games or decryption keys. Technical compatibility is incomplete and no per-title success claims are made.
