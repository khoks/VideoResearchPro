/**
 * What a map node is and where it leads (S-8.9.2): opened by a click, by
 * Enter on the keyboard focus, or from the table. Links go to the source,
 * its channel page, or the exchange on its run or library Q&A page; the card
 * can also re-centre the map on the node (the double-click equivalent).
 */
import { type CSSProperties } from 'react';
import { Link } from 'react-router-dom';
import { Button, Card } from '../primitives';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, space } from '../../theme';
import { TYPE_NAME, neighbourNodes, type GraphModel } from '../../utils/graphModel';

const offscreen: CSSProperties = {
  position: 'absolute',
  width: 1,
  height: 1,
  overflow: 'hidden',
  clip: 'rect(0, 0, 0, 0)',
  whiteSpace: 'nowrap',
};

const MAX_LISTED = 8;

export function GraphDetailCard({
  model,
  id,
  onClose,
  onRefocus,
  onSelect,
}: {
  model: GraphModel;
  id: string;
  onClose: () => void;
  onRefocus: (id: string) => void;
  onSelect: (id: string) => void;
}) {
  const c = useColors();
  const node = model.byId.get(id);
  if (!node) return null;
  const group = model.groups[node.group];
  const link: CSSProperties = { color: c.accent, fontFamily: fonts.ui, fontSize: fontSize.sm };
  const meta: CSSProperties = { fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary, margin: 0 };
  const neighbours = neighbourNodes(model, id);

  const links: { label: string; to: string; external?: boolean }[] = [];
  if (node.type === 'document') {
    if (node.meta.url) links.push({ label: 'Open the source', to: node.meta.url, external: true });
    if (node.meta.channel_id) links.push({ label: 'Channel page', to: `/library/channels/${node.meta.channel_id}` });
  } else if (node.type === 'channel' && node.meta.channel_id) {
    links.push({ label: 'Channel page', to: `/library/channels/${node.meta.channel_id}` });
  } else if (node.type === 'exchange' && node.meta.exchange_id) {
    links.push(
      node.meta.kind === 'job' && node.meta.job_id
        ? { label: 'Open the answer on its run', to: `/jobs/${node.meta.job_id}?exchange=${node.meta.exchange_id}` }
        : { label: 'Open the answer', to: `/library/qa?exchange=${node.meta.exchange_id}` },
    );
  }

  const facts = [
    TYPE_NAME[node.type],
    group?.name,
    node.shownDegree === 1 ? '1 connection here' : `${node.shownDegree} connections here`,
    node.degree > node.shownDegree ? `${node.degree} in your whole library` : null,
    node.type === 'topic' && node.meta.documents ? `in ${node.meta.documents} of your sources` : null,
    node.type === 'document' && node.meta.published_at ? `published ${new Date(node.meta.published_at).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })}` : null,
  ].filter(Boolean);

  return (
    <Card data-graph-card="" aria-labelledby={`graph-card-${node.id}`} role="region">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: space['3'], alignItems: 'flex-start' }}>
        <h3
          id={`graph-card-${node.id}`}
          style={{
            margin: 0,
            fontFamily: fonts.display,
            fontSize: fontSize.lg,
            fontWeight: fontWeight.medium,
            lineHeight: lineHeight.snug,
            color: c.textPrimary,
            overflowWrap: 'anywhere',
          }}
        >
          {node.displayLabel}
        </h3>
        <Button variant="tertiary" size="sm" onClick={onClose} aria-label="Close details">
          Close
        </Button>
      </div>
      <p style={{ ...meta, marginTop: space['1'] }}>{facts.join(' · ')}</p>

      {(links.length > 0 || model.focus !== id) && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: space['3'], alignItems: 'center', marginTop: space['3'] }}>
          {links.map(l =>
            l.external ? (
              <a key={l.label} href={l.to} target="_blank" rel="noopener noreferrer" style={link}>
                {l.label} <span aria-hidden="true">↗</span>
                <span style={offscreen}> (opens in a new tab)</span>
              </a>
            ) : (
              <Link key={l.label} to={l.to} style={link}>
                {l.label}
              </Link>
            ),
          )}
          {model.focus !== id && (
            <Button variant="secondary" size="sm" onClick={() => onRefocus(id)}>
              Centre the map here
            </Button>
          )}
        </div>
      )}

      {neighbours.length > 0 && (
        <div style={{ marginTop: space['3'] }}>
          <p style={{ ...meta, fontWeight: fontWeight.semibold }}>Connected to</p>
          <ul style={{ margin: `${space['1']} 0 0`, paddingLeft: space['5'], fontFamily: fonts.ui, fontSize: fontSize.sm }}>
            {neighbours.slice(0, MAX_LISTED).map(n => (
              <li key={n.id} style={{ marginBottom: space['1'] }}>
                <button
                  type="button"
                  onClick={() => onSelect(n.id)}
                  style={{
                    background: 'none',
                    border: 'none',
                    padding: 0,
                    font: 'inherit',
                    color: c.accent,
                    textDecoration: 'underline',
                    textUnderlineOffset: 2,
                    cursor: 'pointer',
                    textAlign: 'left',
                  }}
                >
                  {n.displayLabel}
                </button>
              </li>
            ))}
          </ul>
          {neighbours.length > MAX_LISTED && (
            <p style={{ ...meta, marginTop: space['1'] }}>and {neighbours.length - MAX_LISTED} more, listed in the table view</p>
          )}
        </div>
      )}
    </Card>
  );
}
