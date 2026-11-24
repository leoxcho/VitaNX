"""Terminal launcher for installed Vita applications."""

from pathlib import Path
import plistlib
import subprocess

from .installed_games import DEFAULT_APP_ROOT, list_installed_games

DEFAULT_OUTPUT = Path.home() / 'Applications' / 'PlayStation Vita Games'


def display(value):
    """Keep metadata and filenames from injecting terminal control characters."""
    return ''.join(c if c.isprintable() else ' ' for c in str(value))


def choose_directory(current):
    value = input(f'Output directory [{current}] (Enter keeps current): ').strip()
    if not value:
        return current
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        print('Please enter an absolute path or a path beginning with ~/.')
        return current
    candidate = candidate.resolve()
    ux0 = DEFAULT_APP_ROOT.parent.resolve()
    if candidate == ux0 or candidate.is_relative_to(ux0):
        print('Output must be outside the original Vita3K ux0 directory.')
        return current
    if candidate.exists() and not candidate.is_dir():
        print('That destination is not a directory.')
        return current
    return candidate


def browse(output, action="reveal"):
    """Look only at apps directly in the chosen destination or a build folder."""
    if not output.is_dir():
        print(f'No converted applications in {display(output)}.')
        return
    apps = []
    for child in output.iterdir():
        if child.is_symlink() or not child.is_dir():
            continue
        if child.suffix == '.app':
            apps.append(child)
        else:
            apps.extend(p for p in child.glob('*.app') if p.is_dir() and not p.is_symlink())
    apps.sort(key=lambda p: p.name.casefold())
    if not apps:
        print(f'No converted applications in {display(output)}.')
        return
    for number, app in enumerate(apps, 1):
        name = app.stem
        try:
            with (app / 'Contents' / 'Info.plist').open('rb') as stream:
                info = plistlib.load(stream)
            name = info.get('CFBundleDisplayName') or info.get('CFBundleName') or name
        except (OSError, ValueError, plistlib.InvalidFileException):
            pass
        print(f'{number:3}. {display(name)} {display(app)}')
    value = input('Select application (0 cancels): ').strip()
    if value.isdecimal() and 1 <= int(value) <= len(apps):
        app = apps[int(value) - 1]
        if action == 'launch':
            result = subprocess.run(['open', str(app)], check=False)
            if result.returncode:
                print(f'Launch failed (exit {result.returncode}).')
        elif action == 'details':
            print(f'Application: {display(app.stem)}')
            print(f'Path: {display(app)}')
            print(f'Bundle metadata: {display(app / "Contents/Info.plist")}')
            print('Conversion and gameplay status: not verified by the launcher.')
        else:
            subprocess.run(['open', '-R', str(app)], check=False)
    elif value and value != '0':
        print('Invalid application number.')


def create_standalone(game, output, include_extras):
    from .bundle import build_installed
    from vitaxnative.self_extract import EncryptedSelfError

    try:
        try:
            target = build_installed(game, output, include_extras=include_extras)
        except EncryptedSelfError:
            cache = (Path.home()/'Library/Application Support/Vita3K/Vita3K/cache/decrypted_selfs'
                     /game['title_id'])
            has_update = include_extras and game['patch_path']
            default = cache if not has_update and (cache/'eboot.bin').is_file() else None
            suffix = f' [{display(default)}]' if default else ''
            value = input(f'Plaintext executable directory for the selected version{suffix}: ').strip()
            directory = Path(value).expanduser() if value else default
            if directory is None:
                print('Build cancelled.')
                return
            target = build_installed(game, output, include_extras=include_extras, plaintext=directory)
    except (OSError, ValueError, RuntimeError) as error:
        print(f'Build failed: {display(error)}')
        return
    print(f'Created {display(target)}')


def selected_game(game, output):
    include_extras = True
    while True:
        print(f'\n{display(game["title_id"])} {display(game["title"])}')
        print(f'{display(game["title_id"])} v{display(game.get("version") or "unknown")} <- {display(game["game_path"])}')
        if game.get('patch_path'):
            state = 'selected' if include_extras else 'excluded (base only)'
            print(f'Update v{display(game.get("patch_version") or "unknown")} <- {display(game["patch_path"])} [{state}]')
        else:
            print('Update: none detected')
        for content_id in game['dlc_content_ids']:
            state = 'selected' if include_extras else 'excluded (base only)'
            path = DEFAULT_APP_ROOT.parent / 'addcont' / game['title_id'] / content_id
            print(f'DLC {display(content_id)} <- {display(path)} [{state}]')
        if not game['dlc_content_ids']:
            print('DLC: none detected')
        for key in ('base_metadata_error', 'patch_metadata_error'):
            if game.get(key):
                print(f'Metadata warning: {display(game[key])}')
        print(f'Output: {display(output)}')
        print('1. Build for macOS')
        print('2. Change output destination')
        print('3. ' + ('Use base game only' if include_extras else 'Include detected update and DLC'))
        print('0. Back to game list')
        choice = input('Select action (0 cancels): ').strip().casefold()
        if choice in ('0', 'b', 'q'):
            return output
        if choice in ('2', 'o'):
            output = choose_directory(output)
        elif choice == '3':
            include_extras = not include_extras
        elif choice in ('1', 'c'):
            if input('Build for macOS? (y/N): ').strip().lower() == 'y':
                create_standalone(game, output, include_extras)
            else:
                print('Build cancelled.')
        else:
            print('Invalid selection')


def game_library(output, action):
    query = ''
    games = []
    refresh = True
    try:
        while True:
            if refresh:
                try:
                    games = list_installed_games(DEFAULT_APP_ROOT)['games']
                except (OSError, ValueError) as error:
                    games = []
                    print(f'Library unavailable: {display(error)}')
                games.sort(key=lambda g: (str(g['title']).casefold(), g['title_id']))
                refresh = False
            visible = [g for g in games if query.casefold() in
                       f'{g["title"]} {g["title_id"]}'.casefold()]
            print(f'\nLibrary: {DEFAULT_APP_ROOT}')
            print(f'Output: {display(output)}')
            if query:
                print(f'Search: {display(query)}')
            for number, game in enumerate(visible, 1):
                patch = f'patch {game.get("patch_version") or "detected"}' if game['patch_path'] else 'no patch'
                print(f'{number:3}. {display(game["title_id"])} {display(game["title"])} '
                      f'— {display(patch)}, {game["dlc_count"]} DLC')
            print(f'\nLibrary: {len(visible)} of {len(games)} base-game entries')
            if not visible:
                print('No matching games.')
            print('S. Search   A. All games   R. Refresh   O. Output directory')
            print('0. Back to main menu')
            choice = input('Select game (0 cancels): ').strip().casefold()
            if choice in ('0', 'q'):
                return output
            if choice == 's':
                query = input('Search title or ID (Enter clears): ').strip()
            elif choice.startswith('/'):
                query = choice[1:]
            elif choice == 'a':
                query = ''
            elif choice == 'r':
                refresh = True
            elif choice == 'o':
                output = choose_directory(output)
            elif choice == 'b':
                browse(output)
            elif choice.isdecimal() and 1 <= int(choice) <= len(visible):
                game = visible[int(choice) - 1]
                if action == 'status':
                    print(f'Game: {display(game["title"])} [{display(game["title_id"])}]')
                    print(f'Version: {display(game.get("version") or "unknown")}')
                    print(f'Patch: {display(game.get("patch_path") or "none")}')
                    print(f'DLC: {game["dlc_count"]}')
                    print('Standalone conversion is available from option 3. Gameplay is unverified.')
                else:
                    output = selected_game(game, output)
                return output
            else:
                print('Invalid selection')
    except (EOFError, KeyboardInterrupt):
        raise
    except OSError as error:
        print(f'Launcher error: {display(error)}')
        return output


MAIN_MENU = """VitaNX

1. Build New Game
2. Launch Existing Game
3. Create Standalone Application (default)
4. Rebuild Existing Game
5. View Game Status
6. Update Standalone Application
7. Open Application in Finder
8. Exit
9. Create Lightweight Application
10. View Application Details"""


def interactive_menu():
    output = DEFAULT_OUTPUT
    try:
        while True:
            print(MAIN_MENU)
            choice = input('Select option [3]: ').strip() or '3'
            if choice == '8':
                return 0
            try:
                if choice in ('1', '3'):
                    output = game_library(output, 'build')
                elif choice == '2':
                    browse(output, 'launch')
                elif choice == '4':
                    print('Rebuild unavailable: installed-game standalone build/rebuild is not implemented. Existing builds are preserved.')
                elif choice == '5':
                    output = game_library(output, 'status')
                elif choice == '6':
                    print('Update unavailable: standalone application updates are not implemented. Existing applications are preserved.')
                elif choice == '7':
                    browse(output)
                elif choice == '9':
                    print('Lightweight application creation is not implemented. No application was generated.')
                elif choice == '10':
                    browse(output, 'details')
                else:
                    print('Invalid selection')
            except (OSError, ValueError) as error:
                print(f'Launcher error: {display(error)}')
            print()
    except (EOFError, KeyboardInterrupt):
        print('\nVitaNX menu closed.')
        return 0
