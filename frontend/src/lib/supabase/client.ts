import { createBrowserClient } from "@supabase/ssr";

/**
 * Browser-side Supabase client (publishable/anon key only — never a secret
 * or service-role key in frontend code).
 */
export function createClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  if (!url || !key) {
    throw new Error(
      "Supabase is not configured. Set NEXT_PUBLIC_SUPABASE_URL and " +
        "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY in frontend/.env.local.",
    );
  }
  return createBrowserClient(url, key);
}
