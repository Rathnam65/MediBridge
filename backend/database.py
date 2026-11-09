from pathlib import Path
import re
from .config import get_settings
import sqlite3
from collections.abc import Mapping

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError as SQLAlchemyIntegrityError

BASE=Path(__file__).resolve().parent.parent
_settings=get_settings()
DB=_settings['database_path']
DATABASE_URL=_settings['database_url']
REQUIRE_POSTGRES=_settings['require_postgres']
DB.parent.mkdir(parents=True,exist_ok=True)

INTEGRITY_ERRORS=(sqlite3.IntegrityError,SQLAlchemyIntegrityError)
_engine: Engine | None = None


class _Result:
    def __init__(self, result):
        self._result=result

    def fetchone(self):
        row=self._result.mappings().fetchone()
        return row

    def fetchall(self):
        return self._result.mappings().fetchall()


class _PostgresConnection:
    def __init__(self, engine):
        self._connection=engine.connect()

    def execute(self, statement, parameters=()):
        if isinstance(parameters, Mapping):
            return _Result(self._connection.execute(text(statement), parameters))
        values=tuple(parameters or ())
        placeholders=statement.count('?')
        if placeholders != len(values):
            raise ValueError(
                f"Query expects {placeholders} parameters; received {len(values)}."
            )
        binds={f"p{index}": value for index,value in enumerate(values)}
        query=re.sub(
            r"\?",
            lambda match: f":p{self._placeholder_index(statement, match.start())}",
            statement,
        )
        return _Result(self._connection.execute(text(query), binds))

    @staticmethod
    def _placeholder_index(statement, position):
        return statement.count('?',0,position)

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()


def _postgres_url():
    if not DATABASE_URL:
        return None
    url=DATABASE_URL
    if url.startswith('postgres://'):
        return 'postgresql+psycopg://' + url[len('postgres://'):]
    if url.startswith('postgresql://'):
        return 'postgresql+psycopg://' + url[len('postgresql://'):]
    if url.startswith('postgresql+psycopg://'):
        return url
    raise ValueError('DATABASE_URL must be a PostgreSQL connection URL.')


def _get_engine():
    global _engine
    if _engine is None:
        url=_postgres_url()
        if not url:
            raise RuntimeError('DATABASE_URL is not configured.')
        _engine=create_engine(
            url,
            pool_pre_ping=True,
            pool_recycle=300,
            pool_size=3,
            max_overflow=2,
            connect_args={'connect_timeout':10},
        )
    return _engine


def conn():
    if DATABASE_URL:
        return _PostgresConnection(_get_engine())
    if REQUIRE_POSTGRES:
        raise RuntimeError(
            "REQUIRE_POSTGRES is enabled but DATABASE_URL is not configured."
        )
    c=sqlite3.connect(DB,timeout=30)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA busy_timeout=30000')
    return c
def init_db():
    if DATABASE_URL:
        from alembic import command
        from alembic.config import Config

        alembic_config=Config(str(BASE/'alembic.ini'))
        command.upgrade(alembic_config,'head')
        return
    c=conn()
    existing_settings = c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='settings'"
    ).fetchone()
    if existing_settings:
        settings_columns = {
            row['name'] for row in c.execute('PRAGMA table_info(settings)')
        }
        existing_legacy_settings = c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='legacy_settings'"
        ).fetchone()
        if settings_columns and 'user_id' not in settings_columns and existing_legacy_settings:
            c.close()
            raise RuntimeError(
                'Refusing database initialization: both legacy settings tables '
                'exist and require operator review.'
            )
    c.executescript('''
        CREATE TABLE IF NOT EXISTS users(
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL COLLATE NOCASE UNIQUE,
            full_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS auth_sessions(
            token_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS cases(
            id TEXT PRIMARY KEY,
            user_id TEXT REFERENCES users(id),
            created_at TEXT NOT NULL,
            assigned_at TEXT,
            deadline_at TEXT,
            document_name TEXT,
            source TEXT,
            text TEXT NOT NULL,
            status TEXT NOT NULL,
            overall_confidence REAL NOT NULL,
            extracted_json TEXT NOT NULL,
            recommendations_json TEXT NOT NULL,
            gaps_json TEXT NOT NULL DEFAULT '[]',
            source_locations_json TEXT NOT NULL DEFAULT '[]',
            workflow_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS activity(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT REFERENCES users(id),
            created_at TEXT NOT NULL,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            detail TEXT NOT NULL
        );
    ''')
    case_columns={row['name'] for row in c.execute('PRAGMA table_info(cases)')}
    if 'user_id' not in case_columns:
        c.execute('ALTER TABLE cases ADD COLUMN user_id TEXT REFERENCES users(id)')
    if 'gaps_json' not in case_columns:
        c.execute("ALTER TABLE cases ADD COLUMN gaps_json TEXT NOT NULL DEFAULT '[]'")
    if 'assigned_at' not in case_columns:
        c.execute('ALTER TABLE cases ADD COLUMN assigned_at TEXT')
    if 'deadline_at' not in case_columns:
        c.execute('ALTER TABLE cases ADD COLUMN deadline_at TEXT')
    if 'source_locations_json' not in case_columns:
        c.execute("ALTER TABLE cases ADD COLUMN source_locations_json TEXT NOT NULL DEFAULT '[]'")
    if 'workflow_json' not in case_columns:
        c.execute("ALTER TABLE cases ADD COLUMN workflow_json TEXT NOT NULL DEFAULT '{}'")
    activity_columns={row['name'] for row in c.execute('PRAGMA table_info(activity)')}
    if 'user_id' not in activity_columns:
        c.execute('ALTER TABLE activity ADD COLUMN user_id TEXT REFERENCES users(id)')
    settings_columns={row['name'] for row in c.execute('PRAGMA table_info(settings)')}
    if settings_columns and 'user_id' not in settings_columns:
        legacy_settings={row['name'] for row in c.execute("PRAGMA table_info(legacy_settings)")}
        if not legacy_settings:
            c.execute('ALTER TABLE settings RENAME TO legacy_settings')
        else:
            c.close()
            raise RuntimeError(
                'Refusing database initialization: legacy settings already exist.'
            )
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings(
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            PRIMARY KEY(user_id, key)
        )
    ''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_cases_user_created ON cases(user_id, created_at)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_cases_user_assigned ON cases(user_id, assigned_at)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_activity_user_id ON activity(user_id, id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON auth_sessions(expires_at)')
    c.commit(); c.close()
