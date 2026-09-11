import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from .config import settings
from .preset_voices import install_presets


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def conn():
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(settings.database_path, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA busy_timeout=10000')
    try:
        yield c
        c.commit()
    finally:
        c.close()


def _add_column(c, table, column, definition):
    columns = {row[1] for row in c.execute(f'PRAGMA table_info({table})').fetchall()}
    if column not in columns:
        c.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')


def init_db():
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    with conn() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('PRAGMA synchronous=NORMAL')
        c.executescript('''
        CREATE TABLE IF NOT EXISTS documents(
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, path TEXT, type TEXT,
          size INTEGER, brand TEXT DEFAULT '', series TEXT DEFAULT '', year TEXT DEFAULT '',
          chunks INTEGER DEFAULT 0, version INTEGER DEFAULT 1, created_at TEXT, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS document_versions(
          id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER NOT NULL,
          version INTEGER NOT NULL, name TEXT, path TEXT, size INTEGER,
          chunks INTEGER DEFAULT 0, created_at TEXT,
          FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS chunks(
          id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER, content TEXT,
          tokens TEXT, page INTEGER, FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS sessions(
          id TEXT PRIMARY KEY, vehicle TEXT, script TEXT, version INTEGER DEFAULT 1,
          sentence INTEGER DEFAULT 0, status TEXT DEFAULT 'idle', updated_at TEXT,
          voice_id TEXT DEFAULT 'browser-default'
        );
        CREATE TABLE IF NOT EXISTS voices(
          id TEXT PRIMARY KEY, name TEXT, style TEXT, provider TEXT,
          reference_path TEXT DEFAULT '', prompt_text TEXT DEFAULT '', prompt_lang TEXT DEFAULT 'zh',
          aux_reference_paths TEXT DEFAULT '[]',
          created_at TEXT
        );
        ''')
        for table, column, definition in [
            ('chunks', 'embedding', 'BLOB'),
            ('chunks', 'embedding_model', "TEXT DEFAULT ''"),
            ('chunks', 'search_text', "TEXT DEFAULT ''"),
            ('chunks', 'parent_content', "TEXT DEFAULT ''"),
            ('chunks', 'metadata', "TEXT DEFAULT '{}'"),
            ('documents', 'source_url', "TEXT DEFAULT ''"),
            ('documents', 'license', "TEXT DEFAULT '待审核'"),
            ('documents', 'valid_until', "TEXT DEFAULT ''"),
            ('documents', 'redactions', 'INTEGER DEFAULT 0'),
            ('document_versions', 'metadata', "TEXT DEFAULT '{}'"),
            ('documents', 'version', 'INTEGER DEFAULT 1'),
            ('documents', 'updated_at', 'TEXT'),
            ('voices', 'reference_path', "TEXT DEFAULT ''"),
            ('voices', 'reference_voice_id', "TEXT DEFAULT ''"),
            ('voices', 'prompt_text', "TEXT DEFAULT ''"),
            ('voices', 'prompt_lang', "TEXT DEFAULT 'zh'"),
            ('voices', 'aux_reference_paths', "TEXT DEFAULT '[]'"),
            ('voices', 'validated_aux_reference_paths', 'TEXT'),
            ('voices', 'sampling_seed', 'INTEGER'),
            ('voices', 'sampling_top_k', 'INTEGER'),
            ('voices', 'sampling_top_p', 'REAL'),
            ('voices', 'sampling_temperature', 'REAL'),
            ('voices', 'sampling_model_version', 'TEXT'),
            ('voices', 'calibration_details', 'TEXT'),
            ('voices', 'synthesis_status', "TEXT DEFAULT 'ready'"),
            ('voices', 'synthesis_message', "TEXT DEFAULT ''"),
            ('voices', 'synthesis_duration', 'REAL'),
            ('voices', 'synthesis_checked_at', 'TEXT'),
            ('voices', 'model_profile', "TEXT DEFAULT 'base'"),
            ('sessions', 'voice_id', "TEXT DEFAULT 'browser-default'"),
        ]:
            _add_column(c, table, column, definition)
        # Older databases predate per-voice model routing.  Only the trained
        # Xilian records should retain the fine-tuned weights; every other
        # uploaded sample must use the v2ProPlus base model.
        c.execute(
            "UPDATE voices SET model_profile='xilian' WHERE model_profile='base' AND "
            "(id IN ('voice-f42877922900','voice-fac38ad29932') OR "
            "reference_path LIKE '%07c2ddaa9e9c48b38effbbe6713386f8%' OR "
            "reference_path LIKE '%5aef24da46e84719b2629ab0f7d04840%')"
        )
        c.execute(
            'INSERT OR IGNORE INTO voices(id,name,style,provider,created_at) VALUES(?,?,?,?,?)',
            ('browser-default', '系统默认', '自然', 'browser', now()),
        )
        install_presets(c, now())
        c.executescript('''
          CREATE TABLE IF NOT EXISTS analytics_events(
            id TEXT PRIMARY KEY,kind TEXT NOT NULL,created_at TEXT NOT NULL,vehicle TEXT DEFAULT '',
            question TEXT DEFAULT '',seconds REAL DEFAULT 0,latency_ms REAL DEFAULT 0,details TEXT DEFAULT '{}');
          CREATE INDEX IF NOT EXISTS event_time ON analytics_events(created_at);
          CREATE TABLE IF NOT EXISTS voice_evaluations(
            id TEXT PRIMARY KEY,created_at TEXT,voice_id TEXT,reviewer TEXT,text TEXT,
            similarity INTEGER,clarity INTEGER,pause INTEGER,emotion INTEGER,overall INTEGER,notes TEXT);
        ''')
        c.execute('''
          INSERT INTO document_versions(document_id,version,name,path,size,chunks,created_at)
          SELECT d.id,COALESCE(d.version,1),d.name,d.path,d.size,d.chunks,COALESCE(d.updated_at,d.created_at)
          FROM documents d
          WHERE NOT EXISTS (SELECT 1 FROM document_versions v WHERE v.document_id=d.id)
        ''')
        c.executescript('''
          CREATE TABLE IF NOT EXISTS rag_state(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL);
          INSERT OR IGNORE INTO rag_state VALUES(1,0);
          CREATE TRIGGER IF NOT EXISTS rag_chunk_insert AFTER INSERT ON chunks BEGIN
            UPDATE rag_state SET revision=revision+1 WHERE id=1; END;
          CREATE TRIGGER IF NOT EXISTS rag_chunk_update AFTER UPDATE ON chunks BEGIN
            UPDATE rag_state SET revision=revision+1 WHERE id=1; END;
          CREATE TRIGGER IF NOT EXISTS rag_chunk_delete AFTER DELETE ON chunks BEGIN
            UPDATE rag_state SET revision=revision+1 WHERE id=1; END;
          CREATE TRIGGER IF NOT EXISTS rag_document_update AFTER UPDATE ON documents BEGIN
            UPDATE rag_state SET revision=revision+1 WHERE id=1; END;
          CREATE TRIGGER IF NOT EXISTS rag_document_delete AFTER DELETE ON documents BEGIN
            UPDATE rag_state SET revision=revision+1 WHERE id=1; END;
        ''')
