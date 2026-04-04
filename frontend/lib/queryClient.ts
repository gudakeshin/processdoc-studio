import { QueryClient } from "@tanstack/react-query";

import { emitToast } from "@/lib/toast-bus";

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60_000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          if (failureCount >= 2) return false;
          const msg = error instanceof Error ? error.message : "";
          if (msg.includes("aborted")) return false;
          return true;
        },
      },
      mutations: {
        retry: false,
        onError: (error) => {
          const msg = error instanceof Error ? error.message : "Something went wrong";
          emitToast(msg);
        },
      },
    },
  });
}
