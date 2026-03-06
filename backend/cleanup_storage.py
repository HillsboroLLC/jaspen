#!/usr/bin/env python3
"""
One-time cleanup script for polluted session/scenario storage files.

Usage:
    # Dry run — list what would be deleted, no changes
    python cleanup_storage.py

    # Actually delete all storage files
    python cleanup_storage.py --confirm

    # Delete only a specific user's data
    python cleanup_storage.py --user <user_id> --confirm

    # List all user IDs with stored data
    python cleanup_storage.py --list-users

Run from the backend/ directory (same working directory as wsgi.py).
"""

import argparse
import glob
import json
import os
import sys

SESSIONS_DIR = 'sessions_data'
SCENARIOS_DIR = 'scenarios_data'


def find_storage_files():
    """Return all session and scenario storage files."""
    files = []
    for directory, label in [(SESSIONS_DIR, 'sessions'), (SCENARIOS_DIR, 'scenarios')]:
        pattern = os.path.join(directory, 'user_*_*.json')
        for path in sorted(glob.glob(pattern)):
            basename = os.path.basename(path)
            # Extract user_id from filename: user_{user_id}_sessions.json
            parts = basename.replace('.json', '').split('_', 1)
            user_id = parts[1].rsplit('_', 1)[0] if len(parts) > 1 else 'unknown'
            try:
                size = os.path.getsize(path)
                with open(path, 'r') as f:
                    data = json.load(f)
                entry_count = len(data) if isinstance(data, dict) else 0
            except Exception:
                size = 0
                entry_count = 0
            files.append({
                'path': path,
                'type': label,
                'user_id': user_id,
                'size': size,
                'entries': entry_count,
            })
    return files


def main():
    parser = argparse.ArgumentParser(description='Clean up polluted session/scenario storage files.')
    parser.add_argument('--confirm', action='store_true', help='Actually delete files (default is dry run)')
    parser.add_argument('--user', type=str, default=None, help='Only clean data for a specific user ID')
    parser.add_argument('--list-users', action='store_true', help='List all user IDs with stored data')
    args = parser.parse_args()

    files = find_storage_files()

    if not files:
        print('No storage files found. Nothing to clean.')
        return

    if args.list_users:
        user_ids = sorted(set(f['user_id'] for f in files))
        print(f'Found {len(user_ids)} user(s) with stored data:')
        for uid in user_ids:
            user_files = [f for f in files if f['user_id'] == uid]
            total_entries = sum(f['entries'] for f in user_files)
            types = ', '.join(sorted(set(f['type'] for f in user_files)))
            print(f'  {uid}  ({total_entries} entries, {types})')
        return

    # Filter by user if specified
    if args.user:
        files = [f for f in files if f['user_id'] == args.user]
        if not files:
            print(f'No storage files found for user: {args.user}')
            return

    # Display what will be affected
    mode = 'DELETING' if args.confirm else 'DRY RUN — would delete'
    print(f'\n{mode}:\n')
    for f in files:
        print(f"  {f['path']}  ({f['entries']} entries, {f['size']} bytes)")

    if not args.confirm:
        print(f'\nTotal: {len(files)} file(s)')
        print('Run with --confirm to actually delete.')
        return

    # Actually delete
    deleted = 0
    for f in files:
        try:
            os.remove(f['path'])
            print(f"  DELETED: {f['path']}")
            deleted += 1
        except Exception as e:
            print(f"  FAILED:  {f['path']} — {e}")

    print(f'\nDone. Deleted {deleted}/{len(files)} file(s).')


if __name__ == '__main__':
    main()
