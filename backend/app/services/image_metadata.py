"""Removing metadata from photos before they leave the server.

Photos taken by a phone carry EXIF/XMP: GPS coordinates, device model, time. The
recognition provider needs only the pixels, so these segments are cut out of the
container without decoding or re-encoding the image.
"""

from __future__ import annotations

import struct


class UnsupportedImage(ValueError):
    """The bytes are not a well-formed image of the declared type."""


# JPEG markers kept as is: JFIF header (APP0), ICC colour profile (APP2), Adobe
# colour transform (APP14). APP1 (EXIF, XMP), APP13 (IPTC), other APPn and
# comments (COM) are dropped.
_JPEG_KEEP_APP = {0xE0, 0xE2, 0xEE}


def _strip_jpeg(data: bytes) -> bytes:
    if data[:2] != b"\xff\xd8":
        raise UnsupportedImage("not a JPEG")
    out = bytearray(b"\xff\xd8")
    pos = 2
    while pos < len(data):
        if data[pos] != 0xFF:
            raise UnsupportedImage("broken JPEG marker")
        marker = data[pos + 1] if pos + 1 < len(data) else None
        if marker is None:
            raise UnsupportedImage("truncated JPEG")
        if marker == 0xFF:  # fill byte
            pos += 1
            continue
        if marker == 0xDA:  # start of scan: the rest is image data
            out += data[pos:]
            return bytes(out)
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            out += data[pos : pos + 2]
            pos += 2
            continue
        if pos + 4 > len(data):
            raise UnsupportedImage("truncated JPEG segment")
        (length,) = struct.unpack(">H", data[pos + 2 : pos + 4])
        end = pos + 2 + length
        if length < 2 or end > len(data):
            raise UnsupportedImage("broken JPEG segment")
        is_app = 0xE0 <= marker <= 0xEF
        if not (marker == 0xFE or (is_app and marker not in _JPEG_KEEP_APP)):
            out += data[pos:end]
        pos = end
    raise UnsupportedImage("JPEG without image data")


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_DROP = {b"eXIf", b"tEXt", b"zTXt", b"iTXt", b"tIME"}


def _strip_png(data: bytes) -> bytes:
    if not data.startswith(_PNG_SIGNATURE):
        raise UnsupportedImage("not a PNG")
    out = bytearray(_PNG_SIGNATURE)
    pos = len(_PNG_SIGNATURE)
    while pos < len(data):
        if pos + 8 > len(data):
            raise UnsupportedImage("truncated PNG chunk")
        length, kind = struct.unpack(">I4s", data[pos : pos + 8])
        end = pos + 12 + length
        if end > len(data):
            raise UnsupportedImage("broken PNG chunk")
        if kind not in _PNG_DROP:
            out += data[pos:end]
        pos = end
        if kind == b"IEND":
            return bytes(out)
    raise UnsupportedImage("PNG without IEND")


_VP8X_EXIF = 0x08
_VP8X_XMP = 0x04


def _strip_webp(data: bytes) -> bytes:
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise UnsupportedImage("not a WebP")
    chunks = bytearray()
    pos = 12
    while pos < len(data):
        if pos + 8 > len(data):
            raise UnsupportedImage("truncated WebP chunk")
        kind = data[pos : pos + 4]
        (length,) = struct.unpack("<I", data[pos + 4 : pos + 8])
        end = pos + 8 + length + (length & 1)
        if end > len(data) + (length & 1):
            raise UnsupportedImage("broken WebP chunk")
        chunk = bytearray(data[pos:end])
        if kind == b"VP8X" and len(chunk) > 8:
            chunk[8] &= ~(_VP8X_EXIF | _VP8X_XMP) & 0xFF
        if kind not in (b"EXIF", b"XMP "):
            chunks += chunk
        pos = end
    return b"RIFF" + struct.pack("<I", len(chunks) + 4) + b"WEBP" + bytes(chunks)


_STRIPPERS = {"image/jpeg": _strip_jpeg, "image/png": _strip_png, "image/webp": _strip_webp}

#: Types whose metadata can be removed; others are refused rather than sent as is.
SUPPORTED_TYPES = frozenset(_STRIPPERS)


def strip_metadata(data: bytes, content_type: str) -> bytes:
    """The same image without EXIF/XMP/IPTC/text metadata."""
    stripper = _STRIPPERS.get(content_type)
    if stripper is None:
        raise UnsupportedImage(f"unsupported type {content_type}")
    return stripper(data)
