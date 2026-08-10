"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import { cn } from "@/lib/cn";

type ToastTone = "success" | "error" | "info";

interface Toast {
  id: number;
  tone: ToastTone;
  title: string;
  description?: string;
}

interface ToastContextValue {
  push: (toast: Omit<Toast, "id">) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const TONE_STYLES: Record<ToastTone, string> = {
  success: "border-ok-200 bg-white",
  error: "border-stop-200 bg-white",
  info: "border-line bg-white",
};

const TONE_ACCENT: Record<ToastTone, string> = {
  success: "bg-ok-600",
  error: "bg-stop-600",
  info: "bg-accent-700",
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = useCallback((toast: Omit<Toast, "id">) => {
    const id = Date.now() + Math.floor(Math.random() * 1000);
    setToasts((current) => [...current, { ...toast, id }]);
    setTimeout(() => {
      setToasts((current) => current.filter((item) => item.id !== id));
    }, 6000);
  }, []);

  const value = useMemo(() => ({ push }), [push]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        aria-atomic="false"
        className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2"
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            role="status"
            className={cn(
              "pointer-events-auto flex overflow-hidden rounded border shadow-sm",
              TONE_STYLES[toast.tone],
            )}
          >
            <span className={cn("w-1 shrink-0", TONE_ACCENT[toast.tone])} aria-hidden />
            <div className="px-3 py-2">
              <p className="text-body font-medium text-ink">{toast.title}</p>
              {toast.description ? (
                <p className="mt-0.5 text-meta text-ink-muted">{toast.description}</p>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  // Tests may render a component in isolation; a no-op keeps that from throwing.
  return context ?? { push: () => undefined };
}
