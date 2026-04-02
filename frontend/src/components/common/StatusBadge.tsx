import { statusColor, statusLabel } from '../../utils/formatters';

export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      style={{
        background: statusColor(status),
        color: '#fff',
        padding: '2px 10px',
        borderRadius: 12,
        fontSize: '0.8rem',
        fontWeight: 600,
      }}
    >
      {statusLabel(status)}
    </span>
  );
}
