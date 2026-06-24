"use client";

import { useQuery } from "@tanstack/react-query";
import { createContext, useContext, type CSSProperties, type ReactNode } from "react";

import { parseResponseBodyLoose } from "./api-error";
import { useAuth } from "./auth-context";

// Mirrors the backend BrandingContext / ColorPalette dataclasses serialized by
// GET /api/projects/{pid}/branding (see backend/app/services/branding_service.py).
export type BrandPalette = {
  primary: string;
  complementary: string;
  accent_light: string;
  accent_dark: string;
  neutral_light: string;
  neutral_dark: string;
  text_primary: string;
  text_inverse: string;
};

export type Branding = {
  level: string;
  primary_color: string;
  palette: BrandPalette;
  font_family: string;
  font_size_base: number;
  logo_url: string | null;
  company_name: string;
  custom_footer_text: string | null;
  deck_theme: string;
};

const BrandingCtx = createContext<Branding | null>(null);

/** Resolved branding for the current project subtree, or null before it loads. */
export function useBranding(): Branding | null {
  return useContext(BrandingCtx);
}

/**
 * Map a resolved palette onto CSS custom properties for a scoped wrapper.
 *
 * We override only the primary brand-green tokens that components already
 * consume (`--deloitte-green`, `--accent-green`) so a project without a custom
 * brand — whose resolved primary equals the Deloitte green — renders
 * identically, and we deliberately leave the blue/complementary tokens alone
 * (the backend's complementary is a fixed secondary, not derived from a custom
 * primary, so binding it to the blue accents would shift them unexpectedly).
 * The full palette is exposed under a `--brand-*` namespace for opt-in use.
 */
export function brandingToCssVars(b: Branding | null): CSSProperties {
  const primary = b?.primary_color || b?.palette?.primary;
  if (!b || !primary) return {};
  const vars: Record<string, string> = {
    "--deloitte-green": primary,
    "--accent-green": primary,
    "--brand-primary": primary,
    "--brand-primary-dark": b.palette?.accent_dark || primary,
    "--brand-complementary": b.palette?.complementary || primary,
    "--brand-accent-light": b.palette?.accent_light || primary,
    "--brand-font-family": b.font_family,
  };
  return vars as CSSProperties;
}

/**
 * Fetches the active project's branding and injects it as CSS variables scoped
 * to its children, so project pages honor a custom brand while the global app
 * chrome (mounted above this layout) keeps the static defaults.
 */
export function BrandingProvider({
  projectId,
  children,
}: {
  projectId: string;
  children: ReactNode;
}) {
  const { api, ready } = useAuth();

  const { data } = useQuery({
    queryKey: ["branding", projectId],
    enabled: Boolean(projectId) && ready,
    queryFn: async (): Promise<Branding> => {
      const res = await api(`/api/projects/${encodeURIComponent(projectId)}/branding`);
      const { data: parsed } = await parseResponseBodyLoose(res);
      if (!res.ok) throw new Error(`Failed to load branding (${res.status})`);
      return parsed as Branding;
    },
  });

  const branding = data ?? null;

  return (
    <BrandingCtx.Provider value={branding}>
      <div style={brandingToCssVars(branding)}>{children}</div>
    </BrandingCtx.Provider>
  );
}
