from contextlib import contextmanager
import sqlite3


class StoreInitializationError(ValueError):
    """The connection does not contain a compatible project ledger."""


def is_row_id(value):
    return type(value) is int and 0 < value <= 2**63 - 1


@contextmanager
def write_transaction(db):
    if db.in_transaction:
        raise sqlite3.ProgrammingError('end the current transaction before writing')
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.commit()
    except BaseException:
        if db.in_transaction:
            db.rollback()
        raise


def _schema(db):
    rows = db.execute(
        'SELECT name, sql FROM sqlite_schema WHERE substr(name, 1, 7) <> ?',
        ('sqlite_',),
    )
    return {name: sql.split() for name, sql in rows}


def initialize_database(db, application_id, schema, install):
    """Install an empty ledger or verify the exact application-owned schema."""
    try:
        if db.in_transaction:
            raise StoreInitializationError('end the current transaction before initialization')
        db.execute('PRAGMA foreign_keys = ON')
        if db.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
            raise StoreInitializationError('SQLite foreign keys are unavailable')
        with write_transaction(db):
            current_id = db.execute('PRAGMA application_id').fetchone()[0]
            version = db.execute('PRAGMA user_version').fetchone()[0]
            actual = _schema(db)
            if current_id == 0 and version == 0 and not actual:
                install(db)
                db.execute(f'PRAGMA application_id = {application_id}')
                db.execute('PRAGMA user_version = 1')
                actual = _schema(db)
            elif (current_id, version) != (application_id, 1):
                raise StoreInitializationError('wrong ledger type or version')
            expected = {name: sql.split() for name, sql in schema.items()}
            if actual != expected:
                raise StoreInitializationError('incompatible ledger structure')
    except sqlite3.Error as exc:
        raise StoreInitializationError('could not initialize the ledger') from exc
