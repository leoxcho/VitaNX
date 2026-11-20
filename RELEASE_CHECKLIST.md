# Public release checklist — publication preflight

- [x] Produce a separate source copy; do not modify the user's working VitaNX installation.
- [x] Exclude local build directories, game dumps, save data, private caches, and internal session notes.
- [x] Remove hard-coded developer volumes and account/home paths; make Vita3K inventory path configurable.
- [x] Sanitize provenance source paths while retaining filename mapping and hashes.
- [x] Add privacy-first `.gitignore` and an offline file/content audit.
- [x] Label runtime and commercial-game limitations accurately (pre-alpha).
- [x] Project owner confirmed VitaXNative source ownership.
- [x] Exclude all precompiled ELF/bin fixtures pending provenance verification; remaining third-party notices still require review.
- [x] Project owner approved MIT for code they control; LICENSE added, retaining third-party notices.
- [ ] Verify README and status statements against the final source and run final tests on Apple Silicon.
- [ ] Create a fresh Git repository from this sanitized folder (do not copy the original `.git/` history).
- [ ] Configure and verify an intentional public Git author name and no-reply email before committing.
- [ ] Review the final staged Git diff and commit metadata, and scan for additional secrets with an external tool if available.
- [ ] Explicitly approve publication and choose a repository name/version before pushing to GitHub.

Do not publish, create a GitHub Release, or tag a stable version until all blocking items are completed. A public *source candidate* is not a working commercial Vita game converter.
