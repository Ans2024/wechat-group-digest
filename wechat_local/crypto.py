"""SQLCipher 4 raw-key pages; SQLite WAL checksums and committed transactions.

Reference: erbanku/weixin-cli 08af894, Apache-2.0 (see THIRD_PARTY.md).
WAL handling is independently implemented: upstream lacks checksum/commit checks.
"""
import hashlib
import hmac
import struct
from Crypto.Cipher import AES

PAGE = 4096

def mac_key(key, salt):
    return hashlib.pbkdf2_hmac('sha512', key, bytes(x ^ 0x3a for x in salt), 2, 32)

def decrypt_page(data, number, key, salt):
    if len(data) != PAGE:
        raise ValueError('数据库页长度不完整')
    start = 16 if number == 1 else 0
    expected = hmac.digest(mac_key(key, salt), data[start:-64] + struct.pack('<I', number), 'sha512')
    if not hmac.compare_digest(expected, data[-64:]):
        raise ValueError(f'数据库页 HMAC 校验失败，页号 {number}')
    plain = AES.new(key, AES.MODE_CBC, data[-80:-64]).decrypt(data[start:-80])
    return (b'SQLite format 3\0' if number == 1 else b'') + plain + bytes(80)

def checksum(data, endian, state=(0, 0)):
    a, b = state
    words = struct.unpack(endian + str(len(data)//4) + 'I', data)
    for i in range(0, len(words), 2):
        a = (a + words[i] + b) & 0xffffffff
        b = (b + words[i+1] + a) & 0xffffffff
    return a, b

def committed_frames(wal):
    if not wal:
        return {}, None, {'valid_frames': 0, 'committed_frames': 0}
    if len(wal) < 32:
        raise ValueError('WAL 头不完整')
    magic, version, size = struct.unpack('>III', wal[:12])
    if magic not in (0x377f0682, 0x377f0683) or version != 3007000 or size != PAGE:
        raise ValueError('未支持的 WAL 格式')
    endian = '<' if magic == 0x377f0682 else '>'
    state = checksum(wal[:24], endian)
    if state != struct.unpack('>II', wal[24:32]):
        raise ValueError('WAL 头校验失败')
    pending, committed, pages = {}, {}, None
    valid = last = 0
    for pos in range(32, len(wal)-24-PAGE+1, 24+PAGE):
        header, data = wal[pos:pos+24], wal[pos+24:pos+24+PAGE]
        number, count = struct.unpack('>II', header[:8])
        if header[8:16] != wal[16:24]:
            break  # stale preallocated tail after a WAL reset
        candidate = checksum(header[:8] + data, endian, state)
        if candidate != struct.unpack('>II', header[16:24]):
            raise ValueError('WAL 帧校验失败；请重试快照')
        if not number:
            raise ValueError('WAL 页号为零')
        state = candidate
        valid += 1
        pending[number] = data
        if count:
            committed.update(pending)
            pending.clear()
            pages, last = count, valid
    return committed, pages, {'valid_frames': valid, 'committed_frames': last,
                              'uncommitted_frames': valid-last}
