"use client";

import { useParams } from "next/navigation";
import { useOutputFormats } from "@/hooks/useOutputFormats";
import { useAuth } from "@/lib/auth-context";

export default function SettingsFormatsPage() {
  const params = useParams();
  const pid = typeof params.pid === "string" ? params.pid : Array.isArray(params.pid) ? params.pid[0] ?? "" : "";
  const { token } = useAuth();
  const outputTypesQuery = useOutputFormats(pid, Boolean(token && pid));
  const outputTypes = outputTypesQuery.data ?? [];
  return (
    <div className="rounded-lg border border-[color:color-mix(in_srgb,var(--primary-700)_20%,transparent)] bg-white p-4 text-sm shadow-sm">
      <h2 className="text-base font-semibold">Output type catalog</h2>
      {outputTypesQuery.isLoading ? (
        <p className="mt-2 text-xs text-[var(--text-muted)]">Loading output types...</p>
      ) : null}
      {!outputTypesQuery.isLoading && outputTypes.length === 0 ? (
        <p className="mt-2 text-xs text-[var(--text-muted)]">No output types configured.</p>
      ) : null}
      <ul className="mt-2 space-y-1 text-xs text-[var(--text-muted)]">
        {outputTypes.map((item) => (
          <li key={item.output_type_id}>
            <strong>{item.display_name}</strong> ({item.output_type_id}) {item.is_default ? "- default" : ""}
          </li>
        ))}
      </ul>
    </div>
  );
}
