# Contributing

VitaNX is experimental pre-alpha research. Contributions should be small, testable, and focused on verifiable Vita hardware or API semantics. Do not invent successful emulator responses to bypass guest errors.

Before submitting changes:

1. Use synthetic, independently authored homebrew/ARM fixtures instead of copyrighted game binaries.
2. Run `python3 scripts/audit_public_release.py` and the relevant focused tests.
3. Inspect every changed file for home paths, usernames, tokens, licenses, firmware, games, saves and hardware identifiers.
4. Avoid submitting execution logs, screenshots, or crash reports with private data.
5. Include attribution for any third-party code and confirm its license allows redistribution.

New contributions should include tests and documentation of what has and has not been validated on Apple Silicon. See `PRIVACY.md` and `docs/LICENSING.md`.
