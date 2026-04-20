"use client";

import { useAuth } from '@/lib/auth-context';
/**
 * WikiPagePreview - Inline preview popup for wiki pages
 *
 * Features:
 * - Quick preview on hover
 * - Configurable trigger (hover, click, none)
 * - Shows page summary and key metadata
 * - Link to full page
 * - Responsive positioning
 */

import React, { useState, useRef, useEffect, useCallback } from 'react';
import Link from 'next/link';

interface PageSummary {
  id: string;
  title: string;
  category: string;
  confidence: string;
  summary: string;
  updated_at: string;
  pages_linking: number;
  outbound_links_count: number;
}

interface WikiPagePreviewProps {
  pageId: string;
  wikiType: 'leading_practice' | 'project';
  projectId?: string;
  trigger?: 'hover' | 'click' | 'none';
  children?: React.ReactNode;
  className?: string;
}

export const WikiPagePreview: React.FC<WikiPagePreviewProps> = ({
  pageId,
  wikiType,
  projectId,
  trigger = 'hover',
  children,
  className = '',
}) => {
  const { api } = useAuth();
  const [page, setPage] = useState<PageSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [position, setPosition] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
  const triggerRef = useRef<HTMLDivElement>(null);
  const previewRef = useRef<HTMLDivElement>(null);

  const fetchPage = useCallback(async () => {
    if (page) return;

    try {
      setLoading(true);
      const params = new URLSearchParams();
      if (projectId) params.append('project_id', projectId);

      const response = await api(
        `/api/wiki/${wikiType}/pages/${pageId}/preview?${params.toString()}`,
        { method: 'GET' }
      );

      if (!response.ok) throw new Error('Failed to load preview');

      const data = await response.json();
      setPage(data.page);
    } catch (err) {
      console.error('Preview load error:', err);
    } finally {
      setLoading(false);
    }
  }, [page, pageId, projectId, wikiType, api]);

  const updatePosition = () => {
    if (!triggerRef.current || !previewRef.current) return;

    const rect = triggerRef.current.getBoundingClientRect();
    const previewRect = previewRef.current.getBoundingClientRect();

    let top = rect.bottom + 8;
    let left = rect.left;

    // Adjust if preview goes off-screen
    if (left + 300 > window.innerWidth) {
      left = window.innerWidth - 300 - 8;
    }

    if (top + previewRect.height > window.innerHeight) {
      top = rect.top - previewRect.height - 8;
    }

    setPosition({ top, left });
  };

  useEffect(() => {
    if (isOpen) {
      fetchPage();
      const timer = setTimeout(updatePosition, 0);
      return () => clearTimeout(timer);
    }
  }, [isOpen, fetchPage]);

  const handleMouseEnter = () => {
    if (trigger === 'hover') {
      setIsOpen(true);
    }
  };

  const handleMouseLeave = () => {
    if (trigger === 'hover') {
      setIsOpen(false);
    }
  };

  const handleClick = () => {
    if (trigger === 'click') {
      setIsOpen(!isOpen);
    }
  };

  const confidenceColor = {
    high: 'text-green-700 bg-green-100',
    medium: 'text-yellow-700 bg-yellow-100',
    low: 'text-red-700 bg-red-100',
  };

  return (
    <div
      ref={triggerRef}
      className={`relative inline ${className}`}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onClick={handleClick}
    >
      {/* Trigger Element */}
      {children || (
        <Link href={`/wiki/${wikiType}/pages/${pageId}`} className="text-blue-600 hover:underline cursor-help">
            Page Preview
        </Link>
      )}

      {/* Preview Popup */}
      {isOpen && (
        <div
          ref={previewRef}
          className="fixed z-50 bg-white border rounded-lg shadow-lg overflow-hidden"
          style={{
            top: `${position.top}px`,
            left: `${position.left}px`,
            width: '320px',
            maxHeight: '400px',
            overflowY: 'auto',
          }}
          onMouseEnter={() => {
            if (trigger === 'hover') {
              // Keep open while hovering preview
            }
          }}
          onMouseLeave={() => {
            if (trigger === 'hover') {
              setIsOpen(false);
            }
          }}
        >
          {loading ? (
            <div className="p-4 text-center text-gray-500">
              <span className="inline-block animate-spin mr-2">⟳</span>
              Loading...
            </div>
          ) : page ? (
            <div className="flex flex-col h-full">
              {/* Header */}
              <div className="p-4 border-b bg-gray-50 sticky top-0">
                <div className="flex items-start justify-between gap-2 mb-2">
                  <h3 className="font-semibold text-gray-900 flex-1 text-sm leading-tight">
                    {page.title}
                  </h3>
                  <span
                    className={`px-2 py-1 rounded text-xs font-medium capitalize flex-shrink-0 ${
                      confidenceColor[page.confidence as keyof typeof confidenceColor]
                    }`}
                  >
                    {page.confidence}
                  </span>
                </div>
                <div className="flex gap-2 text-xs text-gray-600">
                  <span className="bg-gray-200 px-2 py-0.5 rounded capitalize">
                    {page.category}
                  </span>
                </div>
              </div>

              {/* Content */}
              <div className="p-4 flex-1">
                {/* Summary */}
                {page.summary && (
                  <p className="text-sm text-gray-700 leading-relaxed mb-3 line-clamp-3">
                    {page.summary}
                  </p>
                )}

                {/* Metadata Grid */}
                <div className="grid grid-cols-2 gap-3 text-xs mb-3">
                  <div className="bg-gray-50 p-2 rounded">
                    <div className="text-gray-500 font-medium">Updated</div>
                    <div className="text-gray-900">
                      {new Date(page.updated_at).toLocaleDateString()}
                    </div>
                  </div>
                  <div className="bg-gray-50 p-2 rounded">
                    <div className="text-gray-500 font-medium">References</div>
                    <div className="text-gray-900">
                      {page.pages_linking} linked
                    </div>
                  </div>
                </div>

                {/* Outbound Links Count */}
                {page.outbound_links_count > 0 && (
                  <div className="text-xs text-gray-600 mb-3">
                    → Links to {page.outbound_links_count} other page{page.outbound_links_count !== 1 ? 's' : ''}
                  </div>
                )}
              </div>

              {/* Footer */}
              <div className="p-3 border-t bg-gray-50">
                <Link href={`/wiki/${wikiType}/pages/${pageId}`} className="block w-full text-center px-3 py-2 bg-blue-600 text-white text-sm font-medium rounded hover:bg-blue-700 transition">
                    View Full Page →
                </Link>
              </div>
            </div>
          ) : (
            <div className="p-4 text-center text-red-600 text-sm">
              Failed to load preview
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default WikiPagePreview;
