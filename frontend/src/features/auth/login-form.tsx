"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { ArrowRight, Eye, EyeOff, Leaf, LockKeyhole } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { Notice } from "@/components/ui";

const schema = z.object({ email: z.email("Enter a valid email address."), password: z.string().min(1, "Enter your password.").max(256) });
type Credentials = z.infer<typeof schema>;

// Only the email is remembered here. Passwords are never stored by the app; the browser's own
// password manager (autocomplete="current-password") offers to save and fill them securely.
const REMEMBER_KEY = "similia.remembered-email";
const readRemembered = (): string => { try { return localStorage.getItem(REMEMBER_KEY) ?? ""; } catch { return ""; } };
const writeRemembered = (email: string | null) => { try { if (email) localStorage.setItem(REMEMBER_KEY, email); else localStorage.removeItem(REMEMBER_KEY); } catch { /* storage may be blocked */ } };

export function LoginForm({ configured }: { configured: boolean }) {
  const router = useRouter();
  const [error, setError] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [remember, setRemember] = useState(true);
  const { register, handleSubmit, setValue, formState: { errors, isSubmitting } } = useForm<Credentials>({ resolver: zodResolver(schema) });
  useEffect(() => {
    const saved = readRemembered();
    if (saved) setValue("email", saved);
    if (!configured) return;
    // Already signed in (the session cookie lasts across visits)? Skip the form.
    void (async () => {
      try {
        const { data } = await createClient().auth.getSession();
        if (data?.session) router.replace("/workspace/dashboard");
      } catch { /* stay on the sign-in form */ }
    })();
  }, [configured, router, setValue]);
  async function submit(value: Credentials) {
    setError("");
    try {
      const { error } = await createClient().auth.signInWithPassword(value);
      if (error) { setError("Sign-in failed. Check your credentials, email confirmation and account access."); return; }
      writeRemembered(remember ? value.email : null);
      router.replace("/workspace/dashboard");
      router.refresh();
    } catch { setError("Authentication service unavailable. Please try again later."); }
  }
  return <main className="login-page"><section className="login-story"><Link className="brand" href="/login"><span className="brand-mark"><Leaf aria-hidden /></span>similia<span className="brand-ai">AI</span></Link><div><span className="eyebrow">A MORE CONSIDERED WORKSPACE</span><h1>Knowledge you can<br />trace to its source.</h1><p>Explore your library. Inspect every passage. Bring clarity to practitioner review.</p><div className="login-lines"><div /><div /><div /></div></div><small>Built for practitioner-supervised exploration.</small></section><section className="login-form-wrap"><div className="login-card"><span className="login-lock"><LockKeyhole size={22} aria-hidden /></span><h2>Welcome to Similia AI</h2><p>Sign in to your knowledge workspace.</p>{!configured && <Notice>Live authentication is not configured. Set the public Supabase URL and publishable key in frontend/.env.local.</Notice>}<form onSubmit={handleSubmit(submit)} noValidate><label htmlFor="email">Email address</label><input id="email" type="email" autoComplete="username" placeholder="you@practice.com" {...register("email")} aria-invalid={!!errors.email} aria-describedby={errors.email ? "email-error" : undefined} />{errors.email && <p className="field-error" id="email-error">{errors.email.message}</p>}<label htmlFor="password">Password</label><div className="password-field"><input id="password" type={showPassword ? "text" : "password"} autoComplete="current-password" {...register("password")} aria-invalid={!!errors.password} aria-describedby={errors.password ? "password-error" : undefined} /><button type="button" className="password-toggle" onClick={() => setShowPassword((v) => !v)} aria-label={showPassword ? "Hide password" : "Show password"} aria-pressed={showPassword}>{showPassword ? <EyeOff size={18} aria-hidden /> : <Eye size={18} aria-hidden />}</button></div>{errors.password && <p id="password-error" className="field-error">{errors.password.message}</p>}<label htmlFor="remember" className="remember-row"><input id="remember" type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> Remember me on this device</label>{error && <Notice error>{error}</Notice>}<button className="button primary full" disabled={!configured || isSubmitting}>{isSubmitting ? "Signing in…" : "Sign in"}<ArrowRight size={17} aria-hidden /></button></form><p className="fine-print">Accounts require a practitioner or operator role. Patient information is confidential: record it only with the patient&apos;s consent.</p></div></section></main>;
}
