"""spotify_export as an Echo archive importer (S-3.7.5). Registers on import."""
from app.connectors import registry
from app.connectors.spotify_export.importer import IMPORTER

registry.register_importer(IMPORTER)
