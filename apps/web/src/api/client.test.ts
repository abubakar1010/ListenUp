import { api } from './client';

afterEach(() => vi.unstubAllGlobals());
it('accepts the existing bodyless 202 snippet retry response', async () => {
  document.cookie = 'listenup_csrf=test-token';
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 202 })));
  await expect(api<void>('/cards/card-1/audio/retry', { method: 'POST' })).resolves.toBeUndefined();
});
it('preserves JSON payloads on accepted responses', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(Response.json({ status: 'accepted' }, { status: 202 })),
  );
  await expect(api('/grades/attempt-1/retry')).resolves.toEqual({ status: 'accepted' });
});
it('still rejects a missing JSON body on ordinary successful reads', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 200 })));
  await expect(api('/cards')).rejects.toBeInstanceOf(SyntaxError);
});
