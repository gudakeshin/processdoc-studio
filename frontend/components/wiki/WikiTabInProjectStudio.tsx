/**
 * WikiTabInProjectStudio - Wiki tab integration in Project Studio
 *
 * Embeds wiki interface as a tab within the project studio
 * Provides quick access to project wiki operations
 */

import React, { useState } from 'react';
import { WikiDashboard } from './WikiDashboard';
import { WikiSearch } from './WikiSearch';
import { WikiIngest } from './WikiIngest';
import { WikiBrowse } from './WikiBrowse';

type WikiTabType = 'dashboard' | 'search' | 'ingest' | 'browse';

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
      {/* Tab Navigation */}
      <div className="border-b bg-gray-50 px-6 py-4">
        <div className="flex gap-2 mb-4">
          <button
            onClick={() => setActiveTab('dashboard')}
            className={`px-4 py-2 rounded-lg font-medium transition ${
              activeTab === 'dashboard'
                ? 'bg-blue-600 text-white'
                : 'text-gray-700 hover:bg-gray-100'
            }`}
          >
            📊 Dashboard
          </button>
          <button
            onClick={() => setActiveTab('search')}
            className={`px-4 py-2 rounded-lg font-medium transition ${
              activeTab === 'search'
                ? 'bg-blue-600 text-white'
                : 'text-gray-700 hover:bg-gray-100'
            }`}
          >
            🔍 Search
          </button>
          <button
            onClick={() => setActiveTab('browse')}
            className={`px-4 py-2 rounded-lg font-medium transition ${
              activeTab === 'browse'
                ? 'bg-blue-600 text-white'
                : 'text-gray-700 hover:bg-gray-100'
            }`}
          >
            📖 Browse
          </button>
          <button
            onClick={() => setActiveTab('ingest')}
            className={`px-4 py-2 rounded-lg font-medium transition ${
              activeTab === 'ingest'
                ? 'bg-blue-600 text-white'
                : 'text-gray-700 hover:bg-gray-100'
            }`}
          >
            ⬆️ Ingest
          </button>
        </div>

        <p className="text-sm text-gray-600">
          Project Wiki for: <span className="font-semibold">{projectName}</span>
        </p>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {activeTab === 'dashboard' && (
          <WikiDashboard wikiType="project" projectId={projectId} />
        )}

        {activeTab === 'search' && (
          <WikiSearch wikiType="project" projectId={projectId} />
        )}

        {activeTab === 'browse' && (
          <WikiBrowse wikiType="project" projectId={projectId} />
        )}

        {activeTab === 'ingest' && (
          <WikiIngest wikiType="project" projectId={projectId} />
        )}
      </div>
    </div>
  );
};

export default WikiTabInProjectStudio;
