/**
 * WikiTabInProjectStudio - Wiki tab integration in Project Studio
 *
 * Embeds wiki interface as a tab within the project studio.
 * Uses the shared WikiTabNav for consistent tab styling.
 */

import dynamic from 'next/dynamic';
import React, { useState } from 'react';
import { WikiTabNav } from './WikiTabNav';

// Lazy-load tab panels — only the active one ships with the initial chunk.
const WikiDashboard = dynamic(() => import('./WikiDashboard').then(m => ({ default: m.WikiDashboard })), {
  loading: () => <div className="p-4 text-sm text-gray-400">Loading…</div>,
});
const WikiSearch = dynamic(() => import('./WikiSearch').then(m => ({ default: m.WikiSearch })), {
  loading: () => <div className="p-4 text-sm text-gray-400">Loading…</div>,
});
const WikiBrowse = dynamic(() => import('./WikiBrowse').then(m => ({ default: m.WikiBrowse })), {
  loading: () => <div className="p-4 text-sm text-gray-400">Loading…</div>,
});
const WikiIngest = dynamic(() => import('./WikiIngest').then(m => ({ default: m.WikiIngest })), {
  loading: () => <div className="p-4 text-sm text-gray-400">Loading…</div>,
});

type WikiTabType = 'dashboard' | 'search' | 'browse' | 'ingest';

const TABS = [
  { key: 'dashboard', label: 'Dashboard' },
  { key: 'search',    label: 'Search' },
  { key: 'browse',    label: 'Browse' },
  { key: 'ingest',    label: 'Ingest' },
];

interface WikiTabInProjectStudioProps {
  projectId: string;
  projectName: string;
}

export const WikiTabInProjectStudio: React.FC<WikiTabInProjectStudioProps> = ({
  projectId,
  projectName,
}) => {
  const [activeTab, setActiveTab] = useState<WikiTabType>('dashboard');

  return (
    <div className="h-full flex flex-col bg-white">
      <div className="border-b bg-gray-50 px-6 pt-4 pb-0">
        <p className="text-sm text-gray-600 mb-3">
          Project Wiki for: <span className="font-semibold">{projectName}</span>
        </p>
        <WikiTabNav
          tabs={TABS}
          activeTab={activeTab}
          onChange={(key) => setActiveTab(key as WikiTabType)}
        />
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {activeTab === 'dashboard' && <WikiDashboard wikiType="project" projectId={projectId} />}
        {activeTab === 'search'    && <WikiSearch    wikiType="project" projectId={projectId} />}
        {activeTab === 'browse'    && <WikiBrowse    wikiType="project" projectId={projectId} />}
        {activeTab === 'ingest'    && <WikiIngest    wikiType="project" projectId={projectId} />}
      </div>
    </div>
  );
};

export default WikiTabInProjectStudio;
