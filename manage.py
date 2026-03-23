"""Database management CLI.

Usage:
  python manage.py init_db     # Create all tables and seed default admin + roles
  python manage.py create_db   # Create tables only (no drop), seed defaults
  python manage.py migrate_db  # Apply Alembic migrations to head
"""

import sys
import os

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def run_command(cmd_name):
    from app import create_app, db
    from app.commands.init_db import (
        InitDbCommand,
        CreateDbCommand,
        MigrateDbCommand,
        DataImportCommand,
        ForceDropTablesCommand,
    )

    commands = {
        "init_db": InitDbCommand,
        "create_db": CreateDbCommand,
        "migrate_db": MigrateDbCommand,
        "import": DataImportCommand,
        "force_drop_db": ForceDropTablesCommand,
    }

    if cmd_name not in commands:
        print(f"Unknown command: {cmd_name}")
        print(f"Available commands: {', '.join(commands)}")
        sys.exit(1)

    app = create_app(os.getenv("FLASK_CONFIG") or "default")
    with app.app_context():
        commands[cmd_name]().run()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    run_command(sys.argv[1])
