"""GitHub activity connector (S-3.2.4). Registers itself on import."""
from app.connectors.github.connector import GitHubConnector
from app.connectors.registry import register_connector

register_connector(GitHubConnector())
