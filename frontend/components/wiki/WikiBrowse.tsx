/**
 * WikiBrowse - Browse all wiki pages with filtering, sorting, and pagination
 *
 * Features:
 * - Paginated list of all wiki pages
 * - Filter by category and confidence
 * - Sort by title, date updated, or relevance
 * - Quick access to page details
 * - Statistics summary
 */

import React, { useState, useEffect } from 'react';
import Link from 'next/link';

interface BrowseItem {
  id: string;
  title: string;
  category: string;
  confidence: string;
  updated_at: string;
  summary?: string;
  pages_linking: number;
}

interface BrowseResponse {
  status: 'success' | 'error';
  pages: BrowseItem[];
  pagination: {
    total: number;
    limit: number;
    offset: number;
    has_more: boolean;
  };
  available_categories: string[];
  available_confidence: string[];
}

interface WikiBrowseProps {
  wikiType: 'leading_practice' | 'project';
  projectId?: string;
}

type SortBy = 'title' | 'updated_at' | 'relevance';

export const WikiBrowse: React.FC<WikiBrowseProps> = ({
  wikiType,
  projectId,
}) => {
  const [pages, setPages] = useState<BrowseItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filter and sort state
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [selectedConfidence, setSelectedConfidence] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<SortBy>('updated_at');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');

  // Pagination state
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(20);
  const [totalPages, setTotalPages] = useState(1);
  const [totalItems, setTotalItems] = useState(0);

  // Filter options
  const [availableCategories, setAvailableCategories] = useState<string[]>([]);
  const [availableConfidence, setAvailableConfidence] = useState<string[]>([]);

  useEffect(() => {
    const fetchPages = async () => {
      try {
        setLoading(true);
        setError(null);

        const params = new URLSearchParams({
          limit: itemsPerPage.toString(),
          offset: ((currentPage - 1) * itemsPerPage).toString(),
          sort: sortBy,
          sort_order: sortOrder,
        });

        if (projectId) params.append('project_id', projectId);
        if (selectedCategory) params.append('category', selectedCategory);
        if (selectedConfidence) params.append('confidence', selectedConfidence);

        const response = await fetch(
          `/api/wiki/${wikiType}/pages?${params.toString()}`,
          { method: 'GET' }
        );

        if (!response.ok) throw new Error('Failed to fetch pages');

        const data: BrowseResponse = await response.json();
        setPages(data?.pages ?? []);
        setAvailableCategories(data?.available_categories ?? []);
        setAvailableConfidence(data?.available_confidence ?? []);

        const total = data?.pagination?.total ?? 0;
        setTotalItems(total);
        setTotalPages(Math.ceil(total / itemsPerPage));
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    fetchPages();
  }, [wikiType, projectId, currentPage, itemsPerPage, selectedCategory, selectedConfidence, sortBy, sortOrder]);

  const confidenceColor = {
    high: 'bg-green-100 text-green-800',
    medium: 'bg-yellow-100 text-yellow-800',
    low: 'bg-red-100 text-red-800',
  };

  const handleCategoryChange = (category: string | null) => {
    setSelectedCategory(category);
    setCurrentPage(1);
  };

  const handleConfidenceChange = (confidence: string | null) => {
    setSelectedConfidence(confidence);
    setCurrentPage(1);
  };

  const handleSortChange = (newSort: SortBy) => {
    if (sortBy === newSort) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setSortBy(newSort);
      setSortOrder('desc');
    }
    setCurrentPage(1);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold mb-2">Browse Pages</h1>
        <p className="text-gray-600">
          Explore all {wikiType === 'leading_practice' ? 'leading practices' : 'project'} wiki pages
        </p>
      </div>

      {/* Summary Stats */}
      {!loading && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="bg-blue-50 p-4 rounded-lg border border-blue-200">
            <div className="text-sm text-blue-600 font-medium">Total Pages</div>
            <div className="text-2xl font-bold text-blue-900 mt-1">{totalItems}</div>
          </div>
          <div className="bg-purple-50 p-4 rounded-lg border border-purple-200">
            <div className="text-sm text-purple-600 font-medium">Categories</div>
            <div className="text-2xl font-bold text-purple-900 mt-1">{availableCategories.length}</div>
          </div>
          <div className="bg-indigo-50 p-4 rounded-lg border border-indigo-200">
            <div className="text-sm text-indigo-600 font-medium">Confidence Levels</div>
            <div className="text-2xl font-bold text-indigo-900 mt-1">{availableConfidence.length}</div>
          </div>
        </div>
      )}

      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded text-red-600">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Filters Sidebar */}
        <div className="lg:col-span-1 space-y-4">
          {/* Category Filter */}
          {availableCategories.length > 0 && (
            <div className="bg-white p-4 rounded-lg border">
              <h3 className="font-semibold mb-3 text-sm uppercase text-gray-700">Category</h3>
              <div className="space-y-2">
                <button
                  onClick={() => handleCategoryChange(null)}
                  className={`block w-full text-left px-2 py-1 rounded text-sm ${
                    !selectedCategory ? 'bg-blue-100 text-blue-700 font-medium' : 'hover:bg-gray-50'
                  }`}
                >
                  All
                </button>
                {availableCategories.map((cat) => (
                  <button
                    key={cat}
                    onClick={() => handleCategoryChange(cat)}
                    className={`block w-full text-left px-2 py-1 rounded text-sm capitalize ${
                      selectedCategory === cat
                        ? 'bg-blue-100 text-blue-700 font-medium'
                        : 'hover:bg-gray-50'
                    }`}
                  >
                    {cat}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Confidence Filter */}
          {availableConfidence.length > 0 && (
            <div className="bg-white p-4 rounded-lg border">
              <h3 className="font-semibold mb-3 text-sm uppercase text-gray-700">Confidence</h3>
              <div className="space-y-2">
                <button
                  onClick={() => handleConfidenceChange(null)}
                  className={`block w-full text-left px-2 py-1 rounded text-sm ${
                    !selectedConfidence ? 'bg-blue-100 text-blue-700 font-medium' : 'hover:bg-gray-50'
                  }`}
                >
                  All
                </button>
                {availableConfidence.map((conf) => (
                  <button
                    key={conf}
                    onClick={() => handleConfidenceChange(conf)}
                    className={`block w-full text-left px-2 py-1 rounded text-sm capitalize ${
                      selectedConfidence === conf
                        ? 'bg-blue-100 text-blue-700 font-medium'
                        : 'hover:bg-gray-50'
                    }`}
                  >
                    {conf}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Sort Options */}
          <div className="bg-white p-4 rounded-lg border">
            <h3 className="font-semibold mb-3 text-sm uppercase text-gray-700">Sort By</h3>
            <div className="space-y-2">
              {(['title', 'updated_at', 'relevance'] as SortBy[]).map((option) => (
                <button
                  key={option}
                  onClick={() => handleSortChange(option)}
                  className={`block w-full text-left px-2 py-1 rounded text-sm capitalize ${
                    sortBy === option
                      ? 'bg-blue-100 text-blue-700 font-medium'
                      : 'hover:bg-gray-50'
                  }`}
                >
                  {option === 'updated_at' ? 'Recently Updated' : option}
                  {sortBy === option && (
                    <span className="ml-2 text-xs">
                      {sortOrder === 'asc' ? '↑' : '↓'}
                    </span>
                  )}
                </button>
              ))}
            </div>
          </div>

          {/* Items Per Page */}
          <div className="bg-white p-4 rounded-lg border">
            <h3 className="font-semibold mb-3 text-sm uppercase text-gray-700">Per Page</h3>
            <select
              value={itemsPerPage}
              onChange={(e) => {
                setItemsPerPage(Number(e.target.value));
                setCurrentPage(1);
              }}
              className="w-full px-2 py-1 border rounded text-sm"
            >
              <option value={10}>10</option>
              <option value={20}>20</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
          </div>
        </div>

        {/* Pages List */}
        <div className="lg:col-span-3">
          {loading && <div className="text-center py-12 text-gray-500">Loading pages...</div>}

          {!loading && pages.length === 0 && (
            <div className="text-center py-12 text-gray-500">
              <p className="mb-2">No pages found</p>
              <p className="text-sm">Try adjusting your filters</p>
            </div>
          )}

          {!loading && pages.length > 0 && (
            <>
              <div className="space-y-4">
                {pages.map((page) => (
                  <Link key={page.id} href={`/wiki/${wikiType}/pages/${page.id}`} className="block p-4 bg-white border rounded-lg hover:shadow-md transition">
                      <div className="flex items-start justify-between mb-2">
                        <h3 className="text-lg font-semibold text-blue-600 hover:underline flex-1">
                          {page.title}
                        </h3>
                        <span
                          className={`px-2 py-1 rounded text-xs font-medium capitalize ml-4 flex-shrink-0 ${
                            confidenceColor[page.confidence as keyof typeof confidenceColor] ||
                            confidenceColor.medium
                          }`}
                        >
                          {page.confidence}
                        </span>
                      </div>
                      <div className="flex gap-2 flex-wrap mb-2">
                        <span className="text-xs bg-gray-100 px-2 py-1 rounded capitalize">
                          {page.category}
                        </span>
                        <span className="text-xs text-gray-500">
                          Updated {new Date(page.updated_at).toLocaleDateString()}
                        </span>
                        {page.pages_linking > 0 && (
                          <span className="text-xs text-gray-500">
                            {page.pages_linking} reference{page.pages_linking !== 1 ? 's' : ''}
                          </span>
                        )}
                      </div>
                      {page.summary && (
                        <p className="text-sm text-gray-600 line-clamp-2">
                          {page.summary}
                        </p>
                      )}
                  </Link>
                ))}
              </div>

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="mt-6 flex items-center justify-between">
                  <div className="text-sm text-gray-600">
                    Showing {((currentPage - 1) * itemsPerPage) + 1} to{' '}
                    {Math.min(currentPage * itemsPerPage, totalItems)} of {totalItems}
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
                      disabled={currentPage === 1}
                      className="px-4 py-2 border rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      ← Previous
                    </button>
                    <div className="flex items-center gap-1">
                      {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                        let pageNum = currentPage - 2 + i;
                        if (pageNum < 1 || pageNum > totalPages) return null;
                        return (
                          <button
                            key={pageNum}
                            onClick={() => setCurrentPage(pageNum)}
                            className={`px-3 py-2 rounded-lg ${
                              currentPage === pageNum
                                ? 'bg-blue-600 text-white'
                                : 'border hover:bg-gray-50'
                            }`}
                          >
                            {pageNum}
                          </button>
                        );
                      })}
                    </div>
                    <button
                      onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
                      disabled={currentPage === totalPages}
                      className="px-4 py-2 border rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      Next →
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default WikiBrowse;
