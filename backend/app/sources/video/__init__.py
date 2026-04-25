"""YouTube video connector — the first concrete `BaseConnector` implementation.

Importing this package registers the connector in the global registry.
The job orchestrator looks it up via `connector_for("video")`.
"""
