import pytest

from birthdaybot.media import MAX_VIDEO_BYTES, validate_metadata, validate_video


def test_video_metadata():
    assert validate_metadata("party.MP4", MAX_VIDEO_BYTES, "video/mp4") == ".mp4"
    for name, size, mime in [
        ("party.mp4", MAX_VIDEO_BYTES + 1, "video/mp4"),
        ("party.mp4", 0, "video/mp4"),
        ("party.exe", 10, "video/mp4"),
        ("party.mp4", 10, "text/html"),
    ]:
        with pytest.raises(ValueError):
            validate_metadata(name, size, mime)


def test_video_signatures():
    validate_video(b"\x00\x00\x00\x18ftypisom", ".mp4")
    validate_video(b"\x1aE\xdf\xa3webm", ".webm")
    with pytest.raises(ValueError):
        validate_video(b"<html>not a video</html>", ".mp4")
    with pytest.raises(ValueError):
        validate_video(b"", ".webm")
