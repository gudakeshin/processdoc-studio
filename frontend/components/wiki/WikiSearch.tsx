/**
 * WikiSearch - Full-text search interface for wiki pages
 *
 * Features:
 * - Search input with autocomplete
 * - Filter by category and confidence
 * - Display results with snippet preview
 * - Faceted search navigation
 */

import React, { useState, useEffect } from 'react';
import Link from 'next/link';

interface SearchResult {
  id: string;
  title: string;
  category: string;
  confidence: string;
  content: string;
  updated_at: string;
}

interface SearchFacets {
  category: { [key: string]: number };
  confidence: { [key: string]: number };
}

interface WikiSearchProps {
  wikiType: 'leading_practice' | 'project';
  projectId?: string;
}

export const WikiSearch: React.FC<WikiSearchProps> = ({
  wikiType,
  projectId,
}) => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [facets, setFacets] = useState<SearchFacets>({ category: {}, confidence: {} });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [selectedConfidence, setSelectedConfidence] = useState<string | null>(null);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    setLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams({
        q: query,
        limit: '20',
      });

      if (projectId) params.append('project_id', projectId);
      if (selectedCategory) params.append('category', selectedCategory);
      if (selectedConfidence) params.append('confidence', selectedConfidence);

      const response = await fetch(
        `/api/wiki/${wikiType}/search?${params.toString()}`,
        { method: 'GET' }
      );

      if (!response.ok) throw new Error('Search failed');

      const data = await response.json();
      setResults(data.results || []);
      setFacets(data.facets || { category: {}, confidence: {} });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  const confidenceColor = {
    high: 'bg-green-100 text-green-800',
    medium: 'bg-yellow-100 text-yellow-800',
    low: 'bg-red-100 text-red-800',
  };

  return (
    <div className="space-y-6">
      {/* Search Header */}
      <div>
        <h1 className="text-3xl font-bold mb-2">Search Wiki</h1>
        <p className="text-gray-600">
          Find pages, concepts, and learnings across the wiki
        </p>
      </div>

      {/* Search Form */}
      <form onSubmit={handleSearch} className="flex gap-2 mb-4">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search for practices, decisions, learnings..."
          className="flex-1 px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button
          type="submit"
          disabled={loading}
          className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? 'Searching...' : 'Search'}
        </button>
      </form>

      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded text-red-600">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        {/* Facets Sidebar */}
        <div className="md:col-span-1">
          {/* Category Filter */}
          {Object.keys(facets.category).length > 0 && (
            <div className="bg-white p-4 rounded-lg border mb-4">
              <h3 className="font-semibold mb-3">Category</h3>
              <div className="space-y-2">
                <button
                  onClick={() => setSelectedCategory(null)}
                  className={`block w-full text-left px-2 py-1 rounded ${
                    !selectedCategory ? 'bg-blue-100 text-blue-700' : 'hover:bg-gray-50'
                  }`}
                >
                  All
                </button>
                {Object.entries(facets.category).map(([cat, count]) => (
                  <button
                    key={cat}
                    onClick={() => setSelectedCategory(cat)}
                    className={`block w-full text-left px-2 py-1 rounded capitalize ${
                      selectedCategory === cat
                        ? 'bg-blue-100 text-blue-700'
                        : 'hover:bg-gray-50'
                    }`}
                  >
                    {cat} <span className="text-gray-500 text-sm">({count})</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Confidence Filter */}
          {Object.keys(facets.confidence).length > 0 && (
            <div className="bg-white p-4 rounded-lg border">
              <h3 className="font-semibold mb-3">Confidence</h3>
              <div className="space-y-2">
                <button
                  onClick={() => setSelectedConfidence(null)}
                  className={`block w-full text-left px-2 py-1 rounded ${
                    !selectedConfidence ? 'bg-blue-100 text-blue-700' : 'hover:bg-gray-50'
                  }`}
                >
                  All
                </button>
                {Object.entries(facets.confidence).map(([conf, count]) => (
                  <button
                    key={conf}
                    onClick={() => setSelectedConfidence(conf)}
                    className={`block w-full text-left px-2 py-1 rounded capitalize ${
                      selectedConfidence === conf
                        ? 'bg-blue-100 text-blue-700'
                        : 'hover:bg-gray-50'
                    }`}
                  >
                    {conf} <span className="text-gray-500 text-sm">({count})</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Results */}
        <div className="md:col-span-3">
          {loading && <div className="text-center py-8">Searching...</div>}

          {!loading && results.length === 0 && query && (
            <div className="text-center py-8 text-gray-600">
              No results found for "{query}"
            </div>
          )}

          {!loading && results.length > 0 && (
            <div>
              <div className="mb-4 text-sm text-gray-600">
                Found {results.length} result{results.length !== 1 ? 's' : ''}
              </div>
              <div className="space-y-4">
                {results.map((result) => (
                  <Link key={result.id} href={`/wiki/${wikiType}/pages/${result.id}`}>
                    <a className="block p-4 border rounded-lg hover:shadow-md transition">
                      <div className="flex items-start justify-between mb-2">
                        <h3 className="text-lg font-semibold text-blue-600 hover:underline">
                          {result.title}
                        </h3>
                        <span
                          className={`px-2 py-1 rounded text-xs font-medium capitalize ${
                            confidenceColor[result.confidence as keyof typeof confidenceColor] ||
                            confidenceColor.medium
                          }`}
                        >
                          {result.confidence}
                        </span>
                      </div>
                      <div className="flex gap-2 mb-2">
                        <span className="text-xs bg-gray-100 px-2 py-1 rounded capitalize">
                          {result.category}
                        </span>
                        <span className="text-xs text-gray-500">
                          Updated {new Date(result.updated_at).toLocaleDateString()}
                        </span>
                      </div>
                      <p className="text-gray-700 line-clamp-2">
                        {result.content.substring(0, 200)}...
                      </p>
                    </a>
                  </Link>
                ))}
              </div>
            </div>
          )}

          {!loading && !query && (
            <div className="text-center py-12 text-gray-500">
              <p className="mb-4">Enter a search query to find pages</p>
              <p className="text-sm">Try searching for topics, concepts, or decision keywords</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default WikiSearch;
