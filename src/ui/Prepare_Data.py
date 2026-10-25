#Prepares database
import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from Input_Validation import load_config, read_preferences, save_preferences
from Inventory_Database import open_db, validate_inventory, columns, prepare


def copy_data(source_config, destination_config):
    source_config = Path(source_config).expanduser().resolve()
    destination_config = Path(destination_config).expanduser().resolve()
    if source_config == destination_config:
        raise ValueError('Use a separate new project folder. Do not import onto the source.')
    settings = load_config(source_config)
    folder = destination_config.parent / 'data'
    names = {'catalog': 'catalog.sqlite', 'products': 'barcodes.db',
             'inventory': 'Inventory.db', 'manual': 'touch_manual.sqlite'}
    needed = ['catalog', 'products', 'inventory']
    if settings['manual'].is_file():
        needed.append('manual')
    for key in needed:
        if not settings[key].is_file():
            raise FileNotFoundError(str(settings[key]))
        if (folder / names[key]).exists():
            raise FileExistsError(f'Keep the existing file: {folder / names[key]}.')
    old_preferences = source_config.parent / 'pantry_preferences.json'
    preferences = read_preferences(old_preferences) if old_preferences.is_file() else None
    defaults = Path(__file__).resolve().parent / 'config.pi.json'
    template = destination_config if destination_config.is_file() else defaults
    config = json.loads(template.read_text(encoding='utf-8-sig'))
    source_options = json.loads(source_config.read_text(encoding='utf-8-sig'))
    if 'serial' in source_options:
        config['serial'] = source_options['serial']
    config['hardware_review'] = {key: False for key in config.get('hardware_review', {})}
    folder.mkdir(parents=True, exist_ok=True)
    for key in needed:
        print('Copying:', settings[key], flush=True)
        destination = folder / names[key]
        destination.touch(exist_ok=False)
        try:
            with closing(open_db(settings[key])) as source:
                with closing(sqlite3.connect(destination)) as target:
                    source.backup(target)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
    for key in ('catalog', 'products', 'inventory'):
        config[key] = 'data/' + names[key]
    from Calibration_Storage import write_json
    write_json(destination_config, config)
    if preferences is not None:
        save_preferences(destination_config.parent / 'pantry_preferences.json', preferences)
        print('Copied display.')
    print('Original databases are unchanged.')


def main():
    #if copying, had to copy a lot during the builds
    parser = argparse.ArgumentParser(description='Copies data and adds inventory dates')
    parser.add_argument('--config', default=str(Path(__file__).resolve().parent / 'config.pi.json'))
    parser.add_argument('--copy-from', help='Working project configuration file')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.copy_from:
        if not args.apply:
            print('Close application and DB Browser.')
            return
        copy_data(args.copy_from, args.config)
    settings = load_config(args.config)
    for key in ('catalog', 'products', 'inventory'):
        print(key + ': ' + str(settings[key]))
    with closing(open_db(settings['inventory'])) as connection:
        validate_inventory(connection, dates=False)
        missing = {'purchased_on', 'expires_on'} - columns(connection, 'inventory_items')
    if not args.apply:
        print('Date columns to add:', sorted(missing))
        print('Run with --apply to back up and prepare copy.')
        return
    backup = prepare(settings)
    print('Backup:', backup or 'Dates present.')
    print('Ready.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit('Setup stopped: ' + str(error))
