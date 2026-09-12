export const API_REQUEST_TIMEOUT_MS = 20_000;
export const PUBLIC_REQUEST_TIMEOUT_MS = 12_000;
export const UPLOAD_REQUEST_TIMEOUT_MS = 120_000;

export class RequestTimeoutError extends Error {
  constructor() {
    super('The request timed out. Please try again.');
    this.name = 'RequestTimeoutError';
  }
}

export class ApiClientError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = 'ApiClientError';
    this.status = status;
    this.code = code;
  }
}

export const apiErrorCode = (value: unknown): string | undefined =>
  value instanceof ApiClientError ? value.code : undefined;

export async function fetchWithTimeout(
  input: RequestInfo | URL,
  init: RequestInit = {},
  timeoutMs = API_REQUEST_TIMEOUT_MS,
): Promise<Response> {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    throw new RangeError('timeoutMs must be a positive number');
  }

  const controller = new AbortController();
  let timedOut = false;
  const abortFromCaller = () => controller.abort();
  if (init.signal?.aborted) controller.abort();
  else init.signal?.addEventListener('abort', abortFromCaller, { once: true });
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } catch (value) {
    if (timedOut) throw new RequestTimeoutError();
    throw value;
  } finally {
    clearTimeout(timer);
    init.signal?.removeEventListener('abort', abortFromCaller);
  }
}

export function readableRequestError(value: unknown, fallback: string): Error {
  if (value instanceof RequestTimeoutError) return value;
  if (value instanceof Error && value.name === 'AbortError') {
    return new Error('The request was cancelled.');
  }
  if (value instanceof TypeError) {
    return new Error('Could not reach FroggyBot. Check your connection and try again.');
  }
  return value instanceof Error ? value : new Error(fallback);
}
