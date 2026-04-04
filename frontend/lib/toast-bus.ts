export type ToastPayload = {
  message: string;
  kind?: "success" | "error" | "info";
};

type ToastListener = (payload: ToastPayload) => void;

const listeners = new Set<ToastListener>();

/** Publish a toast. String argument defaults to kind "error" (legacy error toasts). */
export function emitToast(messageOrPayload: string | ToastPayload): void {
  const payload: ToastPayload =
    typeof messageOrPayload === "string"
      ? { message: messageOrPayload, kind: "error" }
      : { kind: messageOrPayload.kind ?? "info", message: messageOrPayload.message };
  listeners.forEach((fn) => {
    try {
      fn(payload);
    } catch {
      /* ignore */
    }
  });
}

export function subscribeToast(fn: ToastListener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
