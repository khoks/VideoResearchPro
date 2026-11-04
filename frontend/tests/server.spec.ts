/**
 * T-8.8.4.6: the dev server answers on both loopback addresses.
 *
 * `localhost` is two addresses, and a browser whose connection to the first
 * fails moves on to the second. Windows does fail the odd connect. With the
 * server on one family that second try lands on a port nobody holds, the
 * request comes back `net::ERR_CONNECTION_REFUSED`, and a dev build that lost
 * one module never boots: a blank page, with the server up and every other
 * connection fine. `--host ::` in playwright.config.ts is what this pins.
 */
import { expect, test } from '@playwright/test';

test('the dev server answers on both loopback addresses', async ({ request, baseURL }) => {
  const { port } = new URL(baseURL!);
  for (const address of ['127.0.0.1', '[::1]']) {
    const response = await request.get(`http://${address}:${port}/`);
    expect(response.ok(), address).toBe(true);
  }
});
