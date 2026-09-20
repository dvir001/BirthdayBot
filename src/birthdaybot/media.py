from pathlib import PurePath

MAX_MEDIA_BYTES = 10_000_000
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


def parse_media_limit(value: str | None) -> int:
    try:
        limit = MAX_MEDIA_BYTES if value is None else int(value)
    except ValueError as error:
        raise ValueError("MAX_MEDIA_BYTES must be an integer") from error
    if not 0 < limit <= MAX_MEDIA_BYTES:
        raise ValueError(f"MAX_MEDIA_BYTES must be between 1 and {MAX_MEDIA_BYTES}")
    return limit


def validate_metadata(
    filename: str, size: int, content_type: str | None, max_bytes: int = MAX_MEDIA_BYTES
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


def validate_media(data: bytes, extension: str, max_bytes: int = MAX_MEDIA_BYTES) -> None:
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
