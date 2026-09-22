import hashlib
import sqlite3
from pathlib import Path
from .crypto import committed_frames, decrypt_page, PAGE

def discover():
    import os
    roots = []
    config = Path(os.environ['APPDATA']) / 'Tencent/xwechat/config'
    for file in config.glob('*.ini'):
        try:
            value = file.read_text(encoding='utf-8-sig').strip()
            candidate = Path(value) / 'xwechat_files'
            if candidate.is_dir():
                roots.append(candidate)
        except (OSError, UnicodeError, ValueError):
            pass
    roots.append(Path.home() / 'Documents/xwechat_files')
    return sorted(set(p.resolve() for root in roots if root.is_dir()
                      for p in root.glob('*/db_storage')))

def stable_snapshot(path, attempts=3):
    """Two byte-identical reads of DB + WAL, retry on concurrent writes.

    Optimistic quiescent snapshot; no live file handles are passed to SQLite.
    """
    path = Path(path)
    walpath = Path(str(path)+'-wal')
    def read_pair():
        db = path.read_bytes()
        wal = walpath.read_bytes() if walpath.exists() else b''
        return db, wal
    for _ in range(attempts):
        db, wal = read_pair()
        db2, wal2 = read_pair()
        if db == db2 and wal == wal2:
            return db, wal, {'db_sha256': hashlib.sha256(db).hexdigest(),
                            'wal_sha256': hashlib.sha256(wal).hexdigest(),
                            'snapshot_method': 'two identical DB+WAL reads'}
    raise RuntimeError('数据库持续写入，未取得稳定快照；请稍后重试')

def open_snapshot(path, keys):
    db, wal, audit = stable_snapshot(path)
    salt = db[:16]
    key = keys[salt]
    frames, count, wal_audit = committed_frames(wal)
    if len(db) % PAGE:
        raise ValueError('数据库长度不是完整页')
    count = count or len(db)//PAGE
    plain = bytearray(count*PAGE)
    conn = None
    try:
        for number in range(1, count+1):
            encrypted = frames.get(number, db[(number-1)*PAGE:number*PAGE])
            page = decrypt_page(encrypted, number, key, salt)
            plain[(number-1)*PAGE:number*PAGE] = page
        # A standalone in-memory image cannot open in WAL mode.
        plain[18:20] = b'\1\1'
        conn = sqlite3.connect(':memory:')
        conn.deserialize(plain)
        conn.execute('PRAGMA query_only=ON')
        result = conn.execute('PRAGMA quick_check').fetchall()
        if result != [('ok',)]:
            raise ValueError('解密数据库 quick_check 未通过')
        conn.row_factory = sqlite3.Row
        audit.update(wal_audit)
        audit['integrity'] = 'quick_check ok; every effective page HMAC verified'
        return conn, audit
    except BaseException:
        if conn:
            conn.close()
        raise
    finally:
        plain[:] = bytes(len(plain))

def columns(conn, table):
    return [r[1] for r in conn.execute('PRAGMA table_info("'+table.replace('"','""')+'")')]
