"""Google Takeout as an Echo archive importer (S-3.7.5): Keep notes and
YouTube history. Registers on import."""
from app.connectors import registry
from app.connectors.google_takeout.importer import IMPORTER

registry.register_importer(IMPORTER)
