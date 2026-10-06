import type { Item } from "./types";

export const stamp = (value: string) =>
  value ? new Date(value).toLocaleString() : "";

export const parseList = (value: string): Item[] => {
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
};
