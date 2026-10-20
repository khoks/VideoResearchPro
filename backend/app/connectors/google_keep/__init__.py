"""Google Keep notes from Takeout as an Echo archive importer (S-3.7.5). Registers on import;
``registry.load_builtin`` imports every package here."""
from app.connectors import registry
from app.connectors.google_keep.importer import IMPORTER

registry.register_importer(IMPORTER)
