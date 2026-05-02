"use client";

import { AlertCircle, AlertTriangle, Info, X } from "lucide-react";
import { useState } from "react";

/**
 * SystemBanner — unified system message banner for alerts, warnings, and info.
 *
 * Displays at the top of the run studio for:
 * - Stream degradation warnings
 * - Polling mode notifications
 * - Governance/plan blocked errors
 * - General system messages
 */

export function SystemBanner({
  type = "info",
  title,
  detail,
  action,
  dismissible = true,
  onDismiss,
}: {
  type?: "info" | "warn" | "error";
  title: string;
  detail?: string;
  action?: {
    label: string;
    onClick: () => void;
  };
  dismissible?: boolean;
  onDismiss?: () => void;
}) {
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) return null;

  const config = {
    info: {
      bgColor: "bg-[#E3F2FD]",
      borderColor: "border-l-4 border-[#0072B1]",
      iconColor: "text-[#0072B1]",
      textColor: "text-[#0072B1]",
      icon: Info,
    },
    warn: {
      bgColor: "bg-[#FEF3E2]",
      borderColor: "border-l-4 border-[#B8651A]",
      iconColor: "text-[#B8651A]",
      textColor: "text-[#B8651A]",
      icon: AlertTriangle,
    },
    error: {
      bgColor: "bg-[#FFEBEE]",
      borderColor: "border-l-4 border-[#B23C3C]",
      iconColor: "text-[#B23C3C]",
      textColor: "text-[#B23C3C]",
      icon: AlertCircle,
    },
  };

  const { bgColor, borderColor, iconColor, textColor, icon: IconComponent } = config[type];

  const handleDismiss = () => {
    setDismissed(true);
    onDismiss?.();
  };

  return (
    <div
      className={`${bgColor} ${borderColor} px-4 py-3 flex items-start gap-3 ${dismissible ? "pr-10" : ""}`}
      role="alert"
      aria-live={type === "error" ? "assertive" : "polite"}
    >
      {/* Icon */}
      <IconComponent className={`h-5 w-5 shrink-0 mt-0.5 ${iconColor}`} aria-hidden />

      {/* Content */}
      <div className="flex-1 min-w-0">
        <p className={`text-sm font-semibold ${textColor}`}>{title}</p>
        {detail && <p className="text-xs text-[#666] mt-1">{detail}</p>}
        {action && (
          <button
            onClick={action.onClick}
            className={`text-xs font-semibold mt-2 underline ${textColor} hover:opacity-75 transition-opacity`}
          >
            {action.label}
          </button>
        )}
      </div>

      {/* Dismiss button */}
      {dismissible && (
        <button
          onClick={handleDismiss}
          className="absolute right-3 top-3 p-1 text-[#999] hover:text-[#666] transition-colors"
          aria-label="Dismiss message"
        >
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}
