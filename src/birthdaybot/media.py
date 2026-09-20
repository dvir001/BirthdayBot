from pathlib import PurePath

BYTES_PER_MB = 1_000_000
DEFAULT_MAX_MEDIA_MB = 10
DEFAULT_MAX_MEDIA_BYTES = DEFAULT_MAX_MEDIA_MB * BYTES_PER_MB
MEDIA_TYPES = {
    ".avi": "video",
    ".gif": "image",
    ".jpeg": "image",
    ".jpg": "image",
    ".mkv": "video",
    ".mov": "video",
    ".mp4": "video",
    ".mpeg": "video",
    ".mpg": "video",
    ".ogv": "video",
    ".png": "image",
    ".webm": "video",
    ".webp": "image",
}


def parse_media_limit_mb(value: str | None) -> int:
    try:
        limit = DEFAULT_MAX_MEDIA_MB if value is None else int(value)
    except ValueError as error:
        raise ValueError("MAX_MEDIA_MB must be a whole number") from error
    if limit <= 0:
        raise ValueError("MAX_MEDIA_MB must be greater than zero")
    return limit


def validate_metadata(
    filename: str,
    size: int,
    content_type: str | None,
    max_bytes: int = DEFAULT_MAX_MEDIA_BYTES,
) -> str:
    extension = PurePath(filename).suffix.lower()
    if not 0 < size <= max_bytes:
        raise ValueError("error.media_size")
    media_type = MEDIA_TYPES.get(extension)
    if media_type is None or (
        content_type
        and not content_type.startswith(f"{media_type}/")
        and content_type != "application/octet-stream"
    ):
        raise ValueError("error.media_type")
    return extension


def validate_media(data: bytes, extension: str, max_bytes: int = DEFAULT_MAX_MEDIA_BYTES) -> None:
    if not 0 < len(data) <= max_bytes:
        raise ValueError("error.media_size")
    valid = {
        ".jpg": data.startswith(b"\xff\xd8\xff"),
        ".jpeg": data.startswith(b"\xff\xd8\xff"),
        ".png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        ".gif": data.startswith((b"GIF87a", b"GIF89a")),
        ".webp": data.startswith(b"RIFF") and data[8:12] == b"WEBP",
        ".mp4": data[4:8] == b"ftyp",
        ".mov": data[4:8] in (b"ftyp", b"moov", b"mdat", b"wide"),
        ".webm": data.startswith(b"\x1aE\xdf\xa3"),
        ".mkv": data.startswith(b"\x1aE\xdf\xa3"),
        ".avi": data.startswith(b"RIFF") and data[8:12] == b"AVI ",
        ".mpeg": data.startswith((b"\x00\x00\x01\xba", b"\x00\x00\x01\xb3")),
        ".mpg": data.startswith((b"\x00\x00\x01\xba", b"\x00\x00\x01\xb3")),
        ".ogv": data.startswith(b"OggS") and b"theora" in data[:256],
    }.get(extension, False)
    if not valid:
        raise ValueError("error.media_type")
