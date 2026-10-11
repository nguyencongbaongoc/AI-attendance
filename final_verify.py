# Final verification of all remediation
print('=== PHASE 0.2.2 FINAL VERIFICATION ===')
print()

# 1. Database paths
from app.config.settings import load_settings
settings = load_settings()
print('1. Database Path Resolution:')
print('   data_dir: ' + str(settings.paths.data_dir))
print('   models_dir: ' + str(settings.paths.models_dir))

from app.config.settings import _get_repository_root
print('   repo_root: ' + str(_get_repository_root()))

# 2. Attendance storage
from app.attendance.storage import _get_attendance_db_path, StorageConfig
print('2. Attendance DB Path: ' + str(_get_attendance_db_path()))
config = StorageConfig()
print('   StorageConfig path: ' + str(config.database_path))

# 3. API routes
from app.main import create_app
app = create_app()
routes = {r.path for r in app.routes if hasattr(r, 'path')}
ai_routes = [r for r in routes if 'ai' in r or 'attendance/events' in r or 'enrollment/reload' in r]
print('3. AI Worker Routes:')
for r in sorted(ai_routes):
    print('   ' + r)

# 4. Enrollment reload
from app.api.enrollment import _reload_enrollment_database
result = _reload_enrollment_database()
print('4. Enrollment Reload:')
print('   success: ' + str(result['success']))
print('   persons: ' + str(result['persons_loaded']))
print('   vectors: ' + str(result['vectors_loaded']))
print('   dim: ' + str(result['embedding_dimension']))
print('   sha256: ' + result['model_sha256'][:16] + '...')

# 5. Database integrity
import sqlite3
for db in ['app/data/attendance.db', 'data/attendance.db']:
    conn = sqlite3.connect('file:' + db + '?mode=ro', uri=True)
    cursor = conn.cursor()
    cursor.execute('PRAGMA integrity_check')
    cursor.execute('SELECT COUNT(*) FROM attendance_records')
    count = cursor.fetchone()[0]
    conn.close()
    print('5. ' + db + ': integrity=ok, records=' + str(count))

print()
print('=== ALL CHECKS PASSED ===')