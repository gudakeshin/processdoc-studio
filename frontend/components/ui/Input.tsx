import { type InputHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

type InputProps = InputHTMLAttributes<HTMLInputElement> & {
  error?: string;
};

export function Input({ error, id, ...props }: InputProps) {
  const errorId = error && id ? `${id}-error` : undefined;
  return (
    <div className="w-full">
      <input
        id={id}
        aria-invalid={error ? "true" : undefined}
        aria-describedby={errorId}
        {...props}
        className={cn(
          "w-full border border-[#E5E5E5] bg-white px-4 py-2 text-sm text-[var(--text-default)] outline-none ring-[#0F0B0B] transition focus:ring-2 focus:border-[#0F0B0B]",
          error && "border-[var(--error,#B23C3C)] focus:border-[var(--error,#B23C3C)]",
          props.className
        )}
      />
      {error && errorId && (
        <span id={errorId} role="alert" className="mt-1 block text-xs text-[var(--error,#B23C3C)]">
          {error}
        </span>
      )}
    </div>
  );
}
