export function ProgressBar({ value, color = '#667eea' }: { value: number; color?: string }) {
  return (
    <div style={{ background: '#e2e8f0', borderRadius: 8, height: 8, overflow: 'hidden' }}>
      <div
        style={{
          width: `${Math.min(100, Math.max(0, value))}%`,
          height: '100%',
          background: color,
          borderRadius: 8,
          transition: 'width 0.5s ease',
        }}
      />
    </div>
  );
}
