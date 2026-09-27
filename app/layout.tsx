import type { Metadata } from "next";
import "./globals.css";
import KeyConnectionMonitor from "./ui/KeyConnectionMonitor";

export const metadata: Metadata = {
  title: "家纺AI视觉｜全链路工作台",
  description: "家纺AI视觉全链路工作台动态首页。",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <head><script dangerouslySetInnerHTML={{ __html: `(() => {
        const apiOrigin = new URL(${JSON.stringify(process.env.NEXT_PUBLIC_STUDIO_API ?? "http://127.0.0.1:8000")}).origin;
        const originalFetch = window.fetch.bind(window);
        window.fetch = (input, init) => {
          try {
            const url = new URL(typeof input === "string" ? input : input.url, window.location.href);
            const key = sessionStorage.getItem("studio-personal-ark-key");
            if (key && url.origin === apiOrigin && url.pathname.startsWith("/api/")) {
              const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined));
              headers.set("X-User-Ark-Key", key);
              return originalFetch(input, { ...init, headers });
            }
          } catch { /* Browser storage may be unavailable; normal requests still work. */ }
          return originalFetch(input, init);
        };
      })();` }} /></head>
      <body>{children}<KeyConnectionMonitor /></body>
    </html>
  );
}
