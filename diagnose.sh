#!/bin/bash
# MD Compliance — Diagnostic Script
# Run this on the server: bash diagnose.sh

set -e
echo "========================================"
echo "MD Compliance Diagnostic Report"
echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "========================================"

# 1. Container status
echo ""
echo "=== CONTAINER STATUS ==="
docker compose ps 2>/dev/null || docker-compose ps 2>/dev/null || echo "Docker compose not available"

# 2. App container logs (last 80 lines)
echo ""
echo "=== APP LOGS (last 80 lines) ==="
docker compose logs --tail 80 app 2>/dev/null || docker-compose logs --tail 80 app 2>/dev/null || echo "Cannot read app logs"

# 3. Check if app is responding
echo ""
echo "=== HTTP CHECK ==="
curl -s -o /dev/null -w "HTTP %{http_code} from localhost:5000\n" http://localhost:5000/login --max-time 5 2>/dev/null || echo "App not responding on port 5000"
curl -s -o /dev/null -w "HTTP %{http_code} from localhost:80\n" http://localhost:80/login --max-time 5 2>/dev/null || echo "Nginx not responding on port 80"

# 4. Check postgres
echo ""
echo "=== POSTGRES ==="
docker compose exec -T postgres pg_isready 2>/dev/null || docker-compose exec -T postgres pg_isready 2>/dev/null || echo "Postgres not reachable"

# 5. Check migration state
echo ""
echo "=== MIGRATION STATE ==="
docker compose exec -T app python3 -c "
from app import create_app, db
from sqlalchemy import inspect, text
app = create_app('default')
with app.app_context():
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    print(f'Tables: {len(tables)}')
    if 'alembic_version' in tables:
        ver = db.session.execute(text('SELECT version_num FROM alembic_version')).scalar()
        print(f'Alembic version: {ver}')
    else:
        print('No alembic_version table')
    for t in ['training', 'training_assignment', 'frameworks']:
        if t in tables:
            print(f'  {t}: exists')
        else:
            print(f'  {t}: MISSING')
    # Check for admin user
    try:
        count = db.session.execute(text('SELECT count(*) FROM users WHERE super = true')).scalar()
        print(f'Admin users: {count}')
    except Exception as e:
        print(f'Users table error: {e}')
" 2>/dev/null || echo "Cannot run migration check (app container may not be running)"

# 6. Check for Python import errors
echo ""
echo "=== IMPORT CHECK ==="
docker compose exec -T app python3 -c "
import sys
errors = []
mods = [
    'app',
    'app.masri.training_routes',
    'app.masri.trust_portal',
    'app.masri.continuous_monitor',
    'app.masri.evidence_generators',
    'app.masri.control_mappings',
]
for m in mods:
    try:
        __import__(m)
        print(f'{m}: OK')
    except Exception as e:
        print(f'{m}: FAIL — {e}')
        errors.append(m)
if errors:
    print(f'\n{len(errors)} module(s) failed to import')
    sys.exit(1)
else:
    print('\nAll modules import OK')
" 2>/dev/null || echo "Cannot run import check"

# 7. Check gunicorn process
echo ""
echo "=== GUNICORN PROCESS ==="
docker compose exec -T app ps aux 2>/dev/null | grep -E "gunicorn|python" || echo "No gunicorn process found"

# 8. Disk space
echo ""
echo "=== DISK SPACE ==="
df -h / 2>/dev/null | tail -1

echo ""
echo "========================================"
echo "Done. Share the output above for debugging."
echo "========================================"
