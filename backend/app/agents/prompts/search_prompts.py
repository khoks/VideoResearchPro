INTERPRET_QUERY_PROMPT = """You are a YouTube research assistant. Given a research topic and optional instructions,
generate 3-5 YouTube search queries that would find the most relevant and comprehensive videos on this topic.

Topic: {topic}
Additional instructions: {search_instructions}
Channel type preferences: {channel_type_filters}

Consider:
- Different angles and perspectives on the topic
- Technical vs. explanatory content
- Recent vs. foundational content
- Specific subtopics that are commonly discussed

Return a JSON array of search query strings. Example: ["query 1", "query 2", "query 3"]
"""

RANK_AND_CURATE_PROMPT = """You are a YouTube research assistant. Given a list of discovered videos for a research topic,
rank them by relevance and select the top {num_videos} most relevant ones.

Topic: {topic}
Additional instructions: {search_instructions}

Each video below is shown with metadata:
- Title and channel
- Duration
- Views (view count on the video)
- Likes (like count on the video)
- Published (ISO 8601 publish date — more recent is usually better unless the topic calls for foundational content)
- Subscribers (approximate subscriber count of the channel — a proxy for channel authority)

Videos found:
{video_list}

Consider:
- Relevance to the specific topic
- Engagement signals (views, likes) relative to channel size — a mid-size channel with strong engagement
  is often a better signal than a huge channel with a tangential video
- Channel authority via subscriber count, but weight relevance higher than raw popularity
- Video duration — prefer substantive content over shallow clickbait
- Recency when the topic is fast-moving; favor older foundational videos for evergreen topics
- Diversity of perspectives across different channels

Return a JSON array of video IDs for the top {num_videos} most relevant videos, ordered by relevance.
Example: ["video_id_1", "video_id_2"]
"""
