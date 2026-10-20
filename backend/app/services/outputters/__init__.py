"""Concrete outputters — I-6 Author Studio.

Importing this package registers every shipped outputter into
``output_service``'s registry as a side effect. Callers (FastAPI
lifespan, tests, scripts) import this module to ensure the registry
is populated before resolving an outputter by kind.
"""
from app.services.outputters.book_markdown import BookMarkdownOutputter
from app.services.outputters.deck import DeckOutputter
from app.services.outputters.site import SiteOutputter
from app.services.output_service import register_outputter

# Register on module import. Idempotent.
register_outputter(BookMarkdownOutputter())
register_outputter(DeckOutputter())  # S-6.3.1
register_outputter(SiteOutputter())  # S-6.2.1

__all__ = ["BookMarkdownOutputter", "DeckOutputter", "SiteOutputter"]
