import type React from "react";

/**
 * Activate a click-style handler on Enter or Space for elements that carry
 * role="button" (so keyboard users get parity with onClick).
 */
export function activateOnKey(handler: () => void) {
  return (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      handler();
    }
  };
}
