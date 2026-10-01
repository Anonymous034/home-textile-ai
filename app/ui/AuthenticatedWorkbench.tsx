"use client";

import { useEffect, useRef, useState } from "react";
import DemoLoginForm from "./DemoLoginForm";
import WorkbenchDashboard from "./WorkbenchDashboard";
import "./AuthenticatedWorkbench.css";

const API = (process.env.NEXT_PUBLIC_STUDIO_API ?? "http://127.0.0.1:8000").replace(/\/$/, "");
type AuthStatus = "checking" | "authenticated" | "unauthenticated";

export default function AuthenticatedWorkbench() {
  const [status, setStatus] = useState<AuthStatus>("checking");
  const [gateOpen, setGateOpen] = useState(false);
  const [pendingFeature, setPendingFeature] = useState<string | null>(null);
  const [workbenchKey, setWorkbenchKey] = useState(0);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API}/api/auth/me`, {
      credentials: "include",
      cache: "no-store",
      signal: controller.signal,
    })
      .then((response) => response.ok ? response.json() : null)
      .then((data: { authenticated?: boolean } | null) => {
        setStatus(data?.authenticated ? "authenticated" : "unauthenticated");
      })
      .catch((error: unknown) => {
        if ((error as { name?: string })?.name !== "AbortError") setStatus("unauthenticated");
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!gateOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const focusFirstControl = window.requestAnimationFrame(() => {
      dialogRef.current?.querySelector<HTMLElement>("input, button, a[href]")?.focus();
    });
    const keepFocusInside = (event: KeyboardEvent) => {
      if (event.key !== "Tab" || !dialogRef.current) return;
      const controls = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(
        'input:not([disabled]), button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
      ));
      if (!controls.length) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", keepFocusInside);
    return () => {
      window.cancelAnimationFrame(focusFirstControl);
      document.removeEventListener("keydown", keepFocusInside);
      document.body.style.overflow = previousOverflow;
    };
  }, [gateOpen]);

  const selectFeature = async (href: string) => {
    if (status === "authenticated") {
      window.location.assign(href);
      return;
    }
    if (status === "checking") {
      try {
        const response = await fetch(`${API}/api/auth/me`, { credentials: "include", cache: "no-store" });
        const data = response.ok ? (await response.json()) as { authenticated?: boolean } : null;
        if (data?.authenticated) {
          setStatus("authenticated");
          window.location.assign(href);
          return;
        }
      } catch {
        // If the check fails, keep the visitor on the workbench and offer login.
      }
      setStatus("unauthenticated");
    }
    setPendingFeature(href);
    setGateOpen(true);
  };

  const unlockWorkbench = () => {
    setWorkbenchKey((value) => value + 1);
    setStatus("authenticated");
    setGateOpen(false);
    if (pendingFeature) window.location.assign(pendingFeature);
  };

  return (
    <div className={`authenticated-workbench is-${status}`}>
      <div className="authenticated-workbench__surface" aria-hidden={gateOpen}>
        <WorkbenchDashboard key={workbenchKey} onFeatureSelect={selectFeature} onLoginRequest={() => setGateOpen(true)} />
      </div>

      {gateOpen && (
        <div className="auth-gate">
          <div className="auth-gate__scrim" aria-hidden="true" />
          <div className="login-aurora auth-gate__aurora" aria-hidden="true">
            <i className="login-aurora__glow login-aurora__glow--cyan" />
            <i className="login-aurora__glow login-aurora__glow--blue" />
            <i className="login-aurora__glow login-aurora__glow--violet" />
            <i className="login-aurora__glow login-aurora__glow--center" />
          </div>
          <div
            className="auth-gate__dialog"
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-label="登录后继续使用家纺AI视觉工作台"
          >
            <DemoLoginForm onSuccess={unlockWorkbench} showBackLink={false} />
          </div>
        </div>
      )}
    </div>
  );
}
