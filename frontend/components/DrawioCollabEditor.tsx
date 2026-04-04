"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useAuth } from "@/lib/auth-context";
import { getApiBase } from "@/lib/api";
import { DrawioLockedBy, DrawioWsFromServer, DrawioWsToServer, toWsUrl } from "@/lib/drawio-collab";

function parseJsonMaybe(value: unknown): unknown {
  if (typeof value !== "string") return value;
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

export default function DrawioCollabEditor({
  pid,
  runId,
  initialXml,
}: {
  pid: string;
  runId: string;
  initialXml?: string | null;
}) {
  /* eslint-disable react-hooks/set-state-in-effect */
  const { token, email } = useAuth();
  const [lockedBy, setLockedBy] = useState<DrawioLockedBy | null>(null);
  const [revision, setRevision] = useState<number>(0);
  const [canEdit, setCanEdit] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lockMessage, setLockMessage] = useState<string | null>(null);
  const [diagramLoaded, setDiagramLoaded] = useState(false);
  const [loadWarning, setLoadWarning] = useState<string | null>(null);

  const canEditRef = useRef(canEdit);
  useEffect(() => {
    canEditRef.current = canEdit;
  }, [canEdit]);

  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const editorReadyRef = useRef(false);
  const pendingLoadXmlRef = useRef<string | null>(null);
  const requestedLockRef = useRef(false);
  const lastAutosaveXmlRef = useRef<string | null>(null);
  const autosaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const xmlHasBeenLoadedRef = useRef(false);
  const lastLoadedXmlRef = useRef<string | null>(null);
  const latestXmlRef = useRef<string | null>(null);

  const drawioBaseUrl = useMemo(() => {
    // Default to dedicated embed host so local setup works without running a separate draw.io container.
    const raw = process.env.NEXT_PUBLIC_DRAWIO_BASE_URL || "https://embed.diagrams.net";
    return raw.replace(/\/$/, "");
  }, []);

  const iframeSrcEdit = useMemo(() => {
    if (!drawioBaseUrl) return "";
    // `stealth=1&offline=1` reduces external dependencies (cloud storage/export services) for local collab.
    return `${drawioBaseUrl}/?embed=1&proto=json&stealth=1&offline=1&splash=0&spin=1&noExitBtn=1`;
  }, [drawioBaseUrl]);

  const iframeSrcReadOnly = useMemo(() => {
    if (!drawioBaseUrl) return "";
    // diagrams.net `chrome=0` enables the chromeless read-only viewer.
    // We keep `proto=json` so we can still use the postMessage `load` action for sync.
    return `${drawioBaseUrl}/?embed=1&proto=json&stealth=1&offline=1&splash=0&spin=1&noExitBtn=1&chrome=0&toolbar=0`;
  }, [drawioBaseUrl]);

  const iframeSrc = canEdit ? iframeSrcEdit : iframeSrcReadOnly;

  const requestLock = () => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    const m: DrawioWsToServer = { type: "request_lock" };
    wsRef.current.send(JSON.stringify(m));
  };

  const releaseLock = () => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    const m: DrawioWsToServer = { type: "release_lock" };
    wsRef.current.send(JSON.stringify(m));
  };

  function postToEditor(message: unknown) {
    const win = iframeRef.current?.contentWindow;
    if (!win) return;
    // diagrams.net uses postMessage with JSON-encoded objects.
    win.postMessage(typeof message === "string" ? message : JSON.stringify(message), "*");
  }

  const sendEditorLoad = useCallback((xml: string) => {
    // Enable autosave so we get {event:'autosave', xml:'...'} updates.
    if (!xmlHasBeenLoadedRef.current || lastLoadedXmlRef.current !== xml) {
      xmlHasBeenLoadedRef.current = true;
      lastLoadedXmlRef.current = xml;
      setDiagramLoaded(true);
    }
    postToEditor({ action: "load", xml, autosave: canEdit ? 1 : 0, modified: 0 });
    // Some embed builds respond better to open() than load() on first mount.
    postToEditor({ action: "open", xml });
  }, [canEdit]);

  useEffect(() => {
    if (!token || !pid || !runId) return;
    setError(null);
    setLockedBy(null);
    setRevision(0);
    setCanEdit(false);
    setLockMessage(null);
    setDiagramLoaded(false);
    setLoadWarning(null);
    editorReadyRef.current = false;
    requestedLockRef.current = false;
    pendingLoadXmlRef.current = null;
    xmlHasBeenLoadedRef.current = false;
    lastLoadedXmlRef.current = null;
    latestXmlRef.current = pendingLoadXmlRef.current;
    lastAutosaveXmlRef.current = null;

    const apiBase = getApiBase();
    const wsBase = toWsUrl(apiBase);
    const wsUrl = `${wsBase}/api/drawio/${encodeURIComponent(pid)}/${encodeURIComponent(runId)}/ws?token=${encodeURIComponent(
      token
    )}`;

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      // Wait for bootstrap before loading XML, but we can request lock immediately.
      requestedLockRef.current = false;
    };

    ws.onmessage = (ev) => {
      const body = parseJsonMaybe(ev.data) as DrawioWsFromServer | unknown;
      if (!body || typeof body !== "object") return;

      const msgType = (body as any).type;
      if (typeof msgType !== "string") return;

      if (msgType === "bootstrap") {
        const bootstrap = body as Extract<DrawioWsFromServer, { type: "bootstrap" }>;
        setLockedBy(bootstrap.locked_by);
        setRevision(bootstrap.revision);
        latestXmlRef.current = bootstrap.xml;
        if (typeof bootstrap.xml === "string" && bootstrap.xml.length) {
          if (!editorReadyRef.current) {
            pendingLoadXmlRef.current = bootstrap.xml;
          } else if (lastLoadedXmlRef.current !== bootstrap.xml) {
            sendEditorLoad(bootstrap.xml);
          }
        }

        // Request lock once we have a connection + bootstrap.
        if (!requestedLockRef.current) {
          requestedLockRef.current = true;
          const m: DrawioWsToServer = { type: "request_lock" };
          ws.send(JSON.stringify(m));
        }

        // Decide edit mode based on lock holder email.
        setCanEdit(bootstrap.locked_by?.email === email);
      } else if (msgType === "lock_acquired") {
        const m = body as Extract<DrawioWsFromServer, { type: "lock_acquired" }>;
        setCanEdit(true);
        setRevision(m.revision);
        setLockMessage("Lock acquired. You can edit the process map.");
      } else if (msgType === "lock_denied") {
        const m = body as Extract<DrawioWsFromServer, { type: "lock_denied" }>;
        setCanEdit(false);
        setLockedBy(m.locked_by);
        setRevision(m.revision);
        setLockMessage(
          m.locked_by ? `Diagram is locked by ${m.locked_by.email}. ${m.reason ? `(${m.reason})` : ""}` : "Lock denied."
        );
      } else if (msgType === "lock_update") {
        const m = body as Extract<DrawioWsFromServer, { type: "lock_update" }>;
        setLockedBy(m.locked_by);
        setRevision(m.revision);
        setCanEdit(m.locked_by?.email === email);
        setLockMessage(m.locked_by ? `Locked by ${m.locked_by.email}.` : "Lock released. You can request edit access.");
      } else if (msgType === "drawio_update") {
        const m = body as Extract<DrawioWsFromServer, { type: "drawio_update" }>;
        setRevision(m.revision);
        latestXmlRef.current = m.xml;

        // For now: if we are not the lock-holder, apply the broadcast XML to keep read-only view fresh.
        if (!canEditRef.current && typeof m.xml === "string" && m.xml.length) {
          pendingLoadXmlRef.current = m.xml;
          if (editorReadyRef.current) sendEditorLoad(m.xml);
        }
      }
    };

    ws.onerror = () => {
      // Keep the editor visible even if realtime channel is unavailable.
      setCanEdit(false);
      setLockMessage("Realtime collaboration channel unavailable. Falling back to local read-only mode.");
    };

    ws.onclose = () => {
      wsRef.current = null;
      setCanEdit(false);
    };

    return () => {
      ws.close();
    };
  }, [token, pid, runId, drawioBaseUrl, email, sendEditorLoad]);

  useEffect(() => {
    if (diagramLoaded) {
      setLoadWarning(null);
      return;
    }
    const t = window.setTimeout(() => {
      setLoadWarning(
        "Diagram is taking longer than expected to load. If this persists, verify network access to the diagrams.net host."
      );
    }, 8000);
    return () => window.clearTimeout(t);
  }, [diagramLoaded]);

  // If artifacts arrive after the editor mounts, we can still load the initial diagram immediately on editor init.
  useEffect(() => {
    if (typeof initialXml !== "string" || !initialXml.length) return;
    latestXmlRef.current = initialXml;
    pendingLoadXmlRef.current = initialXml;
    if (editorReadyRef.current) sendEditorLoad(initialXml);
  }, [initialXml, sendEditorLoad]);

  // When switching between edit/read-only modes, diagrams.net is loaded with different iframe parameters.
  // Force diagrams.net to reload the latest XML into the newly mounted iframe.
  useEffect(() => {
    setDiagramLoaded(false);
    xmlHasBeenLoadedRef.current = false;
    lastLoadedXmlRef.current = null;
    editorReadyRef.current = false;
    pendingLoadXmlRef.current = latestXmlRef.current;
  }, [canEdit]);

  useEffect(() => {
    function onMessage(ev: MessageEvent) {
      const iframeWin = iframeRef.current?.contentWindow;
      if (!iframeWin || ev.source !== iframeWin) return;

      const body = parseJsonMaybe(ev.data) as any;
      if (!body || typeof body !== "object") return;

      const evt = body.event;
      if (typeof evt !== "string") return;

      if (evt === "init") {
        editorReadyRef.current = true;
        const xml = pendingLoadXmlRef.current;
        if (typeof xml === "string" && xml.length) {
          if (!xmlHasBeenLoadedRef.current || lastLoadedXmlRef.current !== xml) sendEditorLoad(xml);
        }
      } else if (evt === "autosave") {
        // autosave comes from editor when the user changes the diagram.
        const xml = body.xml;
        if (typeof xml !== "string") return;
        if (!canEditRef.current) return;

        // Debounce + dedupe to avoid flooding the backend.
        if (lastAutosaveXmlRef.current === xml) return;
        lastAutosaveXmlRef.current = xml;

        if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
        autosaveTimerRef.current = setTimeout(() => {
          if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
          const m: DrawioWsToServer = { type: "autosave", xml };
          wsRef.current.send(JSON.stringify(m));
        }, 800);
      }
    }

    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [sendEditorLoad]);

  if (error) {
    return (
      <div style={{ border: "1px solid #ddd", padding: 12, borderRadius: 8 }}>
        <p style={{ color: "crimson" }}>{error}</p>
      </div>
    );
  }

  /* eslint-enable react-hooks/set-state-in-effect */
  return (
    <div style={{ display: "grid", gap: 8, width: "100%", minWidth: 0 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div>
          <strong>Process Map (draw.io)</strong>
          <div style={{ fontSize: 12, color: "#666", marginTop: 2 }}>
            Revision {revision}
            {lockedBy ? ` — locked by ${lockedBy.email}` : " — not locked"}
          </div>
        </div>
        <div style={{ fontSize: 12, color: canEdit ? "#0a6" : "#666" }}>{canEdit ? "Editing" : "Read-only"}</div>
      </div>

      {!diagramLoaded ? <p style={{ margin: 0, fontSize: 13, color: "#666" }}>Loading diagram…</p> : null}
      {loadWarning ? (
        <p style={{ margin: 0, fontSize: 12, color: "#8a6d3b" }}>
          {loadWarning}{" "}
          <a href={drawioBaseUrl} target="_blank" rel="noreferrer">
            Open diagrams.net
          </a>
        </p>
      ) : null}

      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        {canEdit ? (
          <button type="button" onClick={() => releaseLock()} style={{ padding: "6px 10px" }}>
            Release lock
          </button>
        ) : (
          <button
            type="button"
            onClick={() => requestLock()}
            style={{ padding: "6px 10px" }}
            disabled={lockedBy ? lockedBy.email !== email : false}
            title={lockedBy ? `Locked by ${lockedBy.email}` : "Request edit lock"}
          >
            Request edit lock
          </button>
        )}
        {lockMessage ? <span style={{ fontSize: 12, color: "#666" }}>{lockMessage}</span> : null}
      </div>

      {/* diagrams.net iframe */}
      <iframe
        key={canEdit ? "drawio-edit" : "drawio-readonly"}
        ref={iframeRef}
        src={iframeSrc}
        onLoad={() => {
          const xml = pendingLoadXmlRef.current || latestXmlRef.current;
          if (typeof xml === "string" && xml.length) {
            sendEditorLoad(xml);
          }
        }}
        style={{
          width: "100%",
          maxWidth: "100%",
          height: "clamp(360px, 60vh, 700px)",
          border: "1px solid #ddd",
          borderRadius: 8,
        }}
      />
    </div>
  );
}

