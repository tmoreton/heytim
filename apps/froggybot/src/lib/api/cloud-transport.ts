import { fetchAuthSession } from 'aws-amplify/auth';

import { apiUrl } from '../cloud';
import {
  API_REQUEST_TIMEOUT_MS,
  ApiClientError,
  fetchWithTimeout,
  PUBLIC_REQUEST_TIMEOUT_MS,
  readableRequestError,
} from '../http';

export type ApiRequest = <T>(path: string, init?: RequestInit, timeoutMs?: number) => Promise<T>;
export type PublicApiRequest = <T>(path: string) => Promise<T>;

const responseBody = async (response: Response): Promise<Record<string, unknown>> => {
  const text = await response.text();
  if (!text) return {};
  try {
    const value: unknown = JSON.parse(text);
    return value && typeof value === 'object' && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {};
  } catch {
    if (!response.ok) throw new Error(`The service returned an invalid response (${response.status}).`);
    throw new Error('The service returned an invalid response.');
  }
};

const responseMessage = (body: Record<string, unknown>, fallback: string) =>
  typeof body.message === 'string' ? body.message : fallback;

export function createCloudTransport(): { request: ApiRequest; publicRequest: PublicApiRequest } {
  const request: ApiRequest = async <T>(
    path: string,
    init?: RequestInit,
    timeoutMs = API_REQUEST_TIMEOUT_MS,
  ): Promise<T> => {
    const session = await fetchAuthSession();
    const token = session.tokens?.idToken?.toString();
    if (!token) throw new Error('Your session expired. Please sign in again.');
    let response: Response;
    try {
      response = await fetchWithTimeout(`${apiUrl}${path}`, {
        ...init,
        headers: {
          authorization: `Bearer ${token}`,
          'content-type': 'application/json',
          ...init?.headers,
        },
      }, timeoutMs);
    } catch (value) {
      throw readableRequestError(value, 'The request could not be completed.');
    }
    const body = await responseBody(response);
    if (!response.ok) {
      throw new ApiClientError(
        response.status,
        typeof body.code === 'string' ? body.code : 'request_failed',
        responseMessage(body, `The request failed (${response.status}).`),
      );
    }
    return body as T;
  };

  const publicRequest: PublicApiRequest = async <T>(path: string): Promise<T> => {
    let response: Response;
    try {
      response = await fetchWithTimeout(`${apiUrl}${path}`, {}, PUBLIC_REQUEST_TIMEOUT_MS);
    } catch (value) {
      throw readableRequestError(value, 'The invite could not be opened.');
    }
    const body = await responseBody(response);
    if (!response.ok) {
      throw new ApiClientError(
        response.status,
        typeof body.code === 'string' ? body.code : 'request_failed',
        responseMessage(body, 'The invite could not be opened.'),
      );
    }
    return body as T;
  };

  return { request, publicRequest };
}
