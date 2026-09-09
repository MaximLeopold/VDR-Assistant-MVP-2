"""Disabled: Manifest v2 snapshots cannot be refreshed, reconciled or adopted."""
import sys


def main() -> int:
    print('Disabled for Manifest v2. Create a fresh snapshot at a distinct case-root location and associate a new empty vector store.',file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
