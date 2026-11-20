"""Exact-build patching into a new output; original executable is never changed.

This mechanism does not certify timing or visual correctness. No game enhancement
profiles ship with this project.
"""
import hashlib
import os
import re
from pathlib import Path


def apply_patch(source, destination, profile, *, title_id, version):
    source, destination = Path(source), Path(destination)
    if profile.get('title_id') != title_id or profile.get('version') != version:
        raise ValueError('patch title/version mismatch')
    if profile.get('kind') not in ('fps', 'resolution', 'compatibility'):
        raise ValueError('unsupported patch kind')
    expected = profile.get('input_sha256', '')
    if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
        raise ValueError('exact executable SHA-256 required')
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('patch executable fingerprint mismatch')
    edits = profile.get('edits')
    if not isinstance(edits, list) or not edits:
        raise ValueError('nonempty patch edits required')
    result = bytearray(data)
    occupied = set()
    for edit in edits:
        offset = edit.get('offset')
        if type(offset) is not int or offset < 0:
            raise ValueError('invalid patch offset')
        try:
            before = bytes.fromhex(edit['before'])
            after = bytes.fromhex(edit['after'])
        except (KeyError, TypeError, ValueError):
            raise ValueError('invalid patch byte signature') from None
        if not before or len(before) != len(after) or offset + len(before) > len(data):
            raise ValueError('patch extent invalid')
        extent = set(range(offset, offset + len(before)))
        if occupied & extent:
            raise ValueError('overlapping patch edits')
        occupied |= extent
        if data[offset:offset + len(before)] != before:
            raise ValueError('patch byte signature mismatch')
        result[offset:offset + len(before)] = after
    expected_output = profile.get('output_sha256')
    digest = hashlib.sha256(result).hexdigest()
    if digest != expected_output:
        raise ValueError('patched output fingerprint mismatch')
    # Exclusive creation rejects source aliases and preserves existing fallback.
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(result)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return {'output': str(destination), 'sha256': digest, 'edits_applied': len(edits),
            'enhancement_runtime_validated': False}
