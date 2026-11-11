"""
cube_proto.py - Hatsune Miku CUBEFACE Bluetooth protocol, reimplemented for interoperability
(worked out from the MikuCube 1.0.2 Android app; line references point into its decompiled bundle).

Layers:
  * JieLi RCSP auth (SAFER+ / Bluetooth-E1 style), raw bytes on ae01/ae02
  * RCSP "FE DC BA" framing
  * a small file-system protocol on top (browse 0x0C, read 0x24, write 0x1A/0x1B/0x1D/0x20/0x1C)
  * DM.JSN (danmaku list) / BA.JSN (current face) payloads
  * RU30 ("BR28") image encoder for custom faces (296x240 RGB565 + RLE)

Tested from macOS with bleak: auth, file browse/read/write, custom face upload.
Pure functions are unit-checked (see `_selftest`).
Requires: bleak (for CubeClient), Pillow (only for encode_image_file).
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import struct
from dataclasses import dataclass
from typing import Callable, Optional

# --------------------------------------------------------------------------------------
# UUIDs  (decompiled.js 245021-245047)
# --------------------------------------------------------------------------------------
SVC_AE00 = "0000ae00-0000-1000-8000-00805f9b34fb"   # JieLi RCSP service (on the "headphone" device)
CHR_AE01 = "0000ae01-0000-1000-8000-00805f9b34fb"   # phone -> device, write without response
CHR_AE02 = "0000ae02-0000-1000-8000-00805f9b34fb"   # device -> phone, notify
SVC_D100 = "0000d100-b1b1-fbcc-9949-2b4bff2b3a46"
CHR_D101 = "0000d101-b1b1-fbcc-9949-2b4bff2b3a46"   # read: danmaku music-sync flag (on headphone conn)
CHR_D102 = "0000d102-b1b1-fbcc-9949-2b4bff2b3a46"   # write: danmaku music-sync flag
CHR_D103 = "0000d103-b1b1-fbcc-9949-2b4bff2b3a46"   # read: danmaku large-text flag
CHR_D104 = "0000d104-b1b1-fbcc-9949-2b4bff2b3a46"   # write: danmaku large-text flag
CHR_D106 = "0000d106-b1b1-fbcc-9949-2b4bff2b3a46"   # cube: "headphone" MAC (first 6 bytes)
CHR_D108 = "0000d108-b1b1-fbcc-9949-2b4bff2b3a46"

# --------------------------------------------------------------------------------------
# CRC16 used everywhere (`crc16Jl`, decompiled.js 274200-274259) == CRC-16/XMODEM
# (poly 0x1021, init 0, no reflection, no xorout) -- identical to binascii.crc_hqx(data, 0)
# --------------------------------------------------------------------------------------
_CRC_NIB = [0, 4129, 8258, 12387, 16516, 20645, 24774, 28903,
            33032, 37161, 41290, 45419, 49548, 53677, 57806, 61935]


def crc16_jl(data: bytes, init: int = 0) -> int:
    c = init & 0xFFFF
    for b in data:
        c = ((c << 4) & 0xFFFF) ^ _CRC_NIB[(c >> 12) ^ (b >> 4)]
        c = ((c << 4) & 0xFFFF) ^ _CRC_NIB[(c >> 12) ^ (b & 0x0F)]
    return c


# --------------------------------------------------------------------------------------
# RCSP auth (decompiled.js 275000-275418 cipher, 275789-275959 etCipher,
# 276085-276128 tables, 276342-276651 handshake)
# --------------------------------------------------------------------------------------
AUTH_ADDR = bytes([17, 34, 51, 51, 34, 17])                       # 11 22 33 33 22 11
AUTH_KEY = bytes([6, 119, 95, 135, 145, 141, 212, 35, 0, 93, 241, 216, 207, 12, 20, 43])
AUTH_PASS = bytes.fromhex("0270617373")                          # 0x02 "pass"

_BIAS = [
    [119, 241, 86, 36, 126, 71, 27, 134, 189, 112, 142, 30, 59, 115, 22, 3],
    [100, 172, 40, 90, 201, 179, 55, 197, 10, 16, 183, 163, 186, 177, 151, 70],
    [61, 5, 220, 102, 110, 246, 154, 248, 13, 88, 149, 103, 198, 170, 171, 236],
    [160, 104, 155, 150, 212, 235, 191, 67, 73, 54, 233, 106, 137, 216, 195, 138],
    [148, 99, 153, 188, 123, 190, 193, 34, 187, 92, 113, 213, 31, 146, 87, 93],
    [143, 68, 65, 29, 81, 230, 64, 23, 251, 253, 25, 50, 52, 184, 97, 42],
    [202, 35, 111, 218, 57, 247, 162, 1, 127, 214, 49, 231, 222, 128, 4, 221],
    [44, 89, 130, 175, 168, 224, 15, 205, 161, 18, 62, 48, 209, 28, 208, 58],
    [51, 114, 46, 79, 144, 2, 19, 6, 117, 206, 135, 194, 239, 178, 173, 125],
    [56, 21, 225, 82, 159, 122, 108, 47, 39, 196, 226, 129, 169, 207, 141, 192],
    [215, 223, 255, 96, 118, 20, 140, 94, 85, 9, 228, 8, 199, 66, 32, 252],
    [210, 80, 145, 217, 76, 98, 158, 232, 185, 166, 249, 26, 0, 33, 11, 250],
    [53, 156, 78, 75, 105, 72, 203, 14, 200, 164, 91, 234, 132, 7, 180, 24],
    [244, 174, 107, 219, 167, 204, 63, 139, 74, 12, 60, 37, 229, 84, 77, 69],
    [131, 237, 17, 240, 176, 83, 147, 242, 116, 38, 181, 157, 109, 124, 243, 45],
    [241, 86, 36, 126, 71, 27, 134, 189, 112, 142, 30, 59, 115, 22, 3, 182],
    [172, 40, 90, 201, 179, 55, 197, 10, 16, 183, 163, 186, 177, 151, 70, 136],
]
# exp table: 45^x mod 257 (256 -> 0)
_EXP = [1, 45, 226, 147, 190, 69, 21, 174, 120, 3, 135, 164, 184, 56, 207, 63, 8, 103, 9, 148, 235, 38, 168, 107, 189, 24, 52, 27, 187, 191, 114, 247, 64, 53, 72, 156, 81, 47, 59, 85, 227, 192, 159, 216, 211, 243, 141, 177, 255, 167, 62, 220, 134, 119, 215, 166, 17, 251, 244, 186, 146, 145, 100, 131, 241, 51, 239, 218, 44, 181, 178, 43, 136, 209, 153, 203, 140, 132, 29, 20, 129, 151, 113, 202, 95, 163, 139, 87, 60, 130, 196, 82, 92, 28, 232, 160, 4, 180, 133, 74, 246, 19, 84, 182, 223, 12, 26, 142, 222, 224, 57, 252, 32, 155, 36, 78, 169, 152, 158, 171, 242, 96, 208, 108, 234, 250, 199, 217, 0, 212, 31, 110, 67, 188, 236, 83, 137, 254, 122, 93, 73, 201, 50, 194, 249, 154, 248, 109, 22, 219, 89, 150, 68, 233, 205, 230, 70, 66, 143, 10, 193, 204, 185, 101, 176, 210, 198, 172, 30, 65, 98, 41, 46, 14, 116, 80, 2, 90, 195, 37, 123, 138, 42, 91, 240, 6, 13, 71, 111, 112, 157, 126, 16, 206, 18, 39, 213, 76, 79, 214, 121, 48, 104, 54, 117, 125, 228, 237, 128, 106, 144, 55, 162, 94, 118, 170, 197, 127, 61, 175, 165, 229, 25, 97, 253, 77, 124, 183, 11, 238, 173, 75, 34, 245, 231, 115, 35, 33, 200, 5, 225, 102, 221, 179, 88, 105, 99, 86, 15, 161, 49, 149, 23, 7, 58, 40]
_LOG = [0] * 256
for _i, _v in enumerate(_EXP):
    _LOG[_v] = _i
_SET = {0, 3, 4, 7, 8, 11, 12, 15}
_PERM = [8, 11, 12, 15, 2, 1, 6, 5, 10, 9, 14, 13, 0, 7, 4, 3]


def _pht(a):                                   # _jl_qe
    for i in range(0, 16, 2):
        x, y = a[i], a[i + 1]
        a[i] = (2 * x + y) & 0xFF
        a[i + 1] = (x + y) & 0xFF


def _perm(a):                                  # _jl_Ke
    c = a[:16]
    for i in range(16):
        a[i] = c[_PERM[i]]


def _key_schedule(key: bytes):                 # _jl_Qe (+ _jl_Je = rotl3)
    K = [[0] * 16 for _ in range(17)]
    reg = [0] * 17
    for i in range(16):
        reg[i] = key[i]
        reg[16] ^= key[i]
    K[0] = reg[:16]
    r = reg[:]
    for rnd in range(16):
        r = [((x << 3) & 0xFF) | (x >> 5) for x in r]
        idx = rnd + 1
        for j in range(16):
            K[rnd + 1][j] = (r[idx] + _BIAS[rnd + 1][15 - j]) & 0xFF
            idx = 0 if idx + 1 > 16 else idx + 1
    return K


def _round(n, a, K):                           # _jl_Ze
    k1, k2 = K[2 * n], K[2 * n + 1]
    for i in range(16):
        a[i] = (a[i] ^ k1[i]) if i in _SET else ((a[i] + k1[i]) & 0xFF)
    for i in range(16):
        a[i] = _EXP[a[i]] if i in _SET else _LOG[a[i]]
    for i in range(16):
        a[i] = ((a[i] + k2[i]) & 0xFF) if i in _SET else (a[i] ^ k2[i])
    _pht(a); _perm(a); _pht(a); _perm(a); _pht(a); _perm(a); _pht(a)


def _encrypt(a, K, input_add: bool):           # _jl_$e  (Ar / Ar')
    saved = a[:16]
    for n in range(8):
        if n == 2 and input_add:
            for i in range(16):
                a[i] = (saved[i] ^ a[i]) if i in _SET else ((saved[i] + a[i]) & 0xFF)
        _round(n, a, K)
    for i in range(16):
        a[i] = (a[i] ^ K[16][i]) if i in _SET else ((a[i] + K[16][i]) & 0xFF)


_KT_OFF = [(233, '+'), (229, '^'), (223, '+'), (193, '^'), (179, '+'), (167, '^'), (149, '+'), (131, '^'),
           (233, '^'), (229, '+'), (223, '^'), (193, '+'), (179, '^'), (167, '+'), (149, '^'), (131, '+')]


def et_cipher(challenge: bytes, key: bytes = AUTH_KEY, addr: bytes = AUTH_ADDR) -> bytes:
    """etCipher: E1(key, challenge, addr) full 16-byte output, prefixed by 0x01 (17 bytes)."""
    ch = list(challenge[:16])
    a = ch[:]
    _encrypt(a, _key_schedule(key), False)
    ext = [addr[i % 6] for i in range(16)]
    for i in range(16):
        a[i] = ((a[i] ^ ch[i]) + ext[i]) & 0xFF
    kt = [((key[i] + v) & 0xFF) if op == '+' else (key[i] ^ v) for i, (v, op) in enumerate(_KT_OFF)]
    _encrypt(a, _key_schedule(bytes(kt)), True)
    return bytes([1]) + bytes(a)


def auth_nonce_packet(nonce: Optional[bytes] = None) -> bytes:
    """First packet the app writes to ae01: 0x00 + 16 random bytes (not FE DC BA framed)."""
    return b"\x00" + (nonce if nonce is not None else os.urandom(16))


def auth_reply(device_packet: bytes) -> Optional[bytes]:
    """Given an ae02 auth packet, return what to write back (or None)."""
    if len(device_packet) == 17 and device_packet[0] == 0x00:    # device challenge
        return et_cipher(device_packet[1:17])
    if len(device_packet) == 17 and device_packet[0] == 0x01:    # device answer to our nonce (not verified by app)
        return AUTH_PASS
    return None


# --------------------------------------------------------------------------------------
# RCSP framing (buildFedcba, decompiled.js 274158-274198; parsing 226394-226461)
#   FE DC BA | flag | opcode | len_hi len_lo | payload[len] | EF
#   flag 0xC0 = command, response wanted; 0x80 = command, no response (data);
#   flag 0x00 = response.  Command payload[0] = our seq (sn, +1 mod 256);
#   response payload = [status, sn, ...].
# --------------------------------------------------------------------------------------
FLAG_CMD = 0xC0
FLAG_CMD_NORESP = 0x80
FLAG_RESP = 0x00


def build_fedcba(flag: int, opcode: int, payload: bytes) -> bytes:
    payload = bytes(payload)
    return bytes([0xFE, 0xDC, 0xBA, flag & 0xFF, opcode & 0xFF,
                  (len(payload) >> 8) & 0xFF, len(payload) & 0xFF]) + payload + b"\xEF"


@dataclass
class Packet:
    flag: int
    opcode: int
    payload: bytes

    @property
    def is_command(self) -> bool:
        return bool(self.flag & 0x80)


def parse_fedcba(buf: bytes) -> Optional[Packet]:
    if len(buf) < 8 or buf[:3] != b"\xFE\xDC\xBA":
        return None
    ln = (buf[5] << 8) | buf[6]
    if len(buf) < 7 + ln + 1:
        return None
    return Packet(buf[3], buf[4], bytes(buf[7:7 + ln]))


class Reassembler:
    """Joins fragmented FEDCBA packets arriving over several notifications (defensive;
    the app itself assumes one packet per notification with MTU 512)."""

    def __init__(self):
        self.buf = bytearray()

    def feed(self, data: bytes):
        """Yields ('fedcba', Packet) or ('raw', bytes)."""
        out = []
        if not self.buf and data[:3] != b"\xFE\xDC\xBA":
            out.append(("raw", bytes(data)))
            return out
        self.buf += data
        while len(self.buf) >= 7:
            if self.buf[:3] != b"\xFE\xDC\xBA":
                out.append(("raw", bytes(self.buf)))
                self.buf.clear()
                break
            ln = (self.buf[5] << 8) | self.buf[6]
            total = 7 + ln + 1
            if len(self.buf) < total:
                break
            pkt = parse_fedcba(bytes(self.buf[:total]))
            del self.buf[:total]
            out.append(("fedcba", pkt))
        return out


# --- opcodes -------------------------------------------------------------------------
OP_DATA = 0x01           # data container: payload [sn, sub-opcode, ...]
OP_CLOCK_READ = 0x07     # get sys info (RTC)
OP_CLOCK_SYNC = 0x08     # set sys info (RTC)
OP_BROWSE = 0x0C         # start file browse
OP_BROWSE_END = 0x0D     # device -> app, browse finished
OP_FILE_DECLARE = 0x1A   # prepare file write: size + '/'+name
OP_FILE_START = 0x1B     # start transfer: size, crc, tmp name
OP_STOP = 0x1C           # device -> app, transfer end / stop (reason in payload[1])
OP_BLOCK_REQ = 0x1D      # device -> app, "send me len bytes at offset"
OP_DELETE = 0x1F         # delete file by cluster
OP_FILE_DONE = 0x20      # device -> app, all bytes received; app answers with final name
OP_LOCK = 0x21           # [sn, 1]=begin / [sn, 0]=?  (used around writes)
OP_READ_FILE = 0x24      # read file by name; data comes as OP_DATA sub 0x24
OP_PREP = 0x27           # [sn,0,0,0,0,3,1] before OP_FILE_START
OP_D1 = 0xD1             # device -> app command during writes; ack [0, sn]


def browse_payload(sn: int, start: int) -> bytes:
    # decompiled.js 230188-230203 / 229137-229152 / 228196-228211
    return bytes([sn, 0x00, 0x0A, 0x00, start & 0xFF, 0, 0, 0, 0x03, 0x00, 0x04, 0, 0, 0, 0])


def parse_browse_entries(data_payload: bytes):
    """Parse an OP_DATA payload produced by OP_BROWSE. Entries start at index 2:
    [0x0F][cluster u32 BE][2 bytes ?][name_len][name ascii]. (229199-229285)"""
    out, i = [], 2
    p = data_payload
    while i < len(p) and p[i] == 0x0F:
        if i + 8 > len(p):
            break
        cluster = struct.unpack(">I", p[i + 1:i + 5])[0]
        nlen = p[i + 7]
        name = p[i + 8:i + 8 + nlen].decode("ascii", "replace")
        out.append((name, cluster))
        i += 8 + nlen
    return out


def ack(opcode: int, device_sn: int, extra: bytes = b"") -> bytes:
    return build_fedcba(FLAG_RESP, opcode, bytes([0x00, device_sn]) + extra)


# --------------------------------------------------------------------------------------
# Clock (decompiled.js 278425-278710, opcodes at 279170-279173)
# --------------------------------------------------------------------------------------
def build_clock_read(sn: int) -> bytes:
    return build_fedcba(FLAG_CMD, OP_CLOCK_READ, bytes([sn, 0x02, 0, 0, 0, 0x01]))


def build_clock_sync(sn: int, t) -> bytes:
    """t: datetime (local time)."""
    return build_fedcba(FLAG_CMD, OP_CLOCK_SYNC,
                        bytes([sn, 0x02, 0x08, 0x00, (t.year >> 8) & 0xFF, t.year & 0xFF,
                               t.month, t.day, t.hour, t.minute, t.second]))


def parse_clock_read(payload: bytes):
    """payload of the OP_CLOCK_READ response: [status, sn, 0x02, (len, type, data...)*]"""
    import datetime
    if payload[0] != 0:
        raise ValueError("status %d" % payload[0])
    if payload[2] != 2:
        raise ValueError("wrong function")
    i = 3
    while i < len(payload):
        ln = payload[i]
        if ln < 1 or i + ln >= len(payload):
            raise ValueError("malformed attribute")
        typ = payload[i + 1]
        if typ == 0 and ln == 8:
            d = payload[i + 2:i + 9]
            return datetime.datetime((d[0] << 8) | d[1], d[2], d[3], d[4], d[5], d[6])
        i += ln + 1
    raise ValueError("no RTC attribute")


# --------------------------------------------------------------------------------------
# DM.JSN (danmaku) - decompiled.js 240293-240376
# --------------------------------------------------------------------------------------
DEFAULT_REMINDERS = [("Remember to drink water", False), ("Sleep early", False),
                     ("Turn off lights and lock up", False)]


def build_dm_json(custom_items, reminders=DEFAULT_REMINDERS, period_ms: int = 5000,
                  color=(255, 255, 255)) -> str:
    """Array of {name,isOpen,isIP,period,color}. Custom items: isIP 0, always isOpen 1.
    The app always appends the 3 reminder entries (isIP 1) after the custom ones."""
    arr = [{"name": s, "isOpen": 1, "isIP": 0, "period": period_ms, "color": list(color)}
           for s in custom_items]
    for text, on in reminders:
        arr.append({"name": text, "isOpen": 1 if on else 0, "isIP": 1, "period": period_ms,
                    "color": list(color)})
    return json.dumps(arr, ensure_ascii=False, separators=(",", ":"))


def build_ba_json(face_id: str, name: str = "unknown", rcnt: int = 1, md5: str = "", edly: int = 0) -> str:
    """BA.JSN content (current face). For known faces the app reuses the KNOWN_FACES json
    (decompiled.js 276811+) and only rewrites rcnt (0..1000)."""
    return json.dumps({"name": name, "id": face_id, "md5": md5, "rcnt": rcnt, "edly": edly},
                      ensure_ascii=False, separators=(",", ":"))


# --------------------------------------------------------------------------------------
# RU30 / "BR28" image encoder (toBr28Ru30, decompiled.js 274272-274877)
# --------------------------------------------------------------------------------------
def encode_ru30(rgba: bytes, w: int, h: int) -> bytes:
    px = bytearray(w * h * 2)                 # RGB565, big-endian
    for i in range(w * h):
        r, g, b = rgba[4 * i], rgba[4 * i + 1], rgba[4 * i + 2]
        v = ((r << 8) & 0xF800) | ((g << 3) & 0x07E0) | (b >> 3)
        px[2 * i] = v >> 8
        px[2 * i + 1] = v & 0xFF

    def rd(o):
        return px[o] | (px[o + 1] << 8)

    def has_run(rem, start):
        first = rd(start); cnt = 0; pos = start
        while rem > 0:
            rem -= 1
            if rd(pos) == first:
                cnt += 1
                if cnt >= 3:
                    return True
            else:
                cnt = 0
            if (pos - start) // 2 >= 3:
                return False
            pos += 2
        return False

    def run_of(rem, start):
        first = rd(start); cnt = 0; pos = start
        while rem > 0:
            rem -= 1
            if rd(pos) != first:
                return cnt
            cnt += 1
            if cnt == 127:
                return 127
            pos += 2
        return cnt

    def lit_count(rem, start):
        prev = rd(start); run = 0; cnt = 0; pos = start
        while rem > 0:
            rem -= 1
            cur = rd(pos)
            if cur != prev:
                prev = cur; run = 1
            else:
                run += 1
                if run == 3:
                    return int(((pos + 2 - start) + 1 - run * 2) / 2)
            pos += 2
            cnt += 1
            if cnt == 127:
                return 127
        return (pos - start) // 2

    def rle_row(out, src, dst):
        rem, written = w, 0
        while rem > 0:
            if has_run(rem, src):
                n = run_of(rem, src)
                if out is not None:
                    out[dst + written] = 0x80 | n
                    out[dst + written + 1] = px[src]
                    out[dst + written + 2] = px[src + 1]
                written += 3
            else:
                n = lit_count(rem, src)
                if out is not None:
                    out[dst + written] = n
                    out[dst + written + 1: dst + written + 1 + 2 * n] = px[src:src + 2 * n]
                written += 1 + 2 * n
            src += 2 * n
            rem -= n
        return written

    table = 4 * h
    total = table + sum(rle_row(None, r * w * 2, 0) for r in range(h))
    blob = bytearray(total)
    data_off = 0
    for r in range(h):
        n = rle_row(blob, r * w * 2, table + data_off)
        entry = (((table + data_off) & 0x1FFFFF) | ((n & 0x7FF) << 21)) & 0xFFFFFFFF
        blob[4 * r:4 * r + 4] = struct.pack("<I", entry)
        data_off += n

    HDR = 1104
    out = bytearray(HDR + len(blob))
    out[0:4] = b"RU30"
    def u16(o, v): out[o:o + 2] = struct.pack("<H", v & 0xFFFF)
    def u32(o, v): out[o:o + 4] = struct.pack("<I", v & 0xFFFFFFFF)
    u16(4, 768); u16(6, 1); u16(8, 1); u16(10, 0); u32(12, 0); u32(16, 0); u32(20, 24); u32(24, 48)
    u16(28, 1); out[30] = ord("T"); out[31] = 0; u32(32, 0); u32(36, 60)
    u16(40, 1); out[42] = ord("P"); out[43] = 0; u32(44, 0); u32(48, 256); u32(52, 80); u32(56, 1024)
    u16(60, 0); u16(62, crc16_jl(bytes(blob))); u16(64, 0); u16(66, 9217); u16(68, w); u16(70, h)
    u32(72, len(blob)); u32(76, HDR)
    u16(60, crc16_jl(bytes(out[62:80])))
    out[HDR:] = blob
    return bytes(out)


def encode_image_file(path: str, w: int = 296, h: int = 240) -> bytes:
    from PIL import Image, ImageOps
    im = ImageOps.fit(Image.open(path).convert("RGBA"), (w, h))
    return encode_ru30(im.tobytes(), w, h)


# --------------------------------------------------------------------------------------
# Async bleak client
# --------------------------------------------------------------------------------------
class CubeError(Exception):
    pass


class CubeClient:
    """Talks RCSP to the JieLi ("headphone") side of the cube over service ae00.

    usage:
        async with CubeClient(address_or_BLEDevice) as c:
            print(await c.read_clock())
            await c.set_danmaku(["5h 42% / 7d 18%"])
    """

    def __init__(self, device, log: Callable[[str], None] = print, chunk: Optional[int] = None):
        self.device = device
        self.log = log
        self.client = None
        self.sn = random.randint(0, 255)
        self._chunk = chunk
        self._reasm = Reassembler()
        self._queues: dict[int, asyncio.Queue] = {}
        self._auth_q: asyncio.Queue = asyncio.Queue()
        self._data_sink: Optional[Callable[[Packet], bool]] = None

    # ---- plumbing ----
    def _q(self, opcode):
        return self._queues.setdefault(opcode, asyncio.Queue())

    def _nc(self):
        s = self.sn
        self.sn = (self.sn + 1) & 0xFF
        return s

    def _on_notify(self, _h, data: bytearray):
        self.log("<- ae02 " + bytes(data).hex())
        for kind, item in self._reasm.feed(bytes(data)):
            if kind == "raw":
                self._auth_q.put_nowait(item)
            else:
                if item.opcode == OP_DATA and self._data_sink and self._data_sink(item):
                    continue
                self._q(item.opcode).put_nowait(item)

    async def _write(self, data: bytes):
        self.log("-> ae01 " + data.hex())
        n = self._chunk or 20
        for i in range(0, len(data), n):
            await self.client.write_gatt_char(self._ae01, data[i:i + n], response=False)

    async def wait(self, opcode: int, timeout: float = 15.0, cmd: Optional[bool] = None) -> Packet:
        q = self._q(opcode)
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while True:
            left = end - loop.time()
            if left <= 0:
                raise CubeError("timeout waiting for opcode 0x%02x" % opcode)
            try:
                p = await asyncio.wait_for(q.get(), left)
            except asyncio.TimeoutError:
                raise CubeError("timeout waiting for opcode 0x%02x" % opcode)
            if cmd is None or p.is_command == cmd:
                return p

    def drain(self, opcode):
        q = self._q(opcode)
        while not q.empty():
            q.get_nowait()

    async def command(self, opcode: int, body: bytes = b"", wait: bool = True, timeout: float = 15.0):
        """Send [sn]+body with flag 0xC0 and wait for the response (flag 0x00) with that opcode."""
        sn = self._nc()
        self.drain(opcode)
        await self._write(build_fedcba(FLAG_CMD, opcode, bytes([sn]) + body))
        if not wait:
            return None
        p = await self.wait(opcode, timeout, cmd=False)
        if len(p.payload) >= 1 and p.payload[0] != 0:
            self.log("warning: opcode 0x%02x status 0x%02x" % (opcode, p.payload[0]))
        return p

    # ---- lifecycle ----
    async def connect(self):
        from bleak import BleakClient
        self.client = BleakClient(self.device)
        await self.client.connect()
        # ae01/ae02 can exist in more than one service; pick the ones inside ae00
        svc = self.client.services.get_service(SVC_AE00)
        if svc is None:
            raise CubeError("device has no ae00 service")
        self._ae01 = svc.get_characteristic(CHR_AE01)
        self._ae02 = svc.get_characteristic(CHR_AE02)
        if self._chunk is None:
            try:
                ch = self._ae01
                self._chunk = max(20, ch.max_write_without_response_size)
            except Exception:
                self._chunk = max(20, getattr(self.client, "mtu_size", 23) - 3)
        await self.client.start_notify(self._ae02, self._on_notify)
        await self.authenticate()

    async def disconnect(self):
        if self.client:
            await self.client.disconnect()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *a):
        await self.disconnect()

    async def authenticate(self, timeout: float = 10.0):
        nonce = os.urandom(16)
        await self._write(auth_nonce_packet(nonce))
        answered = False
        while True:
            try:
                pkt = await asyncio.wait_for(self._auth_q.get(), timeout)
            except asyncio.TimeoutError:
                raise CubeError("auth ae02 timeout")
            if pkt == AUTH_PASS and answered:
                self.log("auth complete")
                return
            if len(pkt) == 17 and pkt[0] == 0x00:
                await self._write(et_cipher(pkt[1:]))
                answered = True
            elif len(pkt) == 17 and pkt[0] == 0x01:
                await self._write(AUTH_PASS)
            else:
                raise CubeError("auth failed - unexpected packet " + pkt.hex())

    # ---- smoke tests ----
    async def read_clock(self):
        sn = self._nc()
        self.drain(OP_CLOCK_READ)
        await self._write(build_clock_read(sn))
        p = await self.wait(OP_CLOCK_READ, 8, cmd=False)
        return parse_clock_read(p.payload)

    async def sync_clock(self, t=None):
        import datetime
        t = t or datetime.datetime.now()
        sn = self._nc()
        self.drain(OP_CLOCK_SYNC)
        await self._write(build_clock_sync(sn, t))
        p = await self.wait(OP_CLOCK_SYNC, 8, cmd=False)
        if p.payload[0] != 0:
            raise CubeError("clock sync status %d" % p.payload[0])

    # ---- file system ----
    async def list_root(self, starts=(1, 11, 21, 31, 41)):
        files = []
        for st in starts:
            self.drain(OP_DATA); self.drain(OP_BROWSE_END)
            sn = self._nc()
            await self._write(build_fedcba(FLAG_CMD, OP_BROWSE, browse_payload(sn, st)))
            try:
                data = await self.wait(OP_DATA, 5)
            except CubeError:
                data = None
            end = await self.wait(OP_BROWSE_END, 5)
            await self._write(ack(OP_BROWSE_END, end.payload[0]))
            if data:
                files += parse_browse_entries(data.payload)
        return files

    async def find_cluster(self, name: str) -> Optional[int]:
        for st in (1, 11, 21, 31, 41):
            for n, cl in await self.list_root((st,)):
                if n == name:
                    return cl
        return None

    async def read_file(self, name: str) -> Optional[bytes]:
        nb = name.encode()
        chunks = {}

        def sink(p: Packet):
            pl = p.payload
            if len(pl) >= 8 and pl[1] == OP_READ_FILE:
                off = struct.unpack(">I", pl[2:6])[0]
                chunks.setdefault(off, pl[8:])
                return True
            return False

        self._data_sink = sink
        try:
            self.drain(OP_READ_FILE)
            sn = self._nc()
            await self._write(build_fedcba(FLAG_CMD, OP_READ_FILE,
                                           bytes([sn, 0x02, 0, 0, 0, 0x03, 0, 0, 0, 0, len(nb)]) + nb))
            r = await self.wait(OP_READ_FILE, 8, cmd=False)
            size = struct.unpack(">I", r.payload[3:7])[0] if len(r.payload) >= 7 else 0
            if size == 0:
                return None
            end = await self.wait(OP_READ_FILE, 15, cmd=True)
            await self._write(build_fedcba(FLAG_RESP, OP_READ_FILE, bytes([0, end.payload[0], 0x80])))
        finally:
            self._data_sink = None
        data = b"".join(chunks[k] for k in sorted(chunks))
        if len(data) < size:
            raise CubeError("short read %d/%d" % (len(data), size))
        return data[:size]

    async def write_file(self, name: str, data: bytes):
        """Sequence of _closure2_slot138 (decompiled.js 228941-230041)."""
        nb = name.encode()
        size = len(data)
        crc = crc16_jl(data)
        tmp = ("%08x" % random.getrandbits(32)).encode() + b".tmp\x00"
        cluster = await self.find_cluster(name)
        self.drain(OP_D1)
        if cluster is not None:
            self.log("%s exists at cluster 0x%x, deleting" % (name, cluster))
            await self.command(OP_LOCK, bytes([1]))
            await self.command(OP_DELETE, bytes([1, 0, 0, 0, 3, 1]) + struct.pack(">I", cluster))
            await asyncio.sleep(0.15)
        await self.command(OP_FILE_DECLARE, bytes([0x02, 0x01]) + struct.pack(">I", size & 0xFFFFFF) + b"/" + nb)
        await self.command(OP_LOCK, bytes([0]))
        d1 = await self.wait(OP_D1, 15, cmd=True)
        self.drain(OP_PREP)
        sn = self._nc()
        await self._write(build_fedcba(FLAG_CMD, OP_PREP, bytes([sn, 0, 0, 0, 0, 3, 1])))
        await self._write(ack(OP_D1, d1.payload[0]))
        await self.wait(OP_PREP, 15, cmd=False)
        for op in (OP_BLOCK_REQ, OP_FILE_DONE, OP_STOP):
            self.drain(op)
        await self.command(OP_FILE_START, bytes([0x00]) + struct.pack(">I", size)[1:] +
                           struct.pack(">H", crc) + tmp)
        blocks = 0
        while True:
            waits = {asyncio.ensure_future(self.wait(op, 30, cmd=True)): op
                     for op in (OP_BLOCK_REQ, OP_FILE_DONE, OP_STOP)}
            done, pending = await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
            for f in pending:
                f.cancel()
            f = next(iter(done))
            op = waits[f]
            p = f.result()  # raises on timeout
            pl = p.payload
            if op == OP_BLOCK_REQ:
                ln = (pl[2] << 8) | pl[3]
                off = struct.unpack(">I", pl[4:8])[0]
                blk = data[off:min(off + ln, size)]
                blocks += 1
                self.log("block %d off=%d len=%d" % (blocks, off, len(blk)))
                if blk:
                    c = crc16_jl(blk)
                    await self._write(build_fedcba(FLAG_CMD_NORESP, OP_DATA,
                                                   bytes([self._nc(), OP_BLOCK_REQ, 0, c >> 8, c & 0xFF]) + blk))
                else:
                    await self._write(build_fedcba(FLAG_CMD_NORESP, OP_DATA,
                                                   bytes([self._nc(), OP_BLOCK_REQ, 0, 0, 0])))
            elif op == OP_STOP:
                await self._write(ack(OP_STOP, pl[0]))
                raise CubeError("device STOP reason=%s" % (pl[1] if len(pl) > 1 else "?"))
            else:  # OP_FILE_DONE -> answer with final name, then wait OP_STOP
                await self._write(ack(OP_FILE_DONE, pl[0], nb + b"\x00\x00"))
                stop = await self.wait(OP_STOP, 15, cmd=True)
                await self._write(ack(OP_STOP, stop.payload[0]))
                self.log("%s saved (%d B)" % (name, size))
                return

    # ---- features ----
    async def get_danmaku(self):
        raw = await self.read_file("DM.JSN") or await self.read_file("DM_.JSN")
        return json.loads(raw.decode("utf-8")) if raw else None

    async def set_danmaku(self, texts, reminders=DEFAULT_REMINDERS, period_ms=5000, color=(255, 255, 255)):
        await self.write_file("DM.JSN", build_dm_json(texts, reminders, period_ms, color).encode("utf-8"))

    async def read_flags(self):
        a = await self.client.read_gatt_char(CHR_D101)
        b = await self.client.read_gatt_char(CHR_D103)
        return {"musicSync": bool(a and a[0]), "largeText": bool(b and b[0])}

    async def set_flags(self, music_sync: Optional[bool] = None, large_text: Optional[bool] = None):
        if music_sync is not None:
            await self.client.write_gatt_char(CHR_D102, bytes([1 if music_sync else 0]), response=True)
        if large_text is not None:
            await self.client.write_gatt_char(CHR_D104, bytes([1 if large_text else 0]), response=True)

    async def set_face(self, face_id: str, name: str = "unknown", rcnt: int = 1, json_text: Optional[str] = None):
        js = json_text or build_ba_json(face_id, name, rcnt)
        if json_text:
            d = json.loads(json_text); d["rcnt"] = rcnt
            js = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
        await self.write_file("BA.JSN", js.encode("utf-8"))

    async def upload_custom_face(self, image_path: str):
        await self.write_file("10000001.RES", encode_image_file(image_path))
        await self.set_face("10000001.RES", json_text='{"name":"自定义背景","id":"10000001.RES","md5":"","rcnt":1,"edly":0}')


# --------------------------------------------------------------------------------------
# Discovery helpers
# --------------------------------------------------------------------------------------
def parse_headphone_mac(d106_value: bytes) -> Optional[str]:
    """parseHeadphoneMac (decompiled.js 276301-276331): first 6 bytes of d106, as AA:BB:..."""
    if len(d106_value) < 6:
        return None
    return ":".join("%02X" % b for b in d106_value[:6])


async def read_headphone_mac(cube_device, timeout=6.0) -> Optional[str]:
    """Connect to the 'Hatsune Miku CUBEFACE' (d100) peripheral and read d106."""
    from bleak import BleakClient
    async with BleakClient(cube_device) as c:
        try:
            mac = parse_headphone_mac(bytes(await c.read_gatt_char(CHR_D106)))
            if mac:
                return mac
        except Exception:
            pass
        # on macOS the read often comes back empty; the value does arrive as a notification
        got = asyncio.get_running_loop().create_future()
        await c.start_notify(CHR_D106, lambda _h, d: got.done() or got.set_result(bytes(d)))
        return parse_headphone_mac(await asyncio.wait_for(got, timeout))


async def scan_candidates(mac: Optional[str] = None, seconds=8.0):
    """List advertisers that look like the JieLi side (ae00 in adv, or MAC bytes in mfr data)."""
    from bleak import BleakScanner
    found = await BleakScanner.discover(timeout=seconds, return_adv=True)
    macb = bytes.fromhex(mac.replace(":", "")) if mac else None
    out = []
    for dev, adv in found.values():
        uu = [u.lower() for u in (adv.service_uuids or [])]
        hit = any("ae00" in u[:8] or "b1b1" in u for u in uu)
        md = b"".join(bytes(v) for v in (adv.manufacturer_data or {}).values())
        if macb and (macb in md or macb[::-1] in md):
            hit = True
        if hit or (adv.local_name and ("miku" in adv.local_name.lower() or "cube" in adv.local_name.lower())):
            out.append((dev, adv))
    return out


# --------------------------------------------------------------------------------------
def _selftest():
    import binascii
    for s in (b"", b"123456789", "弹幕".encode()):
        assert crc16_jl(s) == binascii.crc_hqx(s, 0)
    assert crc16_jl(b"123456789") == 0x31C3
    # Bluetooth Core spec E1 sample (all-zero key/rand/address): SRES = 056c0fe6, ACO = 48afcdd4bd40fef76693b113
    out = et_cipher(bytes(16), key=bytes(16), addr=bytes(6))
    print("E1(0,0,0) =", out[1:].hex())
    assert out[0] == 1 and out[1:].hex() == "056c0fe648afcdd4bd40fef76693b113"
    import datetime
    assert parse_clock_read(bytes([0, 5, 2, 8, 0, 0x07, 0xE9, 11, 10, 18, 30, 5])) == datetime.datetime(2025, 11, 10, 18, 30, 5)
    assert build_fedcba(0, 0x0D, bytes([0, 0x10])).hex() == "fedcba000d00020010ef"
    p = parse_fedcba(bytes.fromhex("FEDCBA000D00020010EF"))
    assert p.opcode == 0x0D and p.payload == b"\x00\x10"
    img = encode_ru30(bytes([255, 0, 0, 255]) * (8 * 4), 8, 4)
    assert img[:4] == b"RU30" and len(img) > 1104
    print("DM.JSN example:", build_dm_json(["5h 42% / 7d 18%"]))
    print("auth reply example:", et_cipher(bytes(range(16))).hex())
    print("selftest ok")


if __name__ == "__main__":
    _selftest()
