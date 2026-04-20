/**
 * WikiTabNav — shared tab bar used across all wiki components.
 * Replaces 7 identical inline tab implementations.
 */

import React from 'react';

interface Tab {
  key: string;
  label: string;
  count?: number;
}

interface WikiTabNavProps {
  tabs: Tab[];
  activeTab: string;
  onChange: (key: string) => void;
}

export const WikiTabNav: React.FC<WikiTabNavProps> = ({ tabs, activeTab, onChange }) => (
  <div className="flex border-b border-[var(--surface-border)]">
    {tabs.map((tab) => (
      <button
        key={tab.key}
        onClick={() => onChange(tab.key)}
        className={`px-3 py-2 text-xs font-medium transition border-b-2 -mb-px ${
          activeTab === tab.key
            ? 'border-[var(--accent-blue)] text-[var(--accent-blue)]'
            : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text-default)]'
        }`}
      >
        {tab.label}
        {tab.count !== undefined && (
          <span className="ml-1.5 text-[10px] opacity-70">({tab.count})</span>
        )}
      </button>
    ))}
  </div>
);

export default WikiTabNav;
