/**
 * Wiki Components - Barrel export for all wiki UI components
 */

// Core Wiki Components
export { WikiDashboard } from './WikiDashboard';
export { WikiSearch } from './WikiSearch';
export { WikiIngest } from './WikiIngest';
export { WikiBrowse } from './WikiBrowse';
export { WikiPage } from './WikiPage';
export { WikiQuery } from './WikiQuery';
export { WikiLint } from './WikiLint';
export { WikiPagePreview } from './WikiPagePreview';

// Phase 2-5 Components (Relationships, Schema, Refresh, Synthesis)
export { WikiRelationships } from './WikiRelationships';
export { WikiSchemaAnalysis } from './WikiSchemaAnalysis';
export { WikiRefreshScheduler } from './WikiRefreshScheduler';
export { WikiSynthesis } from './WikiSynthesis';

// Integration Components
// The standalone /projects/[pid]/wiki route is the single wiki entry point.
// WikiTabInProjectStudio was removed — link to /projects/[pid]/wiki instead of
// embedding wiki UI in Project Studio.
export { WikiArtifactSection } from './WikiArtifactSection';
export { WikiMemoryLink } from './WikiMemoryLink';
export { CoordinatorWikiContext } from './CoordinatorWikiContext';
