"use client";

import { create } from "zustand";

type ProjectStore = {
  activeProjectId: string | null;
  activeRunId: string | null;
  setActiveProject: (id: string) => void;
  setActiveRun: (id: string | null) => void;
};

export const useProjectStore = create<ProjectStore>((set) => ({
  activeProjectId: null,
  activeRunId: null,
  setActiveProject: (id) => set({ activeProjectId: id }),
  setActiveRun: (id) => set({ activeRunId: id }),
}));
