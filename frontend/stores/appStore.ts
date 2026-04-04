"use client";

import { create } from "zustand";

type AppStore = {
  sidebarPinned: boolean;
  reducedMotion: boolean;
  setSidebarPinned: (pinned: boolean) => void;
  setReducedMotion: (reduced: boolean) => void;
};

export const useAppStore = create<AppStore>((set) => ({
  sidebarPinned: true,
  reducedMotion: false,
  setSidebarPinned: (pinned) => set({ sidebarPinned: pinned }),
  setReducedMotion: (reduced) => set({ reducedMotion: reduced }),
}));
