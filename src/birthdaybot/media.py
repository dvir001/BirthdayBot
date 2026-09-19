from pathlib import PurePath

MAX_VIDEO_BYTES = 10_000_000
EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".mpeg", ".mpg", ".ogv"}


def validate_metadata(filename: str, size: int, content_type: str | None) -> str:
    extension = PurePath(filename).suffix.lower()
    if not 0 < size <= MAX_VIDEO_BYTES:
        raise ValueError("error.video_size")
    if extension not in EXTENSIONS or (
        content_type
        and not content_type.startswith("video/")
        and content_type != "application/octet-stream"
    ):
        raise ValueError("error.video_type")
    return extension


def validate_video(data: bytes, extension: str) -> None:
    if not 0 < len(data) <= MAX_VIDEO_BYTES:
        raise ValueError("error.video_size")
    valid = {
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
        raise ValueError("error.video_type")
