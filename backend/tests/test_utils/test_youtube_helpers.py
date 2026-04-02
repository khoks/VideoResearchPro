from app.utils.youtube_helpers import (
    build_youtube_url,
    extract_channel_handle,
    extract_channel_id,
    extract_video_id,
    format_duration,
    format_timestamp,
    parse_iso8601_duration,
)


def test_extract_video_id_standard():
    assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_video_id_short():
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_video_id_embed():
    assert extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_video_id_bare():
    assert extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_video_id_invalid():
    assert extract_video_id("not-a-url") is None


def test_extract_channel_id():
    assert extract_channel_id("https://www.youtube.com/channel/UCshort") is None
    url = "https://www.youtube.com/channel/UC" + "a" * 22
    assert extract_channel_id(url) == "UC" + "a" * 22


def test_extract_channel_handle():
    assert extract_channel_handle("https://www.youtube.com/@3blue1brown") == "3blue1brown"
    assert extract_channel_handle("@Veritasium") == "Veritasium"


def test_build_youtube_url():
    assert build_youtube_url("abc123") == "https://www.youtube.com/watch?v=abc123"
    assert build_youtube_url("abc123", 90) == "https://www.youtube.com/watch?v=abc123&t=90"


def test_format_duration():
    assert format_duration(90) == "1:30"
    assert format_duration(3661) == "1:01:01"


def test_format_timestamp():
    assert format_timestamp(90.5) == "1:30"
    assert format_timestamp(3661.0) == "1:01:01"


def test_parse_iso8601_duration():
    assert parse_iso8601_duration("PT1H2M3S") == 3723
    assert parse_iso8601_duration("PT5M") == 300
    assert parse_iso8601_duration("PT30S") == 30
    assert parse_iso8601_duration("PT1H") == 3600
