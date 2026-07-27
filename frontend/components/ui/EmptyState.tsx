import type { ReactNode } from "react";
import { Inbox } from "lucide-react";

type Props = {
  title: string;
  description?: string;
  children?: ReactNode;
};

export function EmptyState({ title, description, children }: Props) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 border border-[var(--surface-border-strong)] bg-[var(--surface-muted)] px-6 py-10 text-center">
      <Inbox className="h-10 w-10 text-[var(--text-caption)]" aria-hidden />
      <div>
        <p className="text-sm font-semibold text-[var(--text-default)]">{title}</p>
        {description ? <p className="mt-1 text-2xs text-[var(--text-muted)]">{description}</p> : null}
      </div>
      {children ? <div className="flex flex-wrap justify-center gap-2">{children}</div> : null}
    </div>
  );
}
