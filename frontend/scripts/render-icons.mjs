// Render the PNG app icons from public/logo-mark.svg (S-8.12.2).
//
//   npm run icons
//
// Uses the Chromium that Playwright installs for the device tests, so the
// icons are reproducible from the SVG alone; commit the PNGs it writes.
// Every icon is the mark on the paper background (#faf6f0): a home-screen
// icon with a transparent background turns black on iOS and grey on some
// Android launchers.
//
//   icon-192.png / icon-512.png   purpose "any": mark at 72 % of the tile
//   icon-maskable-512.png         purpose "maskable": mark inside the 80 %
//                                 safe circle (launchers crop to any shape)
//   apple-touch-icon.png (180)    iOS rounds the corners itself
import { readFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const svg = readFileSync(join(root, 'public', 'logo-mark.svg'), 'utf-8');
const PAPER = '#faf6f0';

const ICONS = [
  { file: 'public/icons/icon-192.png', size: 192, mark: 0.72 },
  { file: 'public/icons/icon-512.png', size: 512, mark: 0.72 },
  { file: 'public/icons/icon-maskable-512.png', size: 512, mark: 0.56 },
  { file: 'public/apple-touch-icon.png', size: 180, mark: 0.7 },
];

mkdirSync(join(root, 'public', 'icons'), { recursive: true });
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ deviceScaleFactor: 1 });
  for (const { file, size, mark } of ICONS) {
    const inner = Math.round(size * mark);
    await page.setViewportSize({ width: size, height: size });
    await page.setContent(
      `<!doctype html><html><body style="margin:0;width:${size}px;height:${size}px;display:grid;place-items:center;background:${PAPER}">` +
        `<div style="width:${inner}px;height:${inner}px">${svg.replace('<svg ', '<svg width="100%" height="100%" ')}</div>` +
        `</body></html>`,
    );
    await page.screenshot({ path: join(root, file), omitBackground: false });
    console.log(`${file} ${size}x${size}`);
  }
} finally {
  await browser.close();
}
