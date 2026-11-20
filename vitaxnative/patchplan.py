"""Deterministic, read-only selection of version-specific Vita enhancement patches."""
from pathlib import Path
from .analysis import analyze, load_patch_registry


def plan(game: Path, registry: Path) -> dict:
    info = analyze(game)
    database = load_patch_registry(registry)
    selected, candidates, rejected = [], [], []
    for patch in database['patches']:
        if patch['title_id'] != info['title_id'] or patch['version'] != info['version']:
            continue
        # A registry label alone cannot prove that executable bytes match.
        if patch['status'] == 'validated':
            selected.append(patch)
        elif patch['status'] == 'candidate':
            candidates.append(patch)
        else:
            rejected.append(patch)
    return {
        'game': info['path'], 'title': info['title'], 'title_id': info['title_id'],
        'version': info['version'], 'validated_registry_matches': selected,
        'candidate_matches': candidates, 'rejected_matches': rejected,
        'patches_applied': 0, 'fps_unlocked': False, 'resolution_enhanced': False,
        'note': 'Read-only planning. Registry matches are NOT binary-verified or applied. '
                'A future backend must verify executable hashes and patch signatures before modification.'
    }
