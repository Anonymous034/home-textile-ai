const backendBase = (process.env.STUDIO_API_INTERNAL_URL || process.env.NEXT_PUBLIC_STUDIO_API || "http://127.0.0.1:8000").trim().replace(/\/+$/, "");

async function proxyAuth(request: Request): Promise<Response> {
  const incoming = new URL(request.url);
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  const cookie = request.headers.get("cookie");
  if (contentType) headers.set("content-type", contentType);
  if (cookie) headers.set("cookie", cookie);

  try {
    const target = new URL(`${incoming.pathname}${incoming.search}`, backendBase);
    const response = await fetch(target, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer(),
      cache: "no-store",
      redirect: "manual",
    });
    const responseHeaders = new Headers(response.headers);
    responseHeaders.delete("content-encoding");
    responseHeaders.delete("content-length");
    return new Response(response.body, { status: response.status, headers: responseHeaders });
  } catch {
    return Response.json({ ok: false, message: "验证服务暂时不可用，请确认后端已启动" }, { status: 503 });
  }
}

export const GET = proxyAuth;
export const POST = proxyAuth;
