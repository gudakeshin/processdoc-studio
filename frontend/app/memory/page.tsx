"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ProjectPicker } from "@/components/admin/ProjectPicker";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { useAuth } from "@/lib/auth-context";
import { extractApiErrorMessage } from "@/lib/api-error";

type MemoryItemRow = {
  id: string;
  memory_type: string;
  key: string;
  value: string;
  confidence: string;
  source: string;
  consent_state: string;
  principal_id?: string | null;
  is_archived: boolean;
  updated_at?: string | null;
};

type MemoryEventRow = {
  id: number;
  run_id: string;
  event_type: string;
  payload: string;
  created_at?: string | null;
};

type ProfileSummary = {
  summary: Record<string, unknown> | null;
  updated_at?: string | null;
};

const MEMORY_TYPES = ["preference", "constraint", "decision", "fact"] as const;
const CONSENT_STATES = ["allowed", "restricted", "denied"] as const;

export default function MemoryPage() {
  const { api, token } = useAuth();
  const [projectId, setProjectId] = useState("");
  const [filterType, setFilterType] = useState<string>("");
  const [searchQ, setSearchQ] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [items, setItems] = useState<MemoryItemRow[]>([]);
  const [itemsOffset, setItemsOffset] = useState(0);
  const [itemsHasMore, setItemsHasMore] = useState(false);
  const [recentEvents, setRecentEvents] = useState<MemoryEventRow[]>([]);
  const [eventTypeFilter, setEventTypeFilter] = useState("");
  const [eventOffset, setEventOffset] = useState(0);
  const [eventsHasMore, setEventsHasMore] = useState(false);
  const [profile, setProfile] = useState<ProfileSummary | null>(null);
  const [memSettings, setMemSettings] = useState<{
    memory_compaction_v1_enabled?: boolean;
    memory_respect_consent_in_context?: boolean;
    memory_enforce_consent_ledger?: boolean;
  } | null>(null);
  const [loadBusy, setLoadBusy] = useState(false);

  const [key, setKey] = useState("");
  const [value, setValue] = useState("");
  const [memoryType, setMemoryType] = useState<string>("preference");
  const [confidence, setConfidence] = useState("medium");
  const [source, setSource] = useState("manual");
  const [consentState, setConsentState] = useState<string>("allowed");
  const [principalId, setPrincipalId] = useState("");
  const [error, setError] = useState<string | null>(null);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editKey, setEditKey] = useState("");
  const [editValue, setEditValue] = useState("");
  const [editConfidence, setEditConfidence] = useState("");
  const [editSource, setEditSource] = useState("");
  const [editConsent, setEditConsent] = useState("");
  const [editPrincipal, setEditPrincipal] = useState("");
  const [saveBusy, setSaveBusy] = useState(false);

  const [batchJson, setBatchJson] = useState("");
  const [contextLines, setContextLines] = useState<string[]>([]);
  const [prefInput, setPrefInput] = useState("");
  const [prefsBusy, setPrefsBusy] = useState(false);

  const pageSize = 30;

  const load = useCallback(
    async (opts?: {
      resetItems?: boolean;
      resetEvents?: boolean;
      appendItems?: boolean;
      appendEvents?: boolean;
      itemOffset?: number;
      eventOffsetOverride?: number;
    }) => {
      if (!projectId.trim()) return;
      const iOff = opts?.resetItems ? 0 : (opts?.itemOffset ?? itemsOffset);
      const eOff = opts?.resetEvents ? 0 : (opts?.eventOffsetOverride ?? eventOffset);
      setLoadBusy(true);
      setError(null);
      try {
        const params = new URLSearchParams();
        if (filterType) params.set("memory_type", filterType);
        if (includeArchived) params.set("include_archived", "true");
        if (searchQ.trim()) params.set("q", searchQ.trim());
        params.set("limit", String(pageSize));
        params.set("offset", String(iOff));
        if (eventTypeFilter.trim()) params.set("event_type", eventTypeFilter.trim());
        params.set("event_limit", "20");
        params.set("event_offset", String(eOff));
        params.set("include_profile", "true");
        const qs = params.toString();
        const res = await api(`/api/memory/${encodeURIComponent(projectId.trim())}?${qs}`);
        const data = (await res.json().catch(() => ({}))) as {
          detail?: unknown;
          items?: MemoryItemRow[];
          items_has_more?: boolean;
          recent_events?: MemoryEventRow[];
          events_has_more?: boolean;
          project_memory_profile?: ProfileSummary | null;
          settings?: {
            memory_compaction_v1_enabled?: boolean;
            memory_respect_consent_in_context?: boolean;
            memory_enforce_consent_ledger?: boolean;
          };
        };
        if (!res.ok) {
          setError(extractApiErrorMessage(data, "Failed to load memory"));
          return;
        }
        const nextItems = Array.isArray(data.items) ? data.items : [];
        if (opts?.appendItems) {
          setItems((prev) => [...prev, ...nextItems]);
        } else {
          setItems(nextItems);
        }
        setItemsHasMore(Boolean(data.items_has_more));
        if (opts?.resetItems) setItemsOffset(0);
        const nextEv = Array.isArray(data.recent_events) ? data.recent_events : [];
        if (opts?.appendEvents) {
          setRecentEvents((prev) => [...prev, ...nextEv]);
        } else {
          setRecentEvents(nextEv);
        }
        setEventsHasMore(Boolean(data.events_has_more));
        if (opts?.resetEvents) setEventOffset(0);
        setProfile(data.project_memory_profile ?? null);
        setMemSettings(data.settings ?? null);
      } finally {
        setLoadBusy(false);
      }
    },
    [api, projectId, filterType, includeArchived, searchQ, itemsOffset, eventOffset, eventTypeFilter]
  );

  useEffect(() => {
    void load({ resetItems: true, resetEvents: true });
  }, [projectId, filterType, includeArchived, searchQ, eventTypeFilter, load]);

  const loadPrefs = useCallback(async () => {
    if (!projectId.trim()) return;
    const res = await api(`/api/projects/${encodeURIComponent(projectId.trim())}/me/preferences`);
    const data = (await res.json().catch(() => ({}))) as { context_lines?: string[] };
    if (res.ok && Array.isArray(data.context_lines)) {
      setContextLines(data.context_lines);
    }
  }, [api, projectId]);

  useEffect(() => {
    void loadPrefs();
  }, [loadPrefs]);

  async function add() {
    if (!projectId.trim() || !key.trim() || !value.trim()) return;
    setError(null);
    const res = await api(`/api/memory/${encodeURIComponent(projectId.trim())}`, {
      method: "POST",
      body: JSON.stringify({
        memory_type: memoryType,
        key: key.trim(),
        value: value.trim(),
        confidence,
        source,
        consent_state: consentState,
        principal_id: principalId.trim() || null,
      }),
    });
    const data = (await res.json().catch(() => ({}))) as { detail?: unknown };
    if (!res.ok) {
      setError(extractApiErrorMessage(data, "Failed to add memory"));
      return;
    }
    setKey("");
    setValue("");
    setPrincipalId("");
    await load({ resetItems: true, resetEvents: true });
  }

  async function submitBatch() {
    if (!projectId.trim() || !batchJson.trim()) return;
    setError(null);
    let parsed: unknown;
    try {
      parsed = JSON.parse(batchJson.trim());
    } catch {
      setError("Batch field must be valid JSON (array of {key, value, memory_type?}).");
      return;
    }
    if (!Array.isArray(parsed) || !parsed.length) {
      setError("Batch JSON must be a non-empty array.");
      return;
    }
    const itemsPayload = parsed.map((row: unknown) => {
      if (!row || typeof row !== "object") return null;
      const o = row as Record<string, unknown>;
      return {
        key: String(o.key ?? ""),
        value: String(o.value ?? ""),
        memory_type: String(o.memory_type ?? "fact"),
        confidence: String(o.confidence ?? "medium"),
        source: String(o.source ?? "batch"),
        consent_state: String(o.consent_state ?? "allowed"),
        principal_id:
          o.principal_id !== undefined && o.principal_id !== null ? String(o.principal_id).trim() || null : null,
      };
    });
    const cleaned = itemsPayload.filter((x) => x && x.key && x.value) as {
      key: string;
      value: string;
      memory_type: string;
      confidence: string;
      source: string;
      consent_state: string;
      principal_id: string | null;
    }[];
    if (!cleaned.length) {
      setError("Each batch item needs key and value.");
      return;
    }
    const res = await api(`/api/memory/${encodeURIComponent(projectId.trim())}/batch`, {
      method: "POST",
      body: JSON.stringify({ items: cleaned }),
    });
    const data = (await res.json().catch(() => ({}))) as { detail?: unknown };
    if (!res.ok) {
      setError(extractApiErrorMessage(data, "Batch create failed"));
      return;
    }
    setBatchJson("");
    await load({ resetItems: true, resetEvents: true });
  }

  async function savePreferences() {
    if (!projectId.trim()) return;
    setPrefsBusy(true);
    setError(null);
    try {
      const lines = prefInput
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean);
      const res = await api(`/api/projects/${encodeURIComponent(projectId.trim())}/me/preferences`, {
        method: "PATCH",
        body: JSON.stringify({ context_lines: [...contextLines, ...lines] }),
      });
      const data = (await res.json().catch(() => ({}))) as { detail?: unknown };
      if (!res.ok) {
        setError(extractApiErrorMessage(data, "Failed to save preferences"));
        return;
      }
      setPrefInput("");
      await loadPrefs();
    } finally {
      setPrefsBusy(false);
    }
  }

  async function removeItem(itemId: string) {
    const res = await api(`/api/memory/${encodeURIComponent(projectId.trim())}/${encodeURIComponent(itemId)}`, {
      method: "DELETE",
    });
    if (res.ok) await load({ resetItems: true, resetEvents: false });
  }

  async function archiveItem(item: MemoryItemRow) {
    setSaveBusy(true);
    setError(null);
    try {
      const res = await api(`/api/memory/${encodeURIComponent(projectId.trim())}/${encodeURIComponent(item.id)}`, {
        method: "PATCH",
        body: JSON.stringify({
          memory_type: item.memory_type,
          key: item.key,
          value: item.value,
          confidence: item.confidence,
          source: item.source,
          consent_state: item.consent_state,
          principal_id: item.principal_id ?? null,
          is_archived: true,
        }),
      });
      const data = (await res.json().catch(() => ({}))) as { detail?: unknown };
      if (!res.ok) {
        setError(extractApiErrorMessage(data, "Archive failed"));
        return;
      }
      setEditingId(null);
      await load({ resetItems: true, resetEvents: false });
    } finally {
      setSaveBusy(false);
    }
  }

  function startEdit(item: MemoryItemRow) {
    setEditingId(item.id);
    setEditKey(item.key);
    setEditValue(item.value);
    setEditConfidence(item.confidence);
    setEditSource(item.source);
    setEditConsent(item.consent_state);
    setEditPrincipal(item.principal_id ?? "");
  }

  async function saveEdit(item: MemoryItemRow) {
    setSaveBusy(true);
    setError(null);
    try {
      const res = await api(`/api/memory/${encodeURIComponent(projectId.trim())}/${encodeURIComponent(item.id)}`, {
        method: "PATCH",
        body: JSON.stringify({
          memory_type: item.memory_type,
          key: editKey.trim(),
          value: editValue.trim(),
          confidence: editConfidence.trim() || item.confidence,
          source: editSource.trim() || item.source,
          consent_state: editConsent.trim() || item.consent_state,
          principal_id: editPrincipal.trim() || null,
          is_archived: item.is_archived,
        }),
      });
      const data = (await res.json().catch(() => ({}))) as { detail?: unknown };
      if (!res.ok) {
        setError(extractApiErrorMessage(data, "Update failed"));
        return;
      }
      setEditingId(null);
      await load({ resetItems: true, resetEvents: false });
    } finally {
      setSaveBusy(false);
    }
  }

  if (!token) {
    return (
      <div className="p-4">
        <p className="text-sm text-[var(--text-muted)]">Sign in to manage project memory.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4 p-2 sm:p-4">
      <div>
        <h1 className="text-2xl font-semibold">Memory</h1>
        <p className="text-sm text-[var(--text-muted)]">
          Long-lived memory items and run-linked memory events. When{" "}
          <code className="rounded bg-[var(--primary-100)] px-1 text-xs">memory_compaction_v1_enabled</code> is on (default),
          items and events feed the coordinator&apos;s assembled context. Restricted consent rows can be excluded when{" "}
          <code className="rounded bg-[var(--primary-100)] px-1 text-xs">memory_respect_consent_in_context</code> is enabled.
        </p>
        {memSettings ? (
          <p className="mt-1 text-xs text-[var(--text-caption)]">
            API: compaction={String(memSettings.memory_compaction_v1_enabled)} · consent_filter=
            {String(memSettings.memory_respect_consent_in_context)} · ledger_enforce=
            {String(memSettings.memory_enforce_consent_ledger)}
          </p>
        ) : null}
      </div>

      <Card className="space-y-3 p-4">
        <ProjectPicker value={projectId} onChange={setProjectId} />
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--text-muted)]">Filter type</label>
            <select
              className="input-select-base w-full min-h-11"
              value={filterType}
              onChange={(e) => setFilterType(e.target.value)}
              disabled={!projectId}
            >
              <option value="">All types</option>
              {MEMORY_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          <div className="min-w-[140px] flex-1">
            <label className="mb-1 block text-xs font-medium text-[var(--text-muted)]">Search key/value</label>
            <Input
              placeholder="Substring…"
              value={searchQ}
              onChange={(e) => setSearchQ(e.target.value)}
              disabled={!projectId}
            />
          </div>
          <label className="flex items-center gap-2 text-sm text-[var(--text-default)]">
            <input
              type="checkbox"
              checked={includeArchived}
              onChange={(e) => setIncludeArchived(e.target.checked)}
              disabled={!projectId}
            />
            Include archived
          </label>
          <Button type="button" variant="secondary" onClick={() => void load({ resetItems: true, resetEvents: true })} disabled={!projectId || loadBusy}>
            {loadBusy ? "Refreshing…" : "Refresh"}
          </Button>
        </div>
        {projectId ? (
          <p className="text-xs text-[var(--text-caption)]">
            <Link href={`/projects/${projectId}/settings/dpdp`} className="text-[var(--accent-blue)] underline">
              Project DPDP settings
            </Link>
            {" · "}
            <Link href="/admin/dpdp" className="text-[var(--accent-blue)] underline">
              Admin DPDP
            </Link>
            {" — tie consent for personal data to memory rows (consent_state)."}
          </p>
        ) : null}
      </Card>

      {profile?.summary && Object.keys(profile.summary).length > 0 ? (
        <Card className="space-y-2 p-4">
          <h2 className="text-base font-semibold">Project memory profile (runner)</h2>
          <p className="text-xs text-[var(--text-caption)]">Last upsert after successful runs. {profile.updated_at ? `Updated ${profile.updated_at}` : ""}</p>
          <pre className="max-h-40 overflow-auto rounded border bg-[var(--surface-muted)] p-2 text-[11px] text-[var(--text-default)]">
            {JSON.stringify(profile.summary, null, 2)}
          </pre>
        </Card>
      ) : null}

      <Card className="space-y-3 p-4">
        <h2 className="text-base font-semibold">My context lines (this user + project)</h2>
        <p className="text-xs text-[var(--text-caption)]">
          Merged into coordinator &quot;NonNegotiables&quot; for your runs. Add one line per row below, then Save.
        </p>
        {contextLines.length ? (
          <ul className="list-inside list-disc text-sm text-[var(--text-default)]">
            {contextLines.map((line, i) => (
              <li key={`${i}-${line.slice(0, 24)}`}>{line}</li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-[var(--text-caption)]">None saved yet.</p>
        )}
        <Textarea
          placeholder="One preference per line…"
          value={prefInput}
          onChange={(e) => setPrefInput(e.target.value)}
          disabled={!projectId}
          rows={3}
        />
        <Button type="button" variant="secondary" onClick={() => void savePreferences()} disabled={!projectId || prefsBusy}>
          {prefsBusy ? "Saving…" : "Append lines"}
        </Button>
      </Card>

      <Card className="space-y-3 p-4">
        <h2 className="text-base font-semibold">Add memory item</h2>
        <div className="grid gap-2 sm:grid-cols-2">
          <select
            className="input-select-base w-full min-h-11"
            value={memoryType}
            onChange={(e) => setMemoryType(e.target.value)}
            disabled={!projectId}
          >
            {MEMORY_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <Input
            placeholder="Confidence"
            value={confidence}
            onChange={(e) => setConfidence(e.target.value)}
            disabled={!projectId}
          />
          <Input placeholder="Source" value={source} onChange={(e) => setSource(e.target.value)} disabled={!projectId} />
          <select
            className="input-select-base w-full min-h-11"
            value={consentState}
            onChange={(e) => setConsentState(e.target.value)}
            disabled={!projectId}
          >
            {CONSENT_STATES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <Input
            className="sm:col-span-2"
            placeholder="Principal ID (optional — Consent Ledger when enforcement is on)"
            value={principalId}
            onChange={(e) => setPrincipalId(e.target.value)}
            disabled={!projectId}
          />
        </div>
        <Input placeholder="Key" value={key} onChange={(e) => setKey(e.target.value)} disabled={!projectId} />
        <Textarea placeholder="Value" value={value} onChange={(e) => setValue(e.target.value)} disabled={!projectId} rows={3} />
        <Button type="button" onClick={() => void add()} disabled={!projectId}>
          Save
        </Button>
      </Card>

      <Card className="space-y-2 p-4">
        <h2 className="text-base font-semibold">Batch add (JSON)</h2>
        <p className="text-xs text-[var(--text-caption)]">
          POST <code className="rounded bg-[var(--primary-100)] px-0.5">/api/memory/&#123;project&#125;/batch</code> — array of{" "}
          <code className="rounded bg-[var(--primary-100)] px-0.5">&#123; key, value, memory_type? &#125;</code> after you confirm (HITL).
        </p>
        <Textarea
          value={batchJson}
          onChange={(e) => setBatchJson(e.target.value)}
          disabled={!projectId}
          rows={5}
          placeholder='[{"key":"Tone","value":"Formal","memory_type":"preference"}]'
        />
        <Button type="button" variant="secondary" onClick={() => void submitBatch()} disabled={!projectId}>
          Import batch
        </Button>
      </Card>

      {error ? <div className="alert alert--error">{error}</div> : null}

      <details className="rounded-lg border border-[var(--surface-border-strong)] bg-white p-4" open>
        <summary className="cursor-pointer text-base font-semibold text-[var(--text-default)]">Run memory audit (events)</summary>
        <div className="mt-2 flex flex-wrap gap-2">
          <Input
            placeholder="Event type filter"
            value={eventTypeFilter}
            onChange={(e) => setEventTypeFilter(e.target.value)}
            disabled={!projectId}
            className="max-w-xs"
          />
          <Button
            type="button"
            variant="secondary"
            onClick={() => {
              setEventOffset(0);
              void load({ resetEvents: true, eventOffsetOverride: 0 });
            }}
            disabled={!projectId}
          >
            Apply event filter
          </Button>
        </div>
        {!recentEvents.length ? (
          <div className="mt-2">
            <EmptyState title="No memory events in this window" description="Adjust filters or load more after new runs complete." />
          </div>
        ) : (
          <ul className="mt-3 space-y-2 text-xs text-[var(--text-default)]">
            {recentEvents.map((ev, idx) => {
              let preview = ev.payload;
              try {
                const parsed = JSON.parse(ev.payload) as unknown;
                const s = JSON.stringify(parsed);
                preview = s.slice(0, 280) + (s.length > 280 ? "…" : "");
              } catch {
                preview = ev.payload.slice(0, 280) + (ev.payload.length > 280 ? "…" : "");
              }
              return (
                <li key={`${ev.id}-${idx}`} className="rounded border border-[var(--surface-border)] bg-[var(--surface-muted)] p-2">
                  <strong>{ev.event_type}</strong>
                  <span className="text-[var(--text-caption)]">
                    {" "}
                    · run{" "}
                    <Link href={`/projects/${projectId}/runs/${ev.run_id}`} className="text-[var(--accent-blue)] underline">
                      {ev.run_id}
                    </Link>
                  </span>
                  {ev.created_at ? <span className="text-[var(--text-caption)]"> · {ev.created_at}</span> : null}
                  <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap font-mono text-[11px]">{preview}</pre>
                </li>
              );
            })}
          </ul>
        )}
        {eventsHasMore && projectId ? (
          <Button
            type="button"
            variant="ghost"
            className="mt-2"
            onClick={() => {
              const next = eventOffset + 20;
              setEventOffset(next);
              void load({ appendEvents: true, eventOffsetOverride: next });
            }}
          >
            Load more events
          </Button>
        ) : null}
      </details>

      <section>
        <h2 className="text-lg font-semibold">Items</h2>
        {!projectId ? (
          <p className="mt-2 text-sm text-[var(--text-caption)]">Select a project.</p>
        ) : !items.length ? (
          <div className="mt-2">
            <EmptyState title="No items match this filter" description="Try clearing the type filter or search substring." />
          </div>
        ) : (
          <ul className="mt-2 space-y-3">
            {items.map((item) => (
              <li key={item.id} className="rounded-lg border border-[var(--surface-border-strong)] bg-white p-3 text-sm">
                {editingId === item.id ? (
                  <div className="space-y-2">
                    <div className="grid gap-2 sm:grid-cols-2">
                      <Input value={editConfidence} onChange={(e) => setEditConfidence(e.target.value)} placeholder="confidence" />
                      <Input value={editSource} onChange={(e) => setEditSource(e.target.value)} placeholder="source" />
                      <select
                        className="input-select-base w-full min-h-11"
                        value={editConsent}
                        onChange={(e) => setEditConsent(e.target.value)}
                      >
                        {CONSENT_STATES.map((c) => (
                          <option key={c} value={c}>
                            {c}
                          </option>
                        ))}
                      </select>
                      <Input
                        className="sm:col-span-2"
                        value={editPrincipal}
                        onChange={(e) => setEditPrincipal(e.target.value)}
                        placeholder="Principal ID (optional)"
                      />
                    </div>
                    <Input value={editKey} onChange={(e) => setEditKey(e.target.value)} />
                    <Textarea rows={4} value={editValue} onChange={(e) => setEditValue(e.target.value)} />
                    <div className="flex flex-wrap gap-2">
                      <Button type="button" onClick={() => void saveEdit(item)} disabled={saveBusy}>
                        Save
                      </Button>
                      <Button type="button" variant="ghost" onClick={() => setEditingId(null)} disabled={saveBusy}>
                        Cancel
                      </Button>
                    </div>
                  </div>
                ) : (
                  <>
                    <p className="font-medium text-[var(--text-default)]">
                      {item.memory_type}: {item.key}{" "}
                      {item.is_archived ? (
                        <span className="status-pill status-pill--warning">archived</span>
                      ) : null}
                    </p>
                    <p className="mt-1 whitespace-pre-wrap text-[var(--text-default)]">{item.value}</p>
                    <p className="mt-1 text-xs text-[var(--text-caption)]">
                      confidence {item.confidence} · source {item.source} · consent {item.consent_state}
                      {item.principal_id ? ` · principal ${item.principal_id}` : ""}
                      {item.updated_at ? ` · updated ${item.updated_at}` : ""}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <Button type="button" variant="secondary" onClick={() => startEdit(item)} disabled={item.is_archived}>
                        Edit
                      </Button>
                      {!item.is_archived ? (
                        <Button type="button" variant="secondary" onClick={() => void archiveItem(item)} disabled={saveBusy}>
                          Archive
                        </Button>
                      ) : null}
                      <Button
                        type="button"
                        variant="ghost"
                        className="min-h-11 text-[var(--error)]"
                        onClick={() => void removeItem(item.id)}
                      >
                        Delete
                      </Button>
                    </div>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
        {itemsHasMore && projectId ? (
          <Button
            type="button"
            variant="secondary"
            className="mt-3"
            onClick={() => {
              const next = itemsOffset + pageSize;
              setItemsOffset(next);
              void load({ appendItems: true, itemOffset: next });
            }}
          >
            Load more items
          </Button>
        ) : null}
      </section>

      {projectId ? (
        <p className="text-xs text-[var(--text-caption)]">
          <Link href={`/projects/${projectId}`} className="text-[var(--accent-blue)] underline">
            Back to project
          </Link>
        </p>
      ) : null}
    </div>
  );
}
