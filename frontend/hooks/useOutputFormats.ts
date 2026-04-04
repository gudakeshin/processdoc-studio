"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { useAuth } from "@/lib/auth-context";

export type OutputType = {
  output_type_id: string;
  display_name: string;
  description?: string;
  is_default?: boolean;
};

export function useOutputFormats(projectId: string, enabled = true) {
  const { api, token } = useAuth();

  const query = useQuery({
    queryKey: ["output-types", projectId],
    enabled: enabled && Boolean(token && projectId),
    queryFn: async (): Promise<OutputType[]> => {
      const res = await api(`/api/workspace/${encodeURIComponent(projectId)}/output-types`);
      const data = (await res.json().catch(() => ({}))) as {
        detail?: string;
        items?: Array<Partial<OutputType>>;
      };
      if (!res.ok) {
        throw new Error(typeof data.detail === "string" ? data.detail : "Failed to load output types");
      }
      return (data.items ?? [])
        .filter(
          (item): item is OutputType =>
            typeof item.output_type_id === "string" && item.output_type_id.length > 0
        )
        .map((item) => ({
          output_type_id: item.output_type_id,
          display_name:
            typeof item.display_name === "string" ? item.display_name : item.output_type_id,
          description: typeof item.description === "string" ? item.description : undefined,
          is_default: Boolean(item.is_default),
        }));
    },
  });

  const defaultOutputTypeId = useMemo(() => {
    const items = query.data ?? [];
    if (!items.length) return null;
    return items.find((item) => item.is_default)?.output_type_id ?? items[0].output_type_id;
  }, [query.data]);

  return { ...query, defaultOutputTypeId };
}
