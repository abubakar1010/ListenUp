import type { components } from './schema';

export type Me = components['schemas']['Me'];

/** An RFC 9457 problem returned by the API. Branch on `code`, show `detail`. */
export interface Problem {
  type: string;
  title: string;
  status: number;
  detail: string;
  code: string;
  [extension: string]: unknown;
}

export class ApiError extends Error {
  readonly problem: Problem;

  constructor(problem: Problem) {
    super(problem.detail);
    this.name = 'ApiError';
    this.problem = problem;
  }

  get code(): string {
    return this.problem.code;
  }
}

const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

function csrfToken(): string | undefined {
  // The cookie is `listenup_csrf` locally and `__Host-listenup_csrf` over HTTPS.
  return document.cookie
    .split('; ')
    .map((pair) => pair.split('='))
    .find(([name]) => name.endsWith('listenup_csrf'))?.[1];
}

async function ensureCsrfToken(): Promise<string | undefined> {
  // Any API response sets the cookie; the health check is the cheapest one.
  if (!csrfToken()) await fetch('/api/v1/health', { credentials: 'same-origin' });
  return csrfToken();
}

async function toProblem(response: Response): Promise<Problem> {
  try {
    const body = (await response.json()) as Partial<Problem>;
    if (body && typeof body.code === 'string') return body as Problem;
  } catch {
    // Not JSON: fall through to a generic problem.
  }
  return {
    type: 'about:blank',
    title: response.statusText,
    status: response.status,
    detail: 'Something went wrong. Check your connection and try again.',
    code: 'unexpected_response',
  };
}

/**
 * Call the API. Throws ApiError with the server's problem on any non-2xx response.
 * `keepalive` lets the request outlive the page, for a report sent from `pagehide`.
 */
export async function api<T>(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    headers?: Record<string, string>;
    keepalive?: boolean;
  } = {},
): Promise<T> {
  const method = options.method ?? 'GET';
  const headers: Record<string, string> = { Accept: 'application/json', ...options.headers };
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (UNSAFE.has(method)) {
    const token = await ensureCsrfToken();
    if (token) headers['X-CSRF-Token'] = token;
  }

  const response = await fetch(`/api/v1${path}`, {
    method,
    headers,
    credentials: 'same-origin',
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    ...(options.keepalive ? { keepalive: true } : {}),
  });
  if (!response.ok) throw new ApiError(await toProblem(response));
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
