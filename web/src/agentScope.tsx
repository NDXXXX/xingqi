import { createContext, useContext, useMemo } from "react";
import { request } from "./api";

export const AgentScope = createContext<string | null>(null);

export function agentUrl(url: string, characterId: string | null): string {
  if (!characterId) return url;
  return `${url}${url.includes("?") ? "&" : "?"}character_id=${encodeURIComponent(characterId)}`;
}

export function agentRequest(characterId: string | null) {
  return <T,>(url: string, options?: RequestInit) => request<T>(agentUrl(url, characterId), options);
}

export function useAgentRequest() {
  const characterId = useContext(AgentScope);
  return useMemo(() => agentRequest(characterId), [characterId]);
}
