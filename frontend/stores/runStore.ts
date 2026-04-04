"use client";

import { create } from "zustand";

type RunStore = {
  runId: string | null;
  status: string;
  events: string[];
  setRun: (runId: string) => void;
  setStatus: (status: string) => void;
  appendEvent: (line: string) => void;
  clear: () => void;
};

export const useRunStore = create<RunStore>((set) => ({
  runId: null,
  status: "idle",
  events: [],
  setRun: (runId) => set({ runId }),
  setStatus: (status) => set({ status }),
  appendEvent: (line) => set((s) => ({ events: [...s.events, line] })),
  clear: () => set({ runId: null, status: "idle", events: [] }),
}));
