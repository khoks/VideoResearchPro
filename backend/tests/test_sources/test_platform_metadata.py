"""T-1.5.8.4: who posted a pasted social page, and when, from the page's own
metadata and its address.

Every page here is a small fixture written for the test, and every name in
it is invented (the repository is public, D-087). No network.
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone

import pytest

from app.sources.paste_url import platform_metadata
from app.sources.paste_url.platform_metadata import PostMetadata, read

UTC = timezone.utc

# An X status id for 2024-03-05 10:20:30.123 UTC, and a LinkedIn activity id
# for 2023-11-14 16:45:00.500 UTC. Both encode their time in the bits above
# 22: milliseconds since X's epoch (1288834974657), and since 1970.
X_STATUS_ID = "1764959161537439217"
X_STATUS_TIME = datetime(2024, 3, 5, 10, 20, 30, 123000, tzinfo=UTC)
LI_ACTIVITY_ID = "7130234174308463299"
LI_ACTIVITY_TIME = datetime(2023, 11, 14, 16, 45, 0, 500000, tzinfo=UTC)


def _page(*, meta: dict[str, str] | None = None, json_ld: object | None = None, body: str = "") -> str:
    tags = "".join(
        f'<meta {"property" if ":" in k else "name"}="{k}" content="{html.escape(v)}">'
        for k, v in (meta or {}).items()
    )
    script = (
        f'<script type="application/ld+json">{json.dumps(json_ld)}</script>'
        if json_ld is not None
        else ""
    )
    return f"<!doctype html><html><head>{tags}{script}</head><body>{body}</body></html>"


# ---------------------------------------------------------------------------
# X
# ---------------------------------------------------------------------------


def test_an_x_post_with_a_bare_page_is_dated_and_named_by_its_address():
    """X serves a script shell with no metadata to a client like ours, so the
    address is all there is: the handle in its path, the time in its id."""
    got = read("tweet", f"https://x.com/quill_feather/status/{X_STATUS_ID}", "<html></html>")

    assert got == PostMetadata(
        author="@quill_feather", handle="@quill_feather", published_at=X_STATUS_TIME
    )


@pytest.mark.parametrize(
    "url",
    [
        f"https://twitter.com/quill_feather/status/{X_STATUS_ID}",
        f"https://mobile.x.com/quill_feather/status/{X_STATUS_ID}?s=20",
        f"https://www.x.com/quill_feather/status/{X_STATUS_ID}/photo/1",
    ],
)
def test_every_x_host_and_suffix_reads_the_same(url):
    got = read("tweet", url, None)
    assert got.handle == "@quill_feather"
    assert got.published_at == X_STATUS_TIME


def test_an_x_address_without_a_handle_still_dates_the_post():
    got = read("tweet", f"https://x.com/i/web/status/{X_STATUS_ID}", None)
    assert got.handle is None
    assert got.author is None
    assert got.published_at == X_STATUS_TIME


@pytest.mark.parametrize(
    "url",
    [
        "https://x.com/home",
        "https://x.com/quill_feather",
        "https://x.com/search?q=status",
        f"https://box.com/quill_feather/status/{X_STATUS_ID}",  # not X
        "https://x.com/quill_feather/status/12345",  # pre-snowflake id: no time
    ],
)
def test_an_x_address_that_names_no_post_time_gives_no_date(url):
    assert read("tweet", url, None).published_at is None


def test_a_name_the_x_page_gives_is_shown_and_the_address_keeps_the_handle():
    page = _page(
        json_ld={
            "@context": "https://schema.org",
            "@type": "SocialMediaPosting",
            "author": {"@type": "Person", "name": "Quill Featherstone", "alternateName": "@someone_else"},
            "datePublished": "2020-01-01T00:00:00Z",
        }
    )
    got = read("tweet", f"https://x.com/quill_feather/status/{X_STATUS_ID}", page)

    assert got.author == "Quill Featherstone"
    assert got.handle == "@quill_feather", "the address names the post's author; it wins"
    assert got.published_at == X_STATUS_TIME, "the id is exact; it wins over the page"


def test_twitter_creator_names_the_handle_when_the_address_does_not():
    page = _page(meta={"twitter:creator": "@quill_feather"})
    got = read("tweet", f"https://x.com/i/web/status/{X_STATUS_ID}", page)
    assert got.handle == "@quill_feather"
    assert got.author == "@quill_feather"


# ---------------------------------------------------------------------------
# Instagram
# ---------------------------------------------------------------------------


def test_an_instagram_post_reads_its_open_graph_title_and_description():
    page = _page(
        meta={
            "og:title": 'Marisol Quintero on Instagram: "Tide pools at dawn"',
            "og:description": (
                '1,204 likes, 33 comments - marisol.quintero on March 3, 2024: "Tide pools at dawn"'
            ),
        }
    )
    got = read("ig_post", "https://www.instagram.com/p/C4xYzAbCdEf/", page)

    assert got == PostMetadata(
        author="Marisol Quintero",
        handle="@marisol.quintero",
        published_at=datetime(2024, 3, 3, tzinfo=UTC),
    )


def test_an_instagram_page_with_only_a_handle_shows_the_handle():
    page = _page(meta={"og:description": "12 likes, 0 comments - tidepool.notes on July 9, 2023: \"hi\""})
    got = read("ig_post", "https://www.instagram.com/p/abc/", page)
    assert got.author == "@tidepool.notes"
    assert got.published_at == datetime(2023, 7, 9, tzinfo=UTC)


# ---------------------------------------------------------------------------
# LinkedIn
# ---------------------------------------------------------------------------


def test_a_linkedin_post_reads_its_json_ld():
    page = _page(
        json_ld={
            "@context": "http://schema.org",
            "@type": "DiscussionForumPosting",
            "author": {"@type": "Person", "name": "Odalys Brennan", "url": "https://www.linkedin.com/in/odalys-b"},
            "datePublished": "2024-05-06T08:00:00.000+02:00",
        }
    )
    got = read("li_post", "https://www.linkedin.com/posts/odalys-b_tidal-energy-share-123", page)

    assert got.author == "Odalys Brennan"
    assert got.handle is None
    assert got.published_at == datetime(2024, 5, 6, 6, 0, tzinfo=UTC), "stored in UTC"


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.linkedin.com/posts/odalys-b_tidal-energy-activity-{LI_ACTIVITY_ID}-Ab1c",
        f"https://www.linkedin.com/feed/update/urn:li:activity:{LI_ACTIVITY_ID}/",
        f"https://www.linkedin.com/feed/update/urn%3Ali%3Aactivity%3A{LI_ACTIVITY_ID}",
    ],
)
def test_a_linkedin_activity_id_dates_the_post(url):
    got = read("li_post", url, "<html><head><title>LinkedIn</title></head></html>")
    assert got.published_at == LI_ACTIVITY_TIME


# ---------------------------------------------------------------------------
# Facebook
# ---------------------------------------------------------------------------


def test_a_facebook_post_reads_json_ld_inside_a_graph():
    page = _page(
        json_ld={
            "@context": "https://schema.org",
            "@graph": [
                {"@type": "WebPage", "name": "Facebook"},
                {
                    "@type": "SocialMediaPosting",
                    "author": [{"@type": "Person", "name": "Tobiah Okonkwo-Lind"}],
                    "dateCreated": "2022-08-19",
                },
            ],
        }
    )
    got = read("fb_post", "https://www.facebook.com/tobiah.ol/posts/pfbid0abc", page)

    assert got.author == "Tobiah Okonkwo-Lind"
    assert got.published_at == datetime(2022, 8, 19, tzinfo=UTC), "a date alone is midnight UTC"


def test_a_facebook_page_falls_back_to_article_tags_and_ignores_a_link_for_an_author():
    page = _page(
        meta={
            "article:author": "https://www.facebook.com/tobiah.ol",
            "author": "Tobiah Okonkwo-Lind",
            "article:published_time": "2021-12-31T23:30:00-05:00",
        }
    )
    got = read("fb_post", "https://www.facebook.com/tobiah.ol/posts/1", page)

    assert got.author == "Tobiah Okonkwo-Lind"
    assert got.published_at == datetime(2022, 1, 1, 4, 30, tzinfo=UTC)


# ---------------------------------------------------------------------------
# What is not a date, an author or a page
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("placeholder", ["1970-01-01T00:00:00Z", "0001-01-01", "2999-01-01", "soon", ""])
def test_a_placeholder_date_is_no_date(placeholder):
    page = _page(json_ld={"@type": "SocialMediaPosting", "datePublished": placeholder})
    assert read("fb_post", "https://www.facebook.com/x/posts/1", page).published_at is None


@pytest.mark.parametrize(
    "page",
    [
        '<script type="application/ld+json">{not json</script>',
        "<html><head><meta property='og:title'",  # cut off mid-tag
        "\x00\x01 binary \xff",
        _page(json_ld=[1, "two", None, {"@type": 7}]),
        "",
        None,
    ],
)
def test_a_page_this_cannot_read_gives_nothing_and_never_raises(page):
    assert read("fb_post", "https://www.facebook.com/x/posts/1", page) == PostMetadata()


def test_an_article_is_left_to_trafilatura():
    page = _page(json_ld={"@type": "NewsArticle", "author": "Someone", "datePublished": "2024-01-01"})
    assert read("article", "https://example.com/a", page) == PostMetadata()


def test_a_name_is_trimmed_and_capped():
    page = _page(json_ld={"@type": "SocialMediaPosting", "author": {"name": "  Odalys \n  Brennan " + "x" * 400}})
    got = read("li_post", "https://www.linkedin.com/posts/a", page)
    assert got.author.startswith("Odalys Brennan x")
    assert len(got.author) == 200


@pytest.mark.parametrize(
    "value,expected",
    [
        (datetime(2024, 3, 5, 12, 0), datetime(2024, 3, 5, 12, 0, tzinfo=UTC)),
        (datetime(2024, 3, 5, 12, 0, tzinfo=UTC), datetime(2024, 3, 5, 12, 0, tzinfo=UTC)),
        (datetime(1969, 12, 31), None),
        (None, None),
        ("2024-03-05", None),
    ],
)
def test_to_utc_post_date(value, expected):
    assert platform_metadata.to_utc_post_date(value) == expected
