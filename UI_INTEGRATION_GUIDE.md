# Wiki UI Integration Guide

Complete guide for integrating wiki components into your ProcessDoc v2 frontend application.

---

## Quick Start: Getting the UI Running

### Prerequisites
- React 18+ application with Next.js
- TailwindCSS configured
- Node.js 16+

### Step 1: Copy Components to Your Project

```bash
# Copy all wiki components to your frontend
cp -r frontend/components/wiki/ /path/to/your/project/components/

# Verify the files are there
ls /path/to/your/project/components/wiki/
```

Expected files:
```
components/wiki/
├── WikiDashboard.tsx
├── WikiSearch.tsx
├── WikiIngest.tsx
├── WikiBrowse.tsx
├── WikiPage.tsx
├── WikiQuery.tsx
├── WikiLint.tsx
├── WikiPagePreview.tsx
├── WikiTabInProjectStudio.tsx
├── WikiArtifactSection.tsx
├── WikiMemoryLink.tsx
├── CoordinatorWikiContext.tsx
├── index.ts
└── README.md
```

### Step 2: Import Components

```typescript
// In your application
import { 
  WikiDashboard, 
  WikiSearch, 
  WikiIngest,
  WikiBrowse,
  WikiPage,
  WikiQuery,
  WikiLint,
  WikiPagePreview
} from '@/components/wiki';
```

### Step 3: Add to Your Pages/Routes

#### Option A: Add Wiki Tab to Project Studio

```typescript
// pages/projects/[projectId]/studio.tsx
import { WikiTabInProjectStudio } from '@/components/wiki';

export default function ProjectStudio({ projectId, projectName }) {
  return (
    <div className="flex">
      {/* Existing tabs */}
      <Tabs>
        <Tab label="Settings">...</Tab>
        <Tab label="Team">...</Tab>
        
        {/* Add Wiki Tab */}
        <Tab label="Wiki">
          <WikiTabInProjectStudio 
            projectId={projectId} 
            projectName={projectName}
          />
        </Tab>
      </Tabs>
    </div>
  );
}
```

#### Option B: Create Dedicated Wiki Pages

```typescript
// pages/projects/[projectId]/wiki.tsx
import { WikiDashboard } from '@/components/wiki';

export default function WikiPage({ projectId }) {
  return (
    <div className="container mx-auto p-6">
      <WikiDashboard wikiType="project" projectId={projectId} />
    </div>
  );
}
```

```typescript
// pages/projects/[projectId]/wiki/search.tsx
import { WikiSearch } from '@/components/wiki';

export default function WikiSearchPage({ projectId }) {
  return (
    <div className="container mx-auto p-6">
      <WikiSearch wikiType="project" projectId={projectId} />
    </div>
  );
}
```

### Step 4: Add Leading Practices Wiki Pages

```typescript
// pages/leading-practices/wiki.tsx
import { WikiDashboard } from '@/components/wiki';

export default function LeadingPracticesWiki() {
  return (
    <div className="container mx-auto p-6">
      <WikiDashboard wikiType="leading_practice" />
    </div>
  );
}
```

---

## Integration Scenarios

### Scenario 1: Wiki as Project Studio Tab (Recommended)

**Location:** Add to existing Project Studio interface

```typescript
// components/ProjectStudio.tsx
import { WikiTabInProjectStudio } from '@/components/wiki';

export function ProjectStudio({ projectId, projectName }) {
  const [activeTab, setActiveTab] = useState('overview');

  return (
    <div className="flex h-full">
      {/* Sidebar Tabs */}
      <div className="w-32 border-r">
        <button 
          onClick={() => setActiveTab('overview')}
          className={activeTab === 'overview' ? 'bg-blue-100' : ''}
        >
          Project Overview
        </button>
        <button 
          onClick={() => setActiveTab('wiki')}
          className={activeTab === 'wiki' ? 'bg-blue-100' : ''}
        >
          📚 Wiki
        </button>
        <button 
          onClick={() => setActiveTab('settings')}
          className={activeTab === 'settings' ? 'bg-blue-100' : ''}
        >
          Settings
        </button>
      </div>

      {/* Content Area */}
      <div className="flex-1 overflow-auto">
        {activeTab === 'wiki' && (
          <WikiTabInProjectStudio 
            projectId={projectId}
            projectName={projectName}
          />
        )}
        {activeTab === 'overview' && <ProjectOverview />}
        {activeTab === 'settings' && <ProjectSettings />}
      </div>
    </div>
  );
}
```

### Scenario 2: Wiki in Run Studio (Artifacts Section)

**Location:** Add to Run detail page artifacts section

```typescript
// components/RunStudio/ArtifactsTab.tsx
import { WikiArtifactSection } from '@/components/wiki';

export function ArtifactsTab({ runId, projectId, runName }) {
  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Artifacts</h2>
      
      {/* Regular artifacts listing */}
      <ArtifactsList runId={runId} />
      
      {/* Wiki artifacts section */}
      <div className="border-t pt-6">
        <h3 className="text-xl font-semibold mb-4">Wiki Artifacts</h3>
        <WikiArtifactSection 
          runId={runId}
          projectId={projectId}
          runName={runName}
        />
      </div>
    </div>
  );
}
```

### Scenario 3: Wiki Links in Memory Items

**Location:** Add to Memory item detail view

```typescript
// components/Memory/MemoryDetail.tsx
import { WikiMemoryLink } from '@/components/wiki';

export function MemoryDetail({ memory, projectId }) {
  return (
    <div className="space-y-6">
      {/* Memory content */}
      <div>
        <h2 className="text-2xl font-bold">{memory.type}</h2>
        <p className="text-gray-700 mt-4">{memory.content}</p>
      </div>

      {/* Wiki integration */}
      <div className="border-t pt-6">
        <h3 className="font-semibold mb-4">Wiki Pages</h3>
        <WikiMemoryLink 
          memoryId={memory.id}
          memoryType={memory.type}
          memoryContent={memory.content}
          projectId={projectId}
        />
      </div>
    </div>
  );
}
```

### Scenario 4: Wiki Context in Coordinator

**Location:** Add to Run planning/coordination interface

```typescript
// components/Coordinator/RunPlanning.tsx
import { CoordinatorWikiContext } from '@/components/wiki';

export function RunPlanning({ projectId, runObjective, runType }) {
  return (
    <div className="grid grid-cols-2 gap-6">
      {/* Left: Run Planning Form */}
      <div>
        <h2 className="text-2xl font-bold mb-4">Plan Run</h2>
        <RunObjectiveInput 
          value={runObjective}
          onChange={setRunObjective}
        />
        {/* Other planning controls */}
      </div>

      {/* Right: Wiki Context */}
      <div className="bg-gray-50 p-6 rounded-lg">
        <h3 className="text-lg font-semibold mb-4">Wiki Context</h3>
        <CoordinatorWikiContext 
          projectId={projectId}
          runObjective={runObjective}
          runType={runType}
        />
      </div>
    </div>
  );
}
```

---

## Component Usage Examples

### Example 1: Standalone Wiki Dashboard

```typescript
import { WikiDashboard } from '@/components/wiki';

export default function WikiPage() {
  return (
    <div className="min-h-screen bg-white">
      <header className="bg-blue-600 text-white p-4">
        <h1 className="text-3xl font-bold">Project Wiki</h1>
      </header>
      <main className="p-6">
        <WikiDashboard wikiType="project" projectId="proj_123" />
      </main>
    </div>
  );
}
```

### Example 2: Wiki Search Page with Navigation

```typescript
import { WikiSearch } from '@/components/wiki';
import Link from 'next/link';

export default function SearchPage() {
  return (
    <div>
      <nav className="flex gap-4 p-4 border-b">
        <Link href="/wiki/dashboard">
          <a className="text-blue-600 hover:underline">Dashboard</a>
        </Link>
        <Link href="/wiki/search">
          <a className="font-bold text-blue-600">Search</a>
        </Link>
        <Link href="/wiki/browse">
          <a className="text-blue-600 hover:underline">Browse</a>
        </Link>
        <Link href="/wiki/ingest">
          <a className="text-blue-600 hover:underline">Ingest</a>
        </Link>
      </nav>
      <WikiSearch wikiType="project" projectId="proj_123" />
    </div>
  );
}
```

### Example 3: Full Wiki Application

```typescript
// pages/wiki/[[...slug]].tsx
import { useState } from 'react';
import {
  WikiDashboard,
  WikiSearch,
  WikiBrowse,
  WikiIngest,
  WikiQuery,
  WikiLint
} from '@/components/wiki';

type WikiView = 'dashboard' | 'search' | 'browse' | 'ingest' | 'query' | 'lint';

export default function WikiApp() {
  const [view, setView] = useState<WikiView>('dashboard');
  const projectId = 'proj_123'; // Get from URL or props

  const components = {
    dashboard: <WikiDashboard wikiType="project" projectId={projectId} />,
    search: <WikiSearch wikiType="project" projectId={projectId} />,
    browse: <WikiBrowse wikiType="project" projectId={projectId} />,
    ingest: <WikiIngest wikiType="project" projectId={projectId} />,
    query: <WikiQuery wikiType="project" projectId={projectId} />,
    lint: <WikiLint wikiType="project" projectId={projectId} />,
  };

  return (
    <div className="flex h-screen">
      {/* Navigation Sidebar */}
      <div className="w-48 bg-gray-100 border-r">
        <div className="p-4">
          <h1 className="text-xl font-bold mb-6">Wiki</h1>
          <nav className="space-y-2">
            {(['dashboard', 'search', 'browse', 'ingest', 'query', 'lint'] as WikiView[]).map(v => (
              <button
                key={v}
                onClick={() => setView(v)}
                className={`w-full text-left px-4 py-2 rounded capitalize ${
                  view === v ? 'bg-blue-500 text-white' : 'hover:bg-gray-200'
                }`}
              >
                {v === 'dashboard' && '📊'} 
                {v === 'search' && '🔍'}
                {v === 'browse' && '📖'}
                {v === 'ingest' && '⬆️'}
                {v === 'query' && '❓'}
                {v === 'lint' && '✓'}
                {' '}{v}
              </button>
            ))}
          </nav>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 overflow-auto p-6">
        {components[view]}
      </div>
    </div>
  );
}
```

---

## API Integration

The components automatically call the REST API endpoints. Make sure your backend is running:

```bash
# Start backend server
python -m uvicorn app.main:app --reload

# Expected endpoints to be available:
# POST   /api/wiki/{wiki_type}/ingest
# POST   /api/wiki/{wiki_type}/query
# POST   /api/wiki/{wiki_type}/lint
# GET    /api/wiki/{wiki_type}/pages
# GET    /api/wiki/{wiki_type}/search
# GET    /api/wiki/{wiki_type}/stats
# ... and 7 more endpoints
```

### Component API Calls

Each component makes specific API calls:

```typescript
// WikiDashboard calls:
GET /api/wiki/{wiki_type}/stats

// WikiSearch calls:
GET /api/wiki/{wiki_type}/search?q=query&category=...&confidence=...

// WikiIngest calls:
POST /api/wiki/{wiki_type}/ingest

// WikiBrowse calls:
GET /api/wiki/{wiki_type}/pages?sort=...&limit=...

// WikiQuery calls:
POST /api/wiki/{wiki_type}/query

// WikiLint calls:
POST /api/wiki/{wiki_type}/lint
```

---

## Development & Testing

### Run Local Development Server

```bash
# In your frontend directory
npm run dev

# Navigate to:
# http://localhost:3000/wiki
# http://localhost:3000/projects/[projectId]/wiki
# etc.
```

### Test Components in Isolation

```typescript
// __tests__/components/wiki/WikiDashboard.test.tsx
import { render, screen } from '@testing-library/react';
import { WikiDashboard } from '@/components/wiki';

describe('WikiDashboard', () => {
  it('renders dashboard title', () => {
    render(<WikiDashboard wikiType="project" projectId="test_proj" />);
    expect(screen.getByText(/Wiki/i)).toBeInTheDocument();
  });

  // Add more tests
});
```

### Mock API Responses for Testing

```typescript
// __mocks__/handlers.ts
import { rest } from 'msw';

export const handlers = [
  rest.get('/api/wiki/project/stats', (req, res, ctx) => {
    return res(ctx.json({
      status: 'success',
      data: {
        stats: {
          total_pages: 42,
          pages_this_week: 5,
          health: { severity: 'low', issues_count: 0 }
        }
      }
    }));
  }),

  rest.get('/api/wiki/project/search', (req, res, ctx) => {
    return res(ctx.json({
      status: 'success',
      data: {
        results: [
          { id: '1', title: 'Test Page', content: 'Test content' }
        ],
        facets: { category: { entity: 1 }, confidence: { high: 1 } }
      }
    }));
  }),
];
```

---

## Styling & Customization

All components use TailwindCSS. Customize by:

### Option 1: Modify TailwindCSS Configuration

```javascript
// tailwind.config.js
module.exports = {
  theme: {
    extend: {
      colors: {
        wiki: {
          primary: '#2563eb',
          success: '#10b981',
          warning: '#f59e0b',
        }
      }
    }
  }
}
```

### Option 2: Override Component Styles

```typescript
// Create wrapper component
export function CustomWikiDashboard(props) {
  return (
    <div className="custom-wiki-theme">
      <WikiDashboard {...props} />
    </div>
  );
}
```

```css
/* styles/custom-wiki.css */
.custom-wiki-theme h1 {
  @apply text-4xl font-bold text-wiki-primary;
}

.custom-wiki-theme .card {
  @apply bg-white shadow-lg rounded-lg;
}
```

### Option 3: Component Props for Customization

Some components accept optional props:

```typescript
<WikiPagePreview 
  pageId="page_123"
  wikiType="project"
  trigger="click"  // 'hover' | 'click' | 'none'
  className="custom-class"
>
  <span>Custom trigger text</span>
</WikiPagePreview>
```

---

## Debugging

### Enable Logging

```typescript
// Enable console logging in components
const DEBUG = process.env.NODE_ENV === 'development';

const log = (msg: string) => {
  if (DEBUG) console.log(`[Wiki] ${msg}`);
};
```

### Check Network Requests

```typescript
// Open browser DevTools (F12)
// Network tab → Filter by "wiki"
// Check request/response for API calls
```

### Component State Debugging

```typescript
// Add React DevTools
// https://react-devtools-tutorial.vercel.app/
// Inspect component props and state
```

---

## Deployment

### Build for Production

```bash
# Build Next.js application
npm run build

# Verify build
npm run start

# Or deploy to Vercel, Netlify, etc.
```

### Environment Variables

```bash
# .env.local
NEXT_PUBLIC_API_URL=http://localhost:8000

# In components:
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
```

---

## Common Issues & Solutions

### Issue 1: Components Not Rendering

**Problem:** Components show blank screen

**Solutions:**
1. Check backend API is running
2. Verify API_URL is correct
3. Check browser console for errors
4. Ensure projectId is provided

### Issue 2: Styling Not Applied

**Problem:** Components look unstyled

**Solutions:**
1. Verify TailwindCSS is installed: `npm install tailwindcss`
2. Check tailwind.config.js includes component paths
3. Verify styles are imported in _app.tsx: `import 'tailwindcss/tailwind.css'`
4. Clear Next.js cache: `rm -rf .next`

### Issue 3: API Errors

**Problem:** Components show error messages

**Solutions:**
1. Check backend server is running
2. Verify API endpoints are working: `curl http://localhost:8000/api/wiki/project/stats`
3. Check CORS configuration if API on different domain
4. Review browser console Network tab for failed requests

---

## Next Steps

1. **Copy components** to your project
2. **Add wiki routes** to your application
3. **Start backend API** server
4. **Test components** locally
5. **Customize styling** as needed
6. **Deploy** to production

---

**Components are ready to use! 🚀**

For detailed component API, see `frontend/components/wiki/README.md`
