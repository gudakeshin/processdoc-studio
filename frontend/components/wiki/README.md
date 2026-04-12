# Wiki Components Documentation

Complete React/TypeScript component library for the two-level wiki system in ProcessDoc v2.

## Overview

The wiki component library provides a comprehensive UI for managing knowledge at two levels:
- **Leading Practice Wiki** (global, shared across all projects)
- **Project Wiki** (scoped to individual projects)

All components integrate with the REST API backend and support Cowork alignment tiers (retry, auto-correction, QA/linting).

## Core Components

### WikiDashboard
Main overview component displaying wiki statistics and health summary.

**Props:**
```typescript
interface WikiDashboardProps {
  wikiType: 'leading_practice' | 'project';
  projectId?: string;  // Required for 'project' type
}
```

**Features:**
- Total pages, pages this week, health status
- Category breakdown with clickable filters
- Confidence distribution visualization
- Health alerts with severity color coding
- Quick action buttons (Search, Browse, Ingest, Lint)

**Usage:**
```tsx
<WikiDashboard wikiType="project" projectId="proj_123" />
```

### WikiSearch
Full-text search interface with faceted filtering and results preview.

**Props:**
```typescript
interface WikiSearchProps {
  wikiType: 'leading_practice' | 'project';
  projectId?: string;
}
```

**Features:**
- Search input with autocomplete support
- Category and confidence filters
- Results with snippet preview (200 chars)
- Facet counts and statistics
- Clickable results linking to page details

**Usage:**
```tsx
<WikiSearch wikiType="leading_practice" />
```

### WikiIngest
Source ingestion form for adding new wiki content.

**Props:**
```typescript
interface WikiIngestProps {
  wikiType: 'leading_practice' | 'project';
  projectId?: string;
}
```

**Features:**
- 4 source types: URL, Document, Run Artifact, Conversation
- Dynamic form fields based on source type
- Progress tracking during ingest
- Results display with corrections and QA summary
- Success/error feedback with detailed messaging

**Source Types:**
- **URL:** Ingest content from web articles/documents
- **Document:** Upload PDF, Word, Excel files
- **Run Artifact:** Capture learnings from completed runs
- **Conversation:** Digest conversation transcripts

**Usage:**
```tsx
<WikiIngest wikiType="project" projectId="proj_123" />
```

### WikiBrowse
Paginated list of all wiki pages with filtering, sorting, and pagination.

**Props:**
```typescript
interface WikiBrowseProps {
  wikiType: 'leading_practice' | 'project';
  projectId?: string;
}
```

**Features:**
- Full page listing with pagination
- Filter by category and confidence
- Sort by title, date updated, or relevance
- Configurable items per page (10, 20, 50, 100)
- Summary statistics

**Usage:**
```tsx
<WikiBrowse wikiType="project" projectId="proj_123" />
```

### WikiPage
Single page display with full content, metadata, and related pages.

**Props:**
```typescript
interface WikiPageProps {
  wikiType: 'leading_practice' | 'project';
  pageId: string;
  projectId?: string;
}
```

**Features:**
- Full page content with markdown rendering
- Metadata display (category, confidence, dates)
- Inbound and outbound links
- Frontmatter inspection
- Source traceability (memory items, run IDs)
- Action buttons (Edit, Promote, More)

**Tabs:**
1. **Content** - Full page markdown rendering
2. **Links** - Inbound/outbound cross-references
3. **Metadata** - Frontmatter and source information

**Usage:**
```tsx
<WikiPage wikiType="project" pageId="page_123" projectId="proj_123" />
```

### WikiQuery
Question answering interface with synthesis and optional QA evaluation.

**Props:**
```typescript
interface WikiQueryProps {
  wikiType: 'leading_practice' | 'project';
  projectId?: string;
  initialQuestion?: string;
}
```

**Features:**
- Question textarea input
- Answer synthesis with citations
- Optional quality evaluation (QA score, issues, suggestions)
- Source page references
- Related questions suggestions
- Query history (recent 5)
- Save/Share/Edit actions

**Quality Evaluation:**
When enabled, includes:
- Quality score (0-100%)
- Potential issues (e.g., incomplete coverage)
- Actionable suggestions

**Usage:**
```tsx
<WikiQuery wikiType="project" projectId="proj_123" />
```

### WikiLint
Health check and issue resolution interface.

**Props:**
```typescript
interface WikiLintProps {
  wikiType: 'leading_practice' | 'project';
  projectId?: string;
  autoRun?: boolean;  // Auto-run check on mount
}
```

**Features:**
- One-click health check execution
- Auto-fix capability for low-risk issues
- Issue breakdown by type and severity
- 7 issue types (contradictions, orphans, broken links, etc.)
- Detailed suggestions with affected pages
- Historical trend view

**Issue Types:**
1. **Contradiction** - Conflicting claims
2. **Orphan Page** - No incoming links
3. **Broken Link** - References to non-existent pages
4. **Missing Reference** - Concepts without dedicated pages
5. **Coverage Gap** - Under-explored important topics
6. **Divergence** - Project wiki differs from LP practices
7. **Staleness** - Pages not updated despite newer sources

**Usage:**
```tsx
<WikiLint wikiType="project" projectId="proj_123" autoRun={true} />
```

### WikiPagePreview
Inline preview popup for wiki pages with hover/click triggers.

**Props:**
```typescript
interface WikiPagePreviewProps {
  pageId: string;
  wikiType: 'leading_practice' | 'project';
  projectId?: string;
  trigger?: 'hover' | 'click' | 'none';  // Default: 'hover'
  children?: React.ReactNode;
  className?: string;
}
```

**Features:**
- Quick preview on hover/click
- Shows page summary and metadata
- Link to full page
- Responsive positioning (avoids off-screen)
- Loading state
- Error handling

**Usage:**
```tsx
<WikiPagePreview 
  pageId="page_123" 
  wikiType="project" 
  projectId="proj_123"
  trigger="hover"
>
  <a>View detailed article</a>
</WikiPagePreview>
```

## Integration Components

### WikiTabInProjectStudio
Embeds wiki interface as a tab within the Project Studio.

**Props:**
```typescript
interface WikiTabInProjectStudioProps {
  projectId: string;
  projectName: string;
}
```

**Features:**
- 4 tabs: Dashboard, Search, Browse, Ingest
- Quick access to project wiki operations
- Full viewport integration
- Persistent tab state

**Usage:**
```tsx
<WikiTabInProjectStudio projectId="proj_123" projectName="Financial Transformation" />
```

**Integration Point:** Add as a tab in the Project Studio sidebar alongside Settings, Team, etc.

### WikiArtifactSection
Displays run artifacts and wiki pages created from runs.

**Props:**
```typescript
interface WikiArtifactSectionProps {
  runId: string;
  projectId: string;
  runName?: string;
}
```

**Features:**
- Lists artifacts from a specific run
- Shows which artifacts were ingested to wiki
- Quick action buttons (Ingest More, Browse All)
- Links to artifact pages

**Usage:**
```tsx
<WikiArtifactSection runId="run_456" projectId="proj_123" runName="Financial Model v2" />
```

**Integration Point:** Add to the Run Studio artifacts section.

### WikiMemoryLink
Links memory items to wiki pages with creation capability.

**Props:**
```typescript
interface WikiMemoryLinkProps {
  memoryId: string;
  memoryType: 'fact' | 'decision' | 'constraint';
  memoryContent: string;
  projectId: string;
}
```

**Features:**
- Shows wiki pages created from memory item
- Create new wiki page from memory
- Modal dialog for page creation
- Category and title selection
- Source content preview

**Usage:**
```tsx
<WikiMemoryLink 
  memoryId="mem_789" 
  memoryType="decision"
  memoryContent="We chose Oracle over SAP due to existing integrations"
  projectId="proj_123"
/>
```

**Integration Point:** Add to the Memory item detail view in the memory system.

### CoordinatorWikiContext
Displays relevant wiki pages during run planning in the Coordinator.

**Props:**
```typescript
interface CoordinatorWikiContextProps {
  projectId: string;
  runObjective: string;
  runType?: string;
}
```

**Features:**
- Auto-fetches relevant pages based on run objective
- Groups context by type (Learnings, Practices, Templates)
- Shows relevance score for each page
- Expandable snippets
- Add to plan buttons
- Real-time updates as objective changes

**Context Types:**
- **Learning** - Insights from similar past runs
- **Practice** - Best practices from LP wiki
- **Template** - Reusable structures

**Usage:**
```tsx
<CoordinatorWikiContext 
  projectId="proj_123"
  runObjective="Build financial model for acquisition scenario"
  runType="financial_modeling"
/>
```

**Integration Point:** Add to the Coordinator planning interface above or beside the run objective input.

## Styling

All components use **TailwindCSS** for responsive design with:
- Mobile-first responsive layout
- Color coding for severity and status
- Consistent spacing and typography
- Hover states and transitions
- Loading and error states

## Type Safety

All components are fully typed with TypeScript interfaces:
- Props validation
- API response types
- State management types
- Event handler signatures

## API Integration

Components communicate with the backend via REST API:

**Base Endpoints:**
```
GET    /api/wiki/{wiki_type}/stats
GET    /api/wiki/{wiki_type}/search?q=...
POST   /api/wiki/{wiki_type}/ingest
GET    /api/wiki/{wiki_type}/pages
GET    /api/wiki/{wiki_type}/pages/{pageId}
POST   /api/wiki/{wiki_type}/query
POST   /api/wiki/{wiki_type}/lint
GET    /api/wiki/{wiki_type}/context
```

All API calls include:
- Error handling with user-friendly messages
- Loading state management
- Automatic retry on transient failures
- Optional project_id parameter for project-scoped operations

## Accessibility

Components follow accessibility best practices:
- Semantic HTML structure
- ARIA labels where appropriate
- Keyboard navigation support
- Focus management
- Color contrast compliance

## Performance

Optimizations included:
- Lazy loading of page content
- Pagination for large lists
- Memoization of expensive computations
- Request debouncing for search
- Preview lazy-loading on demand

## Error Handling

All components include:
- Graceful error messages
- Fallback UI states
- Error logging for debugging
- User guidance on resolution

## Examples

### Full Wiki Dashboard in Project
```tsx
import { WikiTabInProjectStudio } from '@/components/wiki';

export default function ProjectWikiTab({ projectId, projectName }) {
  return <WikiTabInProjectStudio projectId={projectId} projectName={projectName} />;
}
```

### Memory to Wiki Flow
```tsx
import { WikiMemoryLink } from '@/components/wiki';

export default function MemoryDetail({ memory }) {
  return (
    <div>
      <h3>{memory.content}</h3>
      <WikiMemoryLink 
        memoryId={memory.id}
        memoryType={memory.type}
        memoryContent={memory.content}
        projectId={memory.projectId}
      />
    </div>
  );
}
```

### Coordinator with Wiki Context
```tsx
import { CoordinatorWikiContext } from '@/components/wiki';

export default function CoordinatorPlanning({ projectId, runObjective }) {
  return (
    <div>
      <textarea value={runObjective} placeholder="What is the run objective?" />
      <CoordinatorWikiContext 
        projectId={projectId}
        runObjective={runObjective}
      />
    </div>
  );
}
```

## Testing

Each component includes patterns for:
- Unit testing with React Testing Library
- Snapshot testing with Jest
- API mocking with MSW (Mock Service Worker)
- User interaction testing
- Loading and error state testing

## Future Enhancements

Planned improvements:
- Export functionality (PDF, Markdown, HTML)
- Advanced filtering and saved searches
- Wiki page versioning and history
- Collaboration comments and mentions
- Real-time synchronization
- Analytics on wiki usage patterns
- AI-powered page suggestions
