"""Podcast source-type connector — registers under ``source_type='podcast_episode'``.

Closes the **M-1.7 (Podcast end-to-end)** milestone. Per
[D-005](../../../docs/decisions.md#d-005--social-media-ingest-before-article-ingest-2026-04-25),
podcasts ship after social-media is mature and the polymorphic plumbing
(connector / approval / classifier / citation) has been validated five
times. This connector is the sixth source type to slot into that
plumbing without core changes.

**Discovery surface.**

- **Topic search** via iTunes Search API (free, no auth) →
  ``GET https://itunes.apple.com/search?term=<q>&entity=podcast`` returns
  shows matching the query. Per-show RSS feeds are then fetched and the
  most recent N episodes from each show become candidates.
- **Creator-feed listing** is direct RSS-feed iteration. The user
  passes either an iTunes show URL (we resolve to RSS) or a direct RSS
  URL.

**Text extraction.**

- **Preferred**: in-feed transcript via the Podcast Index 2.0
  ``<podcast:transcript>`` tag (an increasingly common addition to
  RSS feeds). When present, no audio download / Whisper call is
  needed — the transcript is fetched directly.
- **Fallback**: download the episode audio from the RSS
  ``<enclosure>`` URL and run it through OpenAI Whisper, reusing the
  existing `_whisper_transcribe_with_retry` helper from
  ``app.services.youtube_service``. Per [OQ-4
  resolution](../../../docs/decisions.md#d-033--whisper-as-service-for-podcasts-reuse-existing-openai-whisper-path-2026-05-03),
  we reuse the OpenAI Whisper path rather than spinning up a separate
  service. Gated on ``OPENAI_API_KEY`` just like the YouTube fallback;
  fail-soft to ``None`` (document marked unavailable) when unset.

**Identity.**

- ``Candidate.source_id = f"podcast:{episode_guid}"``. Episode GUIDs
  are required by the RSS-2.0 spec; we use them rather than enclosure
  URLs because the URL can change (CDN rotations, sponsorship-tag
  rewrites) while the GUID is stable.
- ``Candidate.creator_external_id = <feed_url>`` — the RSS feed URL
  uniquely identifies the show. We don't hash it because the URL is
  already a stable canonical identifier.
- ``Candidate.source_url = <enclosure_url>`` for browser-friendly
  citations (clicking opens the audio file in the user's default
  player).
"""
