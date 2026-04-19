import os
from datetime import datetime, timezone

from jinja2 import Environment

from app.config import settings

REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ title }}</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         line-height: 1.6; color: #1a1a2e; background: #f8f9fa; }
  .report { max-width: 960px; margin: 0 auto; padding: 2rem; }
  .report-header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                   color: white; padding: 2rem; border-radius: 12px; margin-bottom: 2rem; }
  .report-header h1 { font-size: 1.8rem; margin-bottom: 0.5rem; }
  .report-header .meta { opacity: 0.9; font-size: 0.9rem; }
  .section { background: white; border-radius: 8px; padding: 1.5rem; margin-bottom: 1.5rem;
             box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
  .section h2 { color: #667eea; font-size: 1.3rem; margin-bottom: 1rem;
                border-bottom: 2px solid #667eea; padding-bottom: 0.5rem; }
  .section h3 { color: #333; font-size: 1.1rem; margin: 1rem 0 0.5rem; }
  .section ul { padding-left: 1.5rem; }
  .section li { margin-bottom: 0.5rem; }
  .source { font-size: 0.85rem; color: #666; }
  .source a { color: #667eea; text-decoration: none; }
  .source a:hover { text-decoration: underline; }
  .stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; }
  .stat-card { background: #f0f2ff; padding: 1rem; border-radius: 8px; text-align: center; }
  .stat-card .value { font-size: 1.8rem; font-weight: bold; color: #667eea; }
  .stat-card .label { font-size: 0.85rem; color: #666; }
  table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
  th, td { padding: 0.75rem; text-align: left; border-bottom: 1px solid #eee; }
  th { background: #f0f2ff; color: #333; font-weight: 600; }
  tr:hover { background: #f8f9ff; }
</style>
</head>
<body>
<div class="report">
  <div class="report-header">
    <h1>{{ title }}</h1>
    <div class="meta">
      Generated on {{ generated_at }} | {{ job_type | title }} Research Report
    </div>
  </div>

  <div class="section">
    <h2>Statistics</h2>
    <div class="stat-grid">
      <div class="stat-card">
        <div class="value">{{ stats.video_count }}</div>
        <div class="label">Videos Analyzed</div>
      </div>
      <div class="stat-card">
        <div class="value">{{ stats.transcript_count }}</div>
        <div class="label">Transcripts Fetched</div>
      </div>
      <div class="stat-card">
        <div class="value">{{ stats.total_words | number_format }}</div>
        <div class="label">Total Words</div>
      </div>
      <div class="stat-card">
        <div class="value">{{ stats.total_minutes }}</div>
        <div class="label">Total Minutes</div>
      </div>
    </div>
    {% if stats.channel_breakdown %}
    <h3>Per-Channel Breakdown</h3>
    <table>
      <thead><tr><th>Channel</th><th>Videos</th><th>Words</th><th>Minutes</th></tr></thead>
      <tbody>
        {% for ch in stats.channel_breakdown %}
        <tr>
          <td>{{ ch.channel_name }}</td>
          <td>{{ ch.video_count }}</td>
          <td>{{ ch.word_count | number_format }}</td>
          <td>{{ ch.minutes }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% endif %}
  </div>

  {{ report_body | safe }}
</div>
</body>
</html>"""


def _number_format(value):
    try:
        return f"{int(value):,}"
    except (ValueError, TypeError):
        return str(value)


def build_report_html(
    title: str,
    job_type: str,
    statistics: dict,
    report_body: str = "",
) -> str:
    """Render the final HTML report."""
    env = Environment(autoescape=True)
    env.filters["number_format"] = _number_format
    template = env.from_string(REPORT_TEMPLATE)

    return template.render(
        title=title,
        job_type=job_type,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        stats=statistics,
        report_body=report_body,
    )


def save_report(job_id: str, html_content: str) -> str:
    """Save HTML report to disk and return the file path."""
    os.makedirs(settings.REPORTS_DIR, exist_ok=True)
    filename = f"report_{job_id}.html"
    filepath = os.path.join(settings.REPORTS_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_content)
    return filepath
