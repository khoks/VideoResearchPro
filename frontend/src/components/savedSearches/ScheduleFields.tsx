import { FormField, Select } from '../primitives';
import { space } from '../../theme';
import { WEEKDAYS } from '../../utils/cadence';
import type { Cadence } from '../../services/savedSearchesApi';

const HOURS = Array.from({ length: 24 }, (_, h) => h);
const DAYS = Array.from({ length: 28 }, (_, d) => d + 1);

/**
 * Human cadence presets (S-8.3.2): daily, weekly or monthly, at an hour in
 * the reader's zone. Never a cron string. Day of month stops at 28 so every
 * month has it, as the scheduler requires.
 */
export function ScheduleFields({ value, onChange }: { value: Cadence; onChange: (c: Cadence) => void }) {
  const set = (patch: Partial<Cadence>) => onChange({ ...value, ...patch });
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: space['3'] }}>
      <FormField label="How often" style={{ flex: '1 1 140px' }}>
        {(id) => (
          <Select
            id={id}
            value={value.cadence}
            onChange={(e) => {
              const cadence = e.target.value as Cadence['cadence'];
              set({
                cadence,
                weekday: cadence === 'weekly' ? value.weekday ?? 0 : undefined,
                day_of_month: cadence === 'monthly' ? value.day_of_month ?? 1 : undefined,
              });
            }}
          >
            <option value="daily">Daily</option>
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
          </Select>
        )}
      </FormField>
      {value.cadence === 'weekly' && (
        <FormField label="On" style={{ flex: '1 1 140px' }}>
          {(id) => (
            <Select id={id} value={value.weekday ?? 0} onChange={(e) => set({ weekday: Number(e.target.value) })}>
              {WEEKDAYS.map((d, i) => (
                <option key={d} value={i}>
                  {d}
                </option>
              ))}
            </Select>
          )}
        </FormField>
      )}
      {value.cadence === 'monthly' && (
        <FormField label="On day" style={{ flex: '1 1 110px' }}>
          {(id) => (
            <Select id={id} value={value.day_of_month ?? 1} onChange={(e) => set({ day_of_month: Number(e.target.value) })}>
              {DAYS.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </Select>
          )}
        </FormField>
      )}
      <FormField label="At" helperText={value.timezone} style={{ flex: '1 1 110px' }}>
        {(id) => (
          <Select id={id} value={value.hour} onChange={(e) => set({ hour: Number(e.target.value), minute: 0 })}>
            {HOURS.map((h) => (
              <option key={h} value={h}>
                {String(h).padStart(2, '0')}:00
              </option>
            ))}
          </Select>
        )}
      </FormField>
    </div>
  );
}
