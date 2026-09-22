"""Read only Weixin.exe memory, without offsets, injection or key persistence."""
import ctypes as C
from ctypes import wintypes as W
import re
import struct
import psutil
from .crypto import decrypt_page

class MBI(C.Structure):
    _fields_ = [('BaseAddress', C.c_void_p), ('AllocationBase', C.c_void_p),
                ('AllocationProtect', W.DWORD), ('PartitionId', W.WORD),
                ('RegionSize', C.c_size_t), ('State', W.DWORD),
                ('Protect', W.DWORD), ('Type', W.DWORD)]

def config_candidates(k, handle):
    # Adapted from wechatauto db.py at 492a8fb, Apache-2.0.
    # These are upstream object offsets, never assumed valid without page HMAC.
    needle = b'com.Tencent.WCDB.Config.Cipher'
    mask = bytes.fromhex('d2c7442458020000004889442450488b450048844c2448488944254048584c24')
    def read(addr, size):
        buf = C.create_string_buffer(size)
        got = C.c_size_t()
        try:
            if k.ReadProcessMemory(handle, addr, buf, size, C.byref(got)):
                return buf.raw[:got.value]
            return b''
        finally:
            C.memset(buf, 0, size)
    def chunks():
        address = 0
        mbi = MBI()
        while k.VirtualQueryEx(handle, address, C.byref(mbi), C.sizeof(mbi)):
            base, size = mbi.BaseAddress or 0, mbi.RegionSize
            if mbi.State == 0x1000 and not mbi.Protect & 0x100 and mbi.Protect & 0xff in (2,4,8,0x20,0x40,0x80):
                for offset in range(0, size, 2*1024*1024-128):
                    yield base+offset, read(base+offset, min(size-offset, 2*1024*1024))
            if base+size <= address:
                break
            address = base+size
    addresses = set()
    for base, data in chunks():
        addresses.update(base+m.start() for m in re.finditer(re.escape(needle), data))
    if not addresses:
        return
    pattern = re.compile(b'|'.join(re.escape(struct.pack('<QQ', a, len(needle))) for a in addresses))
    for base, data in chunks():
        for match in pattern.finditer(data):
            node = read(base+match.start()-16, 80)
            if len(node) != 80:
                continue
            ptr = struct.unpack_from('<Q', node, 0x28)[0]
            if not 0x10000 <= ptr < 0x800000000000:
                continue
            obj = read(ptr+0x88, 0x28)
            if len(obj) < 24:
                continue
            addr, size = struct.unpack_from('<QQ', obj, 8)
            if not (0 < size <= 1024 and 0x10000 <= addr < 0x800000000000):
                continue
            blob = read(addr, size)
            decoded = bytes(v ^ mask[i % len(mask)] for i, v in enumerate(blob))
            for m in re.finditer(rb"[xX]'([0-9a-fA-F]{64,192})'", decoded):
                run = m[1]
                for offset in sorted(set([0, len(run)-64] + list(range(0,len(run)-63,32)))):
                    yield bytearray.fromhex(run[offset:offset+64].decode())

def find_keys(paths):
    found = {}
    try:
        return _scan_keys(paths, found)
    except BaseException:
        for key in found.values():
            key[:] = bytes(len(key))
        raise

def _scan_keys(paths, found):
    targets = {}
    for path in paths:
        with path.open('rb') as f:
            page = f.read(4096)
        targets[page[:16]] = (path, page)
    k = C.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k.OpenProcess.restype = W.HANDLE
    k.VirtualQueryEx.argtypes = [W.HANDLE, C.c_void_p, C.POINTER(MBI), C.c_size_t]
    k.VirtualQueryEx.restype = C.c_size_t
    k.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    k.CloseHandle.argtypes = [W.HANDLE]
    pattern = re.compile(rb"x'([0-9a-fA-F]{64})([0-9a-fA-F]{32})'")
    opened = 0
    scanned_bytes = matches = salt_matches = 0
    for proc in psutil.process_iter(['pid', 'name']):
        if (proc.info['name'] or '').lower() != 'weixin.exe':
            continue
        handle = k.OpenProcess(0x410, False, proc.pid)
        if not handle:
            continue
        opened += 1
        try:
            for candidate in config_candidates(k, handle):
                for salt, (_, page) in targets.items():
                    if salt in found:
                        continue
                    try:
                        decrypt_page(page, 1, candidate, salt)
                        found[salt] = bytearray(candidate)
                    except ValueError:
                        pass
                candidate[:] = bytes(len(candidate))
                if len(found) == len(targets):
                    return found
            if len(found) == len(targets):
                return found
            address = 0
            mbi = MBI()
            while k.VirtualQueryEx(handle, address, C.byref(mbi), C.sizeof(mbi)):
                base, size = mbi.BaseAddress or 0, mbi.RegionSize
                if mbi.State == 0x1000 and not mbi.Protect & 0x100 and mbi.Protect & 0xff in (4, 8, 0x40, 0x80):
                    offset = 0
                    while offset < size:
                        amount = min(2*1024*1024, size-offset)
                        buf = C.create_string_buffer(amount)
                        read = C.c_size_t()
                        if k.ReadProcessMemory(handle, base+offset, buf, amount, C.byref(read)):
                            scanned_bytes += read.value
                            for match in pattern.finditer(buf.raw[:read.value]):
                                matches += 1
                                salt = bytes.fromhex(match[2].decode())
                                if salt in targets and salt not in found:
                                    salt_matches += 1
                                    key = bytearray.fromhex(match[1].decode())
                                    try:
                                        decrypt_page(targets[salt][1], 1, key, salt)
                                        found[salt] = key
                                    except ValueError:
                                        key[:] = bytes(len(key))
                        C.memset(buf, 0, amount)
                        offset += max(amount-100, 1) if amount > 100 else amount
                    if len(found) == len(targets):
                        return found
                nxt = base + size
                if nxt <= address:
                    break
                address = nxt
        finally:
            k.CloseHandle(handle)
    if len(found) != len(targets):
        for key in found.values():
            key[:] = bytes(len(key))
        raise RuntimeError(f'密钥验证不足：{len(found)}/{len(targets)}；可读取微信进程 {opened} 个；扫描 {scanned_bytes//1024//1024} MiB；格式候选 {matches}；盐匹配 {salt_matches}。当前版本可能不再保留此密钥格式。')
    return found
