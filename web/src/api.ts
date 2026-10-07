export const request = async <T,>(
  url: string,
  options: RequestInit = {},
): Promise<T> => {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `请求失败：${response.status}`);
  }
  return response.json() as Promise<T>;
};

export const post = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json", "X-Zhiyu-Request": "1" },
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
});

export const errorText = (error: unknown) =>
  error instanceof Error ? error.message : String(error);
