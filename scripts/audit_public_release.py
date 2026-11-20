#!/usr/bin/env python3
"""Read-only privacy gate for the source-only VitaNX public candidate.

Not a substitute for license review, secret rotation, or Git-history inspection.
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
MAX_SOURCE_BYTES = 3_000_000
ALLOWED_BINARY = set()
PRIVATE_DIRS = {'builds', 'work', 'evidence', 'checkpoints', '.git', '.venv', 'venv', '__pycache__', 'outputs'}
PRIVATE_SUFFIXES = {'.pkg', '.vpk', '.self', '.rif', '.nsp', '.xci', '.nca', '.tik', '.pem', '.p12', '.p8', '.key', '.keystore', '.dylib', '.db', '.sqlite', '.sfo', '.psarc', '.skprx', '.suprx'}
# Split sensitive path literals so this script doesn't flag itself when audited.
SOURCE_PATTERNS = [
    ('home-path', re.compile(r'/(?:V[o]lumes|Users)/[A-Za-z0-9_.\ -]+(?:/[A-Za-z0-9_.\ -]+)*')),
    ('container-path', re.compile(r'/m[n]t/data/')),
    ('email', re.compile(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', re.I)),
    ('credential', re.compile(r'(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})')),
    ('private-key', re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----')),
]

def audit(root=ROOT):
    findings = []
    count = 0
    for path in sorted(root.rglob('*')):
        rel = path.relative_to(root)
        # A Git checkout always contains .git metadata. Source privacy is audited
        # here; historical commit disclosure must be reviewed separately.
        if '.git' in rel.parts:
            continue
        name = rel.as_posix()
        if path.is_symlink():
            findings.append((name, 'symlink forbidden'))
            continue
        if not path.is_file():
            continue
        count += 1
        if any(x in PRIVATE_DIRS for x in rel.parts):
            findings.append((name, 'private/generated directory'))
        if path.name == '.DS_Store' or path.name.startswith('._') or path.name.startswith('.env'):
            findings.append((name, 'private metadata/config file'))
        if path.suffix.lower() in PRIVATE_SUFFIXES:
            findings.append((name, 'disallowed file type'))
        if path.suffix.lower() in {'.elf', '.bin'} and name not in ALLOWED_BINARY:
            findings.append((name, 'unapproved binary'))
        raw = path.read_bytes()
        if len(raw) > MAX_SOURCE_BYTES:
            findings.append((name, 'oversized source file'))
            continue
        if b'\0' in raw and name not in ALLOWED_BINARY:
            findings.append((name, 'unexpected binary content'))
            continue
        try:
            content = raw.decode('utf-8')
        except UnicodeDecodeError:
            if name not in ALLOWED_BINARY:
                findings.append((name, 'non-UTF8 content'))
            continue
        for label, pattern in SOURCE_PATTERNS:
            if pattern.search(content):
                findings.append((name, label))
    return count, findings

if __name__ == '__main__':
    n, issues = audit()
    for file, reason in issues:
        print(f'BLOCK: {file}: {reason}')
    print(f'Files checked: {n}; privacy flags: {len(issues)}')
    sys.exit(bool(issues))
