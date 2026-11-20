# Modified for vitanx 2026-11-09: legacy manifest helpers only; delegate CLI.
def _manifest_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result and result[key] != value:
            raise ValueError(f'conflicting duplicate manifest key: {key}')
        result[key] = value
    return result

def _manifest_imports(mapping):
    result = {}
    for key, value in mapping.items():
        address = int(key, 0) if key.startswith('0x') else int(key)
        if address in result and result[address] != value:
            raise ValueError(f'conflicting duplicate explicit import at {address:#010x}')
        result[address] = value
    return result


if __name__ == "__main__":
    from vitanx.cli import main
    raise SystemExit(main())
