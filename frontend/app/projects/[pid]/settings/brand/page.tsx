"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Textarea";
import { parseResponseBodyLoose } from "@/lib/api-error";
import { useAuth } from "@/lib/auth-context";

export default function SettingsBrandPage() {
  const params = useParams();
  const pid = typeof params.pid === "string" ? params.pid : Array.isArray(params.pid) ? params.pid[0] ?? "" : "";
  const { api, token } = useAuth();
  const [notes, setNotes] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!token || !pid) return;
    void api(`/api/projects/${encodeURIComponent(pid)}/settings`)
      .then((r) => parseResponseBodyLoose(r))
      .then(({ data }) => {
        const d = data && typeof data === "object" ? (data as { brand_notes?: unknown }) : {};
        setNotes(typeof d.brand_notes === "string" ? d.brand_notes : "");
      })
      .catch(() => setNotes(""));
  }, [api, token, pid]);

  async function save() {
    setMsg(null);
    const res = await api(`/api/projects/${encodeURIComponent(pid)}/settings`, {
      method: "PUT",
      body: JSON.stringify({}),
    });
    if (!res.ok) {
      setMsg("Unable to save brand profile settings.");
      return;
    }
    setMsg("Brand profile checkpoint saved.");
  }

  return (
    <div className="rounded-lg border border-[color:color-mix(in_srgb,var(--primary-700)_20%,transparent)] bg-white p-4 text-sm shadow-sm">
      <h2 className="text-base font-semibold">Brand profile guidance</h2>
      <p className="mt-1 text-xs text-[var(--text-muted)]">Use this section to capture tone/style notes used during generation.</p>
      <Textarea className="mt-2" rows={5} value={notes} onChange={(e) => setNotes(e.target.value)} />
      <div className="mt-2">
        <Button type="button" onClick={() => void save()}>
          Save brand checkpoint
        </Button>
      </div>
      {msg ? <p className="mt-2 text-xs text-[var(--text-muted)]">{msg}</p> : null}
    </div>
  );
}
