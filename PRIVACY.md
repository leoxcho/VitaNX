# Privacy and security for contributors

This project never needs your personal files, games, account credentials, private dumps, or saves to file an issue or run the supplied synthetic regressions.

**Do not commit or attach:** `ux0/app`, `ux0/patch`, `ux0/addcont`, game executables/dumps, firmware, BIOS, `.rif` license files, decryption keys, signing certificates, account tokens, save data, native translation caches, build output, terminal transcripts, or diagnostics with absolute home paths. Do not upload gameplay screenshots containing usernames, account IDs, or system notifications without redacting them.

When reporting problems, include only source-level reproductions or synthetic homebrew fixtures. Logs may reveal user, host, volume labels, mounted drives, process arguments, or installed-game titles. Review/redact them locally before posting.

The privacy scan checks common mistakes but cannot guarantee that every piece of personal data has been found. Inspect the full Git diff and `git log --all --stat` before publication. The source archive has no `.git` history, so a historical leak cannot be ruled out for an existing repository.

If a secret is committed, deleting a working-tree file or adding `.gitignore` is insufficient: revoke/rotate the secret and remove the affected Git history before publishing. Never publish a working-copy clone with unknown history; create a new repository from the audited source candidate instead.

## GitHub identity and commit history

Public commits disclose the configured author name/email and may link to your GitHub account. Before the first commit, set the intended public author identity and a GitHub-provided no-reply email for **this new repository only**. Review your GitHub profile privacy settings and the email metadata in `git log --format=fuller`; changing the account setting does not scrub an old commit. Do not initialize the public repository by copying the existing private `.git/` directory.

A public repository's owner name and activity are visible by design. Code sanitization does not make a GitHub account anonymous.
