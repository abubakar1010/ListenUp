import { jsonResponse, problem } from '../../test-utils';
import { blindStepFixture } from '../blind/fixtures';

export interface Call {
  method: string;
  path: string;
  body: unknown;
  headers: Record<string, string>;
}

type Handler = (call: Call) => Response;

/**
 * Mocks fetch by "METHOD /path" (path after /api/v1, with its query). Records every
 * call; routes without an entry answer 404, except a session's Blind step, which
 * answers an untried step.
 */
export function mockRoutes(routes: Record<string, Handler | Response>) {
  const calls: Call[] = [];
  const spy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const path = String(input).replace(/^\/api\/v1/, '');
    const method = init?.method ?? 'GET';
    const call: Call = {
      method,
      path,
      body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
      headers: (init?.headers ?? {}) as Record<string, string>,
    };
    calls.push(call);
    const handler = routes[`${method} ${path}`];
    // A session with Blind open also loads its Blind step: untried unless mocked.
    const blind = method === 'GET' && path.match(/^\/sessions\/([^/]+)\/blind$/);
    if (!handler && blind) return jsonResponse(200, blindStepFixture(null, blind[1]));
    if (!handler) return problem(404, 'not_found', `No mock for ${method} ${path}.`);
    return typeof handler === 'function' ? handler(call) : handler.clone();
  });
  return { calls, spy };
}
