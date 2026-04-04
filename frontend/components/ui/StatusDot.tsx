export function StatusDot({
  status,
  describedBy,
  label,
}: {
  status: "ok" | "warn" | "error";
  /**
   * Use when a surrounding element provides the human-friendly meaning.
   * (We set `aria-describedby` to associate the dot with that text.)
   */
  describedBy?: string;
  /**
   * Use to override the default screen-reader label.
   */
  label?: string;
}) {
  const color =
    status === "ok"
      ? "bg-[var(--success)]"
      : status === "warn"
        ? "bg-[var(--warning)]"
        : "bg-[var(--error)]";

  const defaultLabel = status === "ok" ? "OK" : status === "warn" ? "Warning" : "Error";
  const srLabel = label ?? `Status: ${defaultLabel}`;

  return (
    <span
      className={`inline-block h-2.5 w-2.5 rounded-full ${color}`}
      role="img"
      aria-label={srLabel}
      aria-describedby={describedBy}
    />
  );
}
