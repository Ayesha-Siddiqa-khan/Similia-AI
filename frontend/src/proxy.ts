import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

export async function proxy(request: NextRequest) {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  const protectedPage = request.nextUrl.pathname.startsWith("/workspace");
  if (!url || !key) {
    return protectedPage ? NextResponse.redirect(new URL("/login", request.url)) : NextResponse.next();
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
      const redirect = NextResponse.redirect(new URL("/login", request.url));
      response.cookies.getAll().forEach((cookie) => redirect.cookies.set(cookie));
      redirect.headers.set("Cache-Control", "private, no-store");
      return redirect;
    }
  } catch {
    if (protectedPage) return NextResponse.redirect(new URL("/login", request.url));
  }
  response.headers.set("Cache-Control", "private, no-store");
  return response;
}

export const config = { matcher: ["/workspace/:path*", "/api/backend/:path*", "/login"] };
