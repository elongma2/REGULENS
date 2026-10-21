import { supabase } from "../lib/supabase";

const configuredBase = import.meta.env.VITE_API_BASE_URL ?? "/api";
export const apiBase = configuredBase.replace(/\/$/, "");

export async function authorizationHeader(): Promise<Record<string, string>> {
  if (!supabase) return {};
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ? { Authorization: `Bearer ${data.session.access_token}` } : {};
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const authorization = await authorizationHeader();
  const request = {
    ...init,
    headers: { ...authorization, ...init.headers },
  };
  const method = (init.method ?? "GET").toUpperCase();
  const canRetry = method === "GET" || method === "HEAD";

  try {
    const response = await fetch(`${apiBase}${path}`, request);
    if (!canRetry || ![408, 425, 429, 500, 502, 503, 504].includes(response.status)) return response;
  } catch (error) {
    if (!canRetry || (error instanceof DOMException && error.name === "AbortError")) throw error;
  }

  await new Promise((resolve) => globalThis.setTimeout(resolve, 180));
  return fetch(`${apiBase}${path}`, request);
}

