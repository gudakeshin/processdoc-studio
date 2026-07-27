"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { useAuth } from "@/lib/auth-context";

interface SettingsData {
  web_search_provider?: string | null;
  tavily_enabled?: boolean;
  tavily_configured?: boolean;
}

export default function SettingsSearchPage() {
  const { api } = useAuth();
  const params = useParams();
  const pid =
    typeof params.pid === "string" ? params.pid : Array.isArray(params.pid) ? params.pid[0] ?? "" : "";

  const [provider, setProvider] = useState<string | null>(null);
  const [tavilyApiKey, setTavilyApiKey] = useState("");
  const [message, setMessage] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [tavilyGlobalConfigured, setTavilyGlobalConfigured] = useState(false);

  useEffect(() => {
    if (!pid.trim()) return;
    void api(`/api/projects/${encodeURIComponent(pid)}/settings`)
      .then(async (res) => {
        const data = (await res.json().catch(() => ({}))) as SettingsData;
        if (!res.ok) return;
        if (data.web_search_provider) {
          setProvider(data.web_search_provider);
        }
        if (data.tavily_configured) {
          setTavilyGlobalConfigured(true);
        }
      })
      .catch(() => {});
  }, [api, pid]);

  async function save() {
    if (!pid.trim()) return;
    setMessage("");
    const payload: { web_search_provider?: string | null; tavily_api_key?: string } = {};

    if (provider) {
      payload.web_search_provider = provider;
    }
    if (tavilyApiKey) {
      payload.tavily_api_key = tavilyApiKey;
    }

    const res = await api(`/api/projects/${encodeURIComponent(pid)}/settings`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      setMessage("✓ Search settings saved");
      setTavilyApiKey("");
    } else {
      setMessage("Failed to save settings");
    }
  }

  return (
    <div className="space-y-4 rounded-lg border border-[color:color-mix(in_srgb,var(--primary-700)_20%,transparent)] bg-white p-4 shadow-sm">
      <h2 className="text-lg font-semibold">Search Provider Settings</h2>
      <p className="text-sm text-[var(--primary-700)]">Choose your preferred web search provider.</p>

      <div className="space-y-3">
        <div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="provider"
              value="brave"
              checked={provider === "brave" || (provider === null && provider !== "google" && provider !== "tavily")}
              onChange={(e) => setProvider(e.target.value)}
              className="h-4 w-4"
            />
            <span>Brave (default)</span>
          </label>
          <p className="ml-6 text-xs text-[var(--text-muted)]">Primary search provider if configured globally.</p>
        </div>

        <div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="provider"
              value="tavily"
              checked={provider === "tavily"}
              onChange={(e) => setProvider(e.target.value)}
              className="h-4 w-4"
            />
            <span>Tavily {tavilyGlobalConfigured ? "(configured)" : "(not configured)"}</span>
          </label>
          <p className="ml-6 text-xs text-[var(--text-muted)]">Use Tavily for web searches if available.</p>
        </div>

        <div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="provider"
              value="google"
              checked={provider === "google"}
              onChange={(e) => setProvider(e.target.value)}
              className="h-4 w-4"
            />
            <span>Google Custom Search</span>
          </label>
          <p className="ml-6 text-xs text-[var(--text-muted)]">Use Google Custom Search if configured.</p>
        </div>
      </div>

      <div className="border-t border-[var(--primary-200)] pt-4">
        <button
          type="button"
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="text-sm font-medium text-[var(--primary-700)] hover:text-[var(--primary-900)]"
        >
          {showAdvanced ? "▼" : "▶"} Advanced Options
        </button>

        {showAdvanced && (
          <div className="mt-3 space-y-2 rounded-md bg-[var(--primary-50)] p-3">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={!!tavilyApiKey}
                onChange={(e) => {
                  if (!e.target.checked) {
                    setTavilyApiKey("");
                  }
                }}
                className="h-4 w-4"
              />
              <span>Use project-specific Tavily API key</span>
            </label>
            {tavilyApiKey !== "" && (
              <Input
                type="password"
                placeholder="Paste Tavily API key (tvly-...)"
                value={tavilyApiKey}
                onChange={(e) => setTavilyApiKey(e.target.value)}
                className="mt-2"
              />
            )}
            <p className="text-xs text-[var(--text-muted)]">
              Leave blank to use global configuration. Keys are stored in project settings.json.
            </p>
          </div>
        )}
      </div>

      <div className="flex gap-2">
        <Button onClick={() => void save()}>Save Settings</Button>
        {message && <p className="flex items-center text-sm text-[var(--text-muted)]">{message}</p>}
      </div>
    </div>
  );
}
