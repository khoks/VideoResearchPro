/**
 * The command palette (S-8.2.2, plan docs/plans/m2-command-palette.md).
 *
 * Opens on Mod-K (Cmd on macOS, Ctrl elsewhere) or Ctrl-Alt-K — Chrome and
 * Firefox bind Ctrl-K to the address bar, and a page handler only wins once
 * the page has focus, hence the alternate. Grouped, tenant-scoped results
 * come from `GET /search` (the server filters, so cmdk's own filter is off);
 * navigation actions and recent items are filtered on the client.
 *
 * Built on `cmdk` for the combobox / listbox semantics and keyboard model
 * (focus stays in the input, `aria-activedescendant` follows the arrows).
 * The overlay is our own: cmdk's Dialog takes only class names, and this
 * app's surfaces are inline-styled. Selection styling reads
 * `useCommandState` per item, so no `<style>` block is needed (the plan's
 * open question 1 does not arise).
 */
import { lazy, Suspense } from 'react';
import { useNavigate } from 'react-router-dom';
import { useShortcuts } from '../../hooks/useShortcuts';
import { usePaletteStore } from '../../stores/paletteStore';

// cmdk and its Radix dependencies load on first open, not with the app.
const PalettePanel = lazy(() => import('./PalettePanel'));

/** Mounted once, in AppLayout: the shortcuts and the (closed) palette. */
export function CommandPalette() {
  const navigate = useNavigate();
  const open = usePaletteStore((s) => s.open);
  const setOpen = usePaletteStore((s) => s.setOpen);
  const toggle = usePaletteStore((s) => s.toggle);
  const singleKey = usePaletteStore((s) => s.singleKeyShortcuts);

  useShortcuts(
    [
      { keys: 'mod+k', run: toggle, allowInInputs: true },
      { keys: 'ctrl+alt+k', run: toggle, allowInInputs: true },
      {
        keys: '/',
        singleKey: true,
        run: () => {
          // The page's own search box when it has one, else the palette.
          const field = document.querySelector<HTMLInputElement>('[data-page-search]');
          if (field) field.focus();
          else setOpen(true);
        },
      },
      // The chords ui-design.md §2.1 has always described.
      { keys: 'g r', singleKey: true, run: () => navigate('/submit') },
      { keys: 'g l', singleKey: true, run: () => navigate('/library') },
      { keys: 'g k', singleKey: true, run: () => navigate('/qa-history') },
      { keys: 'g a', singleKey: true, run: () => navigate('/author') },
    ],
    { singleKeyEnabled: singleKey && !open },
  );

  if (!open) return null;
  return (
    <Suspense fallback={null}>
      <PalettePanel onClose={() => setOpen(false)} />
    </Suspense>
  );
}
