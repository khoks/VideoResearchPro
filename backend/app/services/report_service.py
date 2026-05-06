import os
import logging


logger = logging.getLogger(__name__)


def get_report_html(report_path: str) -> str | None:
    """Read an HTML report from disk."""
    if not report_path or not os.path.exists(report_path):
        return None
    with open(report_path, "r", encoding="utf-8") as f:
        return f.read()


def delete_report(report_path: str) -> bool:
    """Delete a report file from disk."""
    if report_path and os.path.exists(report_path):
        os.remove(report_path)
        return True
    return False
