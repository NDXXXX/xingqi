export function isCurrentRequest(
  active: object | null,
  owner: object,
): boolean {
  return active === owner;
}
