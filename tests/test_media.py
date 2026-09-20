import pytest

from birthdaybot.media import MAX_MEDIA_BYTES, validate_media, validate_metadata


def test_media_metadata():
    assert validate_metadata("party.MP4", MAX_MEDIA_BYTES, "video/mp4") == ".mp4"
    assert validate_metadata("photo.JPG", MAX_MEDIA_BYTES, "image/jpeg") == ".jpg"
    for name, size, mime in [
        ("party.mp4", MAX_MEDIA_BYTES + 1, "video/mp4"),
        ("party.mp4", 0, "video/mp4"),
        ("party.exe", 10, "video/mp4"),
        ("party.mp4", 10, "text/html"),
        ("photo.jpg", 10, "video/mp4"),
    ]:
        with pytest.raises(ValueError):
            validate_metadata(name, size, mime)


def test_media_signatures():
    validate_media(b"\x00\x00\x00\x18ftypisom", ".mp4")
    validate_media(b"\x1aE\xdf\xa3webm", ".webm")
    validate_media(b"\x89PNG\r\n\x1a\ncontents", ".png")
    validate_media(b"\xff\xd8\xffcontents", ".jpeg")
    validate_media(b"GIF89acontents", ".gif")
    validate_media(b"RIFF\x00\x00\x00\x00WEBPcontents", ".webp")
    with pytest.raises(ValueError):
        validate_media(b"<html>not media</html>", ".mp4")
    with pytest.raises(ValueError):
        validate_media(b"", ".webm")
