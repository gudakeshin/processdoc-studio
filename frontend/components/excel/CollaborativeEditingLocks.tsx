"use client";

import { useState, useEffect, useMemo } from "react";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";

type LockStatus = "locked" | "unlocked" | "conflicted";

type CellLock = {
  cellRef: string;
  lockedBy: string;
  lockedAt: string;
  version: number;
  status: LockStatus;
  expiresAt?: string;
};

type UserPresence = {
  userId: string;
  userName: string;
  lastSeen: string;
  currentCell?: string;
  isActive: boolean;
};

type ConflictMarker = {
  cellRef: string;
  conflictingUser: string;
  yourVersion: number;
  theirVersion: number;
  timestamp: string;
};

export function CollaborativeEditingLocks({
  locks = [],
  presence = [],
  conflicts = [],
  onRetry,
  onForceRelease,
}: {
  locks?: CellLock[];
  presence?: UserPresence[];
  conflicts?: ConflictMarker[];
  onRetry?: (cellRef: string) => void;
  onForceRelease?: (cellRef: string, userId: string) => void;
}) {
  const [activeTab, setActiveTab] = useState<"locks" | "presence" | "conflicts">(
    "locks"
  );
  const [expandedCell, setExpandedCell] = useState<string>("");

  // Calculate lock status
  const lockStats = useMemo(() => {
    return {
      total: locks.length,
      active: locks.filter((l) => l.status === "locked").length,
      conflicts: conflicts.length,
    };
  }, [locks, conflicts]);

  // Filter active users
  const activeUsers = useMemo(() => {
    return presence.filter((u) => u.isActive);
  }, [presence]);

  // Check if cell is editable
  const isCellLocked = (cellRef: string, currentUserId: string) => {
    const lock = locks.find((l) => l.cellRef === cellRef);
    return lock && lock.lockedBy !== currentUserId && lock.status === "locked";
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-2xl font-bold text-[#0F0B0B]">
          Collaborative Editing
        </h2>
        <p className="mt-1 text-sm text-[#4C4C4C]">
          Real-time collaboration status and optimistic locking
        </p>
      </div>

      {/* Status Cards */}
      <div className="grid gap-3 sm:grid-cols-3">
        <Card className="bg-white">
          <div className="p-4">
            <p className="text-xs text-[#4C4C4C]">Active Locks</p>
            <p className="mt-2 text-2xl font-bold text-[#0F0B0B]">
              {lockStats.active}
            </p>
            <p className="mt-1 text-xs text-[#4C4C4C]">
              of {lockStats.total} total
            </p>
          </div>
        </Card>

        <Card className="bg-white border-l-4 border-[#86BC24]">
          <div className="p-4">
            <p className="text-xs text-[#4C4C4C]">Active Users</p>
            <p className="mt-2 text-2xl font-bold text-[#86BC24]">
              {activeUsers.length}
            </p>
            <p className="mt-1 text-xs text-[#4C4C4C]">
              {activeUsers.map((u) => u.userName).join(", ")}
            </p>
          </div>
        </Card>

        <Card className={`bg-white ${lockStats.conflicts > 0 ? "border-l-4 border-orange-500" : ""}`}>
          <div className="p-4">
            <p className="text-xs text-[#4C4C4C]">Conflicts</p>
            <p className={`mt-2 text-2xl font-bold ${lockStats.conflicts > 0 ? "text-orange-600" : "text-[#86BC24]"}`}>
              {lockStats.conflicts}
            </p>
            <p className="mt-1 text-xs text-[#4C4C4C]">
              {lockStats.conflicts > 0 ? "Needs resolution" : "All clear"}
            </p>
          </div>
        </Card>
      </div>

      {/* Tab Navigation */}
      <div className="flex gap-2 border-b border-[#f0f0f0]">
        {(["locks", "presence", "conflicts"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm font-medium transition ${
              activeTab === tab
                ? "border-b-2 border-[#86BC24] text-[#86BC24]"
                : "text-[#4C4C4C] hover:text-[#0F0B0B]"
            }`}
          >
            {tab === "locks" && "Cell Locks"}
            {tab === "presence" && "User Presence"}
            {tab === "conflicts" && "Conflicts"}
          </button>
        ))}
      </div>

      {/* Locks Tab */}
      {activeTab === "locks" && (
        <div className="space-y-3">
          {locks.length === 0 ? (
            <Card className="bg-[#f0f8f0]">
              <div className="p-6 text-center">
                <p className="text-sm text-[#86BC24]">
                  ✓ All cells are unlocked
                </p>
              </div>
            </Card>
          ) : (
            locks.map((lock) => (
              <Card
                key={lock.cellRef}
                className={`bg-white ${
                  expandedCell === lock.cellRef ? "border-[#86BC24]" : ""
                }`}
              >
                <button
                  onClick={() =>
                    setExpandedCell(
                      expandedCell === lock.cellRef ? "" : lock.cellRef
                    )
                  }
                  className="w-full p-4 text-left transition hover:bg-[#f9f9f9]"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1">
                      <p className="font-mono font-bold text-[#0F0B0B]">
                        {lock.cellRef}
                      </p>
                      <div className="mt-1 flex items-center gap-2">
                        <Badge
                          variant={
                            lock.status === "locked"
                              ? "error"
                              : lock.status === "conflicted"
                              ? "warning"
                              : "success"
                          }
                        >
                          {lock.status}
                        </Badge>
                        <span className="text-xs text-[#4C4C4C]">
                          v{lock.version}
                        </span>
                      </div>
                    </div>
                    <div>
                      <p className="text-xs text-[#4C4C4C]">
                        Locked by {lock.lockedBy}
                      </p>
                      <p className="text-xs text-[#4C4C4C]">
                        {new Date(lock.lockedAt).toLocaleTimeString()}
                      </p>
                    </div>
                  </div>

                  {/* Expanded Details */}
                  {expandedCell === lock.cellRef && (
                    <div className="mt-4 space-y-3 border-t border-[#f0f0f0] pt-4">
                      <div className="grid gap-3 sm:grid-cols-2">
                        <div>
                          <p className="text-xs font-semibold text-[#4C4C4C]">
                            Locked By
                          </p>
                          <p className="mt-1 text-sm text-[#0F0B0B]">
                            {lock.lockedBy}
                          </p>
                        </div>
                        <div>
                          <p className="text-xs font-semibold text-[#4C4C4C]">
                            Lock Time
                          </p>
                          <p className="mt-1 text-sm text-[#0F0B0B]">
                            {new Date(lock.lockedAt).toLocaleString()}
                          </p>
                        </div>
                      </div>

                      {lock.expiresAt && (
                        <div className="rounded-lg bg-blue-50 border border-blue-200 p-3">
                          <p className="text-xs font-semibold text-blue-700">
                            ⏱️ Lock expires in{" "}
                            {Math.ceil(
                              (new Date(lock.expiresAt).getTime() -
                                new Date().getTime()) /
                                1000 /
                                60
                            )}{" "}
                            minutes
                          </p>
                        </div>
                      )}

                      <div className="flex gap-2 pt-2">
                        <button
                          onClick={() => onRetry?.(lock.cellRef)}
                          className="flex-1 rounded-lg bg-blue-600 px-3 py-2 text-xs font-medium text-white hover:bg-blue-700 transition"
                        >
                          Retry
                        </button>
                        <button
                          onClick={() =>
                            onForceRelease?.(lock.cellRef, lock.lockedBy)
                          }
                          className="flex-1 rounded-lg bg-red-600 px-3 py-2 text-xs font-medium text-white hover:bg-red-700 transition"
                        >
                          Force Release
                        </button>
                      </div>
                    </div>
                  )}
                </button>
              </Card>
            ))
          )}
        </div>
      )}

      {/* Presence Tab */}
      {activeTab === "presence" && (
        <div className="space-y-3">
          {presence.length === 0 ? (
            <Card className="bg-white">
              <div className="p-6 text-center">
                <p className="text-sm text-[#4C4C4C]">
                  No users currently in session
                </p>
              </div>
            </Card>
          ) : (
            presence.map((user) => (
              <Card
                key={user.userId}
                className={`bg-white ${user.isActive ? "border-l-4 border-[#86BC24]" : ""}`}
              >
                <div className="p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <div
                          className={`h-3 w-3 rounded-full ${
                            user.isActive
                              ? "bg-[#86BC24]"
                              : "bg-[#cccccc]"
                          }`}
                        />
                        <p className="font-semibold text-[#0F0B0B]">
                          {user.userName}
                        </p>
                      </div>
                      {user.currentCell && (
                        <p className="mt-1 text-xs text-[#4C4C4C]">
                          Currently editing: {user.currentCell}
                        </p>
                      )}
                    </div>
                    <div className="text-right">
                      <Badge
                        variant={user.isActive ? "success" : "info"}
                      >
                        {user.isActive ? "Active" : "Inactive"}
                      </Badge>
                      <p className="mt-1 text-xs text-[#4C4C4C]">
                        {new Date(user.lastSeen).toLocaleTimeString()}
                      </p>
                    </div>
                  </div>
                </div>
              </Card>
            ))
          )}
        </div>
      )}

      {/* Conflicts Tab */}
      {activeTab === "conflicts" && (
        <div className="space-y-3">
          {conflicts.length === 0 ? (
            <Card className="bg-[#f0f8f0]">
              <div className="p-6 text-center">
                <p className="text-sm text-[#86BC24]">
                  ✓ No version conflicts detected
                </p>
              </div>
            </Card>
          ) : (
            conflicts.map((conflict) => (
              <Card
                key={`${conflict.cellRef}-${conflict.conflictingUser}`}
                className="bg-white border-l-4 border-orange-500"
              >
                <div className="p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1">
                      <p className="font-mono font-bold text-[#0F0B0B]">
                        {conflict.cellRef}
                      </p>
                      <p className="mt-1 text-sm text-orange-600">
                        Conflicting edits with {conflict.conflictingUser}
                      </p>
                      <div className="mt-2 grid gap-2 sm:grid-cols-2">
                        <div className="rounded-lg bg-blue-50 p-2">
                          <p className="text-xs font-semibold text-blue-700">
                            Your Version
                          </p>
                          <p className="mt-1 font-mono text-xs text-blue-900">
                            v{conflict.yourVersion}
                          </p>
                        </div>
                        <div className="rounded-lg bg-orange-50 p-2">
                          <p className="text-xs font-semibold text-orange-700">
                            Their Version
                          </p>
                          <p className="mt-1 font-mono text-xs text-orange-900">
                            v{conflict.theirVersion}
                          </p>
                        </div>
                      </div>
                    </div>
                    <Badge variant="warning">Conflict</Badge>
                  </div>
                  <p className="mt-3 text-xs text-[#4C4C4C]">
                    {new Date(conflict.timestamp).toLocaleString()}
                  </p>
                </div>
              </Card>
            ))
          )}
        </div>
      )}
    </div>
  );
}
