# SPDX-License-Identifier: MIT
"""Bounded DxLib MED archive reader and template-preserving writer.

Two container profiles share one index/header layout and differ only in how the
member bytes are stored:

``mdn0-plain-v1``
    ``MDN0`` magic, plaintext members.
``mde0-additive-member-v1``
    ``MDE0`` magic, every member coded with a caller-supplied byte key
    (additive per member, first 16 bytes untouched, phase counted from the
    first coded byte). The key is never guessed or bundled here.

The index entry width comes from the header and the last eight bytes of each
entry are always ``u32 stored length`` then ``u32 absolute offset``. Wider
entries (for example 26-byte entries with a 14-byte name slot) carry an extra
undocumented ``u32`` before the length, which stays inside the name slot read
below and is preserved verbatim by the writer.

Index layout adapted from GARbro ArcFormats/DxLib/ArcMED.cs.
Copyright (C) 2016 by morkt

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""
from dataclasses import dataclass
import io
from pathlib import Path
import stat
import struct

from ..common.binary import FormatError
from ..common.safety import _check_existing_ancestors, validate_names

MAX_ARCHIVE = 64 << 20
MAX_MEMBER = 8 << 20
MAX_ENTRIES = 4096

PLAIN_PROFILE = "mdn0-plain-v1"
ENCRYPTED_PROFILE = "mde0-additive-member-v1"
MAGICS = {b"MDN0": PLAIN_PROFILE, b"MDE0": ENCRYPTED_PROFILE}
#: First member offset that a coded member leaves unmodified.
MEMBER_KEY_BASE = 0x10


@dataclass(frozen=True)
class Entry:
    name: str
    offset: int
    size: int
    slot: int


def profile(head):
    """Return the container profile id of an archive head; magic decides coding."""
    try:
        return MAGICS[bytes(head[:4])]
    except KeyError:
        raise FormatError("expected a DxLib MED archive (MDN0 or MDE0)") from None


def check_key(key):
    """Validate an explicit member key; this module never derives or stores one."""
    if not isinstance(key, (bytes, bytearray)) or not 0 < len(key) <= 256:
        raise FormatError("MED member key must be an explicit 1..256 byte key")
    return bytes(key)


def transform_member(data, key, *, encrypt=False):
    """Code one member with the additive member schedule.

    The first 16 bytes of a member are untouched. For every later member
    offset ``p`` the schedule index is ``(p - 0x10) % len(key)``: the phase is
    counted from the first coded byte, not from the member start. Using
    ``p % len(key)`` instead shifts every member and yields plausible-looking
    garbage, so keep the subtraction.
    """
    key = check_key(key)
    if len(data) < MEMBER_KEY_BASE:
        raise FormatError("MED member shorter than its untouched header")
    out = bytearray(data[:MEMBER_KEY_BASE])
    for p in range(MEMBER_KEY_BASE, len(data)):
        toggle = key[(p - MEMBER_KEY_BASE) % len(key)]
        out.append((data[p] - toggle) & 0xFF if encrypt else (data[p] + toggle) & 0xFF)
    return bytes(out)


def index(stream, size):
    """Read only header/index, validate all ranges before reading any payload."""
    if not 16 <= size <= MAX_ARCHIVE:
        raise FormatError("MED archive size outside budget")
    stream.seek(0)
    header = stream.read(16)
    profile(header)
    width, count = struct.unpack_from("<HH", header, 4)
    if not 9 <= width <= 1024 or not 1 <= count <= MAX_ENTRIES:
        raise FormatError("MED index dimensions outside budget")
    end = 16 + width * count
    if end > size:
        raise FormatError("truncated MED index")
    table = stream.read(end - 16)
    if len(table) != end - 16:
        raise FormatError("truncated MED index")
    entries = []
    for i in range(count):
        slot = i * width
        raw_name = table[slot:slot + width - 8].split(b"\0", 1)[0]
        try:
            name = raw_name.decode("cp932", "strict")
        except UnicodeError as exc:
            raise FormatError("invalid MED member name encoding") from exc
        length, offset = struct.unpack_from("<II", table, slot + width - 8)
        if length > MAX_MEMBER or offset < end or offset + length > size:
            raise FormatError(f"MED member range/budget: {name}")
        entries.append(Entry(name, offset, length, 16 + slot + width - 8))
    names = [e.name for e in entries]
    if validate_names(names) != names or any("/" in n or "\\" in n for n in names):
        raise FormatError("MED requires unique flat member names")
    last = end
    for e in sorted(entries, key=lambda e: e.offset):
        if e.offset < last:
            raise FormatError("overlapping MED members")
        last = e.offset + e.size
    return entries


def read_member(stream, entry, key=None):
    """Read one member; pass the member key for an MDE0 container to decode it."""
    if not 0 <= entry.size <= MAX_MEMBER or entry.offset < 16:
        raise FormatError("invalid MED member range")
    stream.seek(entry.offset)
    data = stream.read(entry.size)
    if len(data) != entry.size:
        raise FormatError("truncated MED member")
    return data if key is None else transform_member(data, key)


def read_archive(path):
    path = Path(path)
    _check_existing_ancestors(path.parent)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or getattr(info, "st_file_attributes", 0) & 0x400:
        raise FormatError("MED input must be an ordinary unlinked file")
    with path.open("rb") as stream:
        entries = index(stream, info.st_size)
        stream.seek(0)
        data = stream.read(MAX_ARCHIVE + 1)
    if len(data) != info.st_size:
        raise FormatError("MED input size changed")
    if index(io.BytesIO(data), len(data)) != entries:
        raise FormatError("MED index changed during read")
    return data, entries


def rebuild(data, replacements, key=None):
    """Write replacements; ``key`` re-codes them for an MDE0 container."""
    entries = index(io.BytesIO(data), len(data))
    coded = profile(data) == ENCRYPTED_PROFILE
    if key is not None and not coded:
        raise FormatError("member key given for a plaintext MDN0 archive")
    if key is None and coded and replacements:
        raise FormatError("MDE0 replacements need the explicit member key")
    if set(replacements) - {e.name for e in entries}:
        raise FormatError("unknown MED replacement member")
    total = len(data)
    for e in entries:
        value = replacements.get(e.name)
        if value is not None:
            if not isinstance(value, bytes) or len(value) > MAX_MEMBER:
                raise FormatError("MED replacement exceeds budget")
            total += len(value) - e.size
        elif e.name in replacements:
            raise FormatError("MED replacement must be bytes")
    if total > MAX_ARCHIVE:
        raise FormatError("rebuilt MED exceeds budget")
    if coded and replacements:
        check_key(key)

    def stored(name, raw):
        value = replacements.get(name)
        if value is None:
            return raw
        return transform_member(value, key, encrypt=True) if coded else value

    # Preserve physical order, index order, name padding, gaps and trailer.
    out = bytearray()
    cursor = 0
    for e in sorted(entries, key=lambda e: e.offset):
        out.extend(data[cursor:e.offset])
        position = len(out)
        value = stored(e.name, data[e.offset:e.offset + e.size])
        out.extend(value)
        struct.pack_into("<II", out, e.slot, len(value), position)
        cursor = e.offset + e.size
    out.extend(data[cursor:])
    result = bytes(out)
    after = index(io.BytesIO(result), len(result))
    for old, new in zip(entries, after):
        expected = stored(old.name, data[old.offset:old.offset + old.size])
        actual = result[new.offset:new.offset + new.size]
        if actual != expected:
            raise FormatError("MED rebuilt member mismatch")
        if coded and old.name in replacements:
            if transform_member(actual, key) != replacements[old.name]:
                raise FormatError("MED rebuilt member does not decode to the replacement")
    return result
