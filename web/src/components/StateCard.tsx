import type { ReactNode } from "react";

export function StateCard({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <article className="empty-panel">
      <h2>{title}</h2>
      {description && <p>{description}</p>}
      {action}
    </article>
  );
}
