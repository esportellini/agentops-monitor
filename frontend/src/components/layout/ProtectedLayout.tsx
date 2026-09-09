"use client";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Topbar } from "@/components/layout/Topbar";

export function ProtectedLayout({ children }: { children: ReactNode }) {
  const [navigationOpen, setNavigationOpen] = useState(false);
  const frameRef = useRef<HTMLDivElement>(null);
  const closeNavigation = useCallback(() => setNavigationOpen(false), []);
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    frame.inert = navigationOpen;
    if (navigationOpen) frame.setAttribute("aria-hidden", "true");
    else frame.removeAttribute("aria-hidden");
    document.body.style.overflow = navigationOpen ? "hidden" : "";
    return () => { frame.inert = false; frame.removeAttribute("aria-hidden"); document.body.style.overflow = ""; };
  }, [navigationOpen]);
  return <AuthGuard><div className="app-shell"><a className="skip-link" href="#main-content">Skip to content</a><Sidebar open={navigationOpen} onClose={closeNavigation} /><div ref={frameRef} className="app-frame"><Topbar onOpenNavigation={() => setNavigationOpen(true)} /><main id="main-content" className="app-main" tabIndex={-1}>{children}</main></div></div></AuthGuard>;
}
