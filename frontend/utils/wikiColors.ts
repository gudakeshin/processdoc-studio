/**
 * Shared color/style utilities for wiki components.
 * Single source of truth — replaces 11 duplicate confidenceColor objects.
 */

/** Maps confidence level to a CSS class string for inline badge styling */
export const confidenceClass: Record<string, string> = {
  high:   'bg-[var(--success-light)] text-[var(--success)] border-[var(--success)]',
  medium: 'bg-[var(--warning-light)] text-[var(--warning)] border-[var(--warning)]',
  low:    'bg-[var(--error-light)]   text-[var(--error)]   border-[var(--error)]',
};

/** Maps severity level to border-left accent color for issue cards */
export const severityBorderColor: Record<string, string> = {
  high:   'var(--error)',
  medium: 'var(--warning)',
  low:    'var(--success)',
};

/** Maps severity level to background and text colors for stat cards */
export const severityBg: Record<string, string> = {
  high:   'bg-[var(--error-light)]   text-[var(--error)]',
  medium: 'bg-[var(--warning-light)] text-[var(--warning)]',
  low:    'bg-[var(--success-light)] text-[var(--success)]',
};

/** Maps severity level to a border-left CSS class for issue suggestion boxes */
export const severityBorder: Record<string, string> = {
  high:   'border-[var(--error)]',
  medium: 'border-[var(--warning)]',
  low:    'border-[var(--success)]',
};
