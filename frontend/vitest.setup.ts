import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Vitest globals are off, so RTL can't auto-register its cleanup. Unmount after
// each test to keep renders from accumulating across `it` blocks in a file.
afterEach(() => {
  cleanup();
});
