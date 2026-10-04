#!/usr/bin/env python3
"""Explicit local data backup/preview/restore; never reads default personal paths."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.backup_bundle import (BackupError, create_bundle, registry_for_directory,
                                 validate_bundle, load_preview, restore)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Privat sikkerhetskopi og kontrollert gjenoppretting')
    commands = parser.add_subparsers(dest='command', required=True)
    backup = commands.add_parser('create', help='Lag en privat kopi av eksplisitt datamappe')
    backup.add_argument('--data-dir', required=True, type=Path)
    backup.add_argument('--archive', required=True, type=Path)
    backup.add_argument('--services-stopped', action='store_true', required=True)
    preview = commands.add_parser('preview', help='Valider kopi i en ny mellommappe')
    preview.add_argument('--archive', required=True, type=Path)
    preview.add_argument('--staging', required=True, type=Path)
    preview.add_argument('--destination', required=True, type=Path)
    apply = commands.add_parser('restore', help='Bruk nøyaktig den gjennomgåtte forhåndsvisningen')
    apply.add_argument('--staging', required=True, type=Path)
    apply.add_argument('--destination', required=True, type=Path)
    apply.add_argument('--review-token', required=True)
    apply.add_argument('--generation', required=True)
    apply.add_argument('--services-stopped', action='store_true', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'create':
            registry = registry_for_directory(args.data_dir)
            try:
                result = asyncio.run(create_bundle(registry, args.archive))
            finally:
                registry.close()
        elif args.command == 'preview':
            view = validate_bundle(args.archive, args.staging, args.destination)
            result = {'generation': view.generation, 'destination': str(view.destination),
                      'staging': str(view.staging_dir), 'schemas': dict(view.schema_versions),
                      'checksums': dict(view.checksums), 'warnings': view.warnings,
                      'review_token': view.review_token}
        else:
            view = load_preview(args.staging, expected_review_token=args.review_token)
            if view.generation != args.generation:
                raise BackupError('generation_mismatch')
            result = restore(view, args.destination, services_stopped=args.services_stopped)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (BackupError, OSError) as error:
        code = str(error) if isinstance(error, BackupError) else 'filesystem_error'
        print('Operasjonen ble avvist: ' + code, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
