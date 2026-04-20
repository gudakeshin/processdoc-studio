"use client";

import React, { useState, useEffect, useCallback } from "react";
import { useAuth } from "@/lib/auth-context";

interface WikiSchemaEditorProps {
  wikiType: string
  projectId?: string
}

export default function WikiSchemaEditor({ wikiType, projectId }: WikiSchemaEditorProps) {
  const { api } = useAuth();
  const [schema, setSchema] = useState('')
  const [original, setOriginal] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState<'idle' | 'saved' | 'error'>('idle')
  const [errorMsg, setErrorMsg] = useState('')

  const apiBase = projectId
    ? `/api/wiki/${wikiType}/schema?project_id=${projectId}`
    : `/api/wiki/${wikiType}/schema`

  const fetchSchema = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api(apiBase)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const text = await res.text()
      setSchema(text)
      setOriginal(text)
    } catch (e: any) {
      setErrorMsg(e.message)
    } finally {
      setLoading(false)
    }
  }, [apiBase, api])

  useEffect(() => { fetchSchema() }, [fetchSchema])

  const handleSave = async () => {
    setSaving(true)
    setStatus('idle')
    try {
      const res = await api(apiBase, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: schema }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setOriginal(schema)
      setStatus('saved')
      setTimeout(() => setStatus('idle'), 2500)
    } catch (e: any) {
      setErrorMsg(e.message)
      setStatus('error')
    } finally {
      setSaving(false)
    }
  }

  const isDirty = schema !== original

  if (loading) return <div className="p-4 text-gray-500">Loading schema…</div>

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Wiki Schema</h2>
          <p className="text-sm text-gray-500">
            Edit conventions and the LLM will follow them on the next ingest or query.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {status === 'saved' && <span className="text-sm text-green-600">Saved ✓</span>}
          {status === 'error' && <span className="text-sm text-red-600">{errorMsg}</span>}
          <button
            onClick={handleSave}
            disabled={!isDirty || saving}
            className="px-4 py-1.5 text-sm rounded bg-blue-600 text-white disabled:opacity-40 hover:bg-blue-700"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
          {isDirty && (
            <button
              onClick={() => setSchema(original)}
              className="px-3 py-1.5 text-sm rounded border hover:bg-gray-50"
            >
              Discard
            </button>
          )}
        </div>
      </div>
      <textarea
        value={schema}
        onChange={e => setSchema(e.target.value)}
        className="w-full h-[60vh] font-mono text-sm border rounded p-3 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
        placeholder="# WIKI_SCHEMA.md&#10;&#10;Define your wiki conventions here…"
        spellCheck={false}
      />
    </div>
  )
}
