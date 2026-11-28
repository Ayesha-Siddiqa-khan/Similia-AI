import { timingSafeEqual } from "node:crypto";
import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

export async function proxy(request: NextRequest) {
  const token = process.env.SIMILIA_RENDERER_TOKEN;
  const desktopOrigin = process.env.SIMILIA_DESKTOP_ORIGIN;
  if (token) {
    const supplied = Buffer.from(request.headers.get("x-similia-renderer-token") ?? "");
    const expected = Buffer.from(token);
    if (!desktopOrigin || request.headers.get("host") !== new URL(desktopOrigin).host ||
        supplied.length !== expected.length || !timingSafeEqual(supplied, expected)) {
      return new NextResponse(null, { status: 403, headers: { "Cache-Control": "no-store" } });
    }
  }
  const pathname = request.nextUrl.pathname;
  const protectedPage = pathname === "/workspace" || pathname.startsWith("/workspace/");
  if (!protectedPage && pathname !== "/login" && !pathname.startsWith("/api/backend/")) {
    return NextResponse.next();
  }
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  const loginUrl = new URL("/login", desktopOrigin ?? request.url);
  if (!url || !key) {
    return protectedPage ? NextResponse.redirect(loginUrl) : NextResponse.next();
  }
  let response = NextResponse.next({ request });
  const supabase = createServerClient(url, key, { cookies: {
    getAll: () => request.cookies.getAll(),
    setAll(cookies, headers) {
      cookies.forEach(({ name, value }) => request.cookies.set(name, value));
      response = NextResponse.next({ request });
      cookies.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
      Object.entries(headers ?? {}).forEach(([key, value]) => response.headers.set(key, value));
    },
  } });
  try {
    const { data, error } = await supabase.auth.getClaims();
    if (protectedPage && (error || !data?.claims)) {
      const redirect = NextResponse.redirect(loginUrl);
      response.cookies.getAll().forEach((cookie) => redirect.cookies.set(cookie));
      redirect.headers.set("Cache-Control", "private, no-store");
      return redirect;
    }
  } catch {
    if (protectedPage) return NextResponse.redirect(loginUrl);
  }
  response.headers.set("Cache-Control", "private, no-store");
  return response;
}
