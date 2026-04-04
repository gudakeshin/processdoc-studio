import { getWsOriginForBrowser } from "./api";

export type DrawioLockedBy = { user_id: string; email: string };

export type DrawioWsToServer =
  | { type: "request_lock" }
  | { type: "release_lock" }
  | { type: "autosave"; xml: string };

export type DrawioWsFromServer =
  | {
      type: "bootstrap";
      project_id: string;
      run_id: string;
      xml: string;
      revision: number;
      locked_by: DrawioLockedBy | null;
    }
  | { type: "lock_acquired"; revision: number }
  | {
      type: "lock_denied";
      locked_by: DrawioLockedBy | null;
      revision: number;
      reason?: string;
    }
  | { type: "lock_update"; locked_by: DrawioLockedBy | null; revision: number }
  | {
      type: "drawio_update";
      xml: string;
      revision: number;
      by: DrawioLockedBy;
    };

export function toWsUrl(apiBase: string): string {
  if (!apiBase) return getWsOriginForBrowser();
  return apiBase.replace(/^http:/, "ws:").replace(/^https:/, "wss:");
}

