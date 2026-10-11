export function isLocalInferenceEndpoint(baseUrl?: string | null): boolean {
  if (!baseUrl) return false;
  try {
    const hostname = new URL(baseUrl).hostname.toLowerCase().replace(/^\[|\]$/g, "");
    if (hostname === "localhost" || hostname.endsWith(".localhost") || hostname.endsWith(".local")) return true;
    if (hostname === "::1" || /^f[cd][0-9a-f]{2}:/i.test(hostname) || /^fe[89ab][0-9a-f]:/i.test(hostname)) return true;
    const octets = hostname.split(".").map(Number);
    if (octets.length !== 4 || octets.some((octet) => !Number.isInteger(octet) || octet < 0 || octet > 255)) return false;
    const [first, second] = octets;
    return first === 10 || first === 127 || first === 169 && second === 254 ||
      first === 172 && second >= 16 && second <= 31 || first === 192 && second === 168;
  } catch {
    return false;
  }
}

export function modelDisclosureKey(model: { provider_id: string; base_url?: string | null }): string {
  return `${model.provider_id}:${model.base_url || "default"}`;
}
