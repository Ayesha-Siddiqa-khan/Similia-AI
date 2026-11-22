import { LoginForm } from "@/features/auth";
export default function Login() {
  const configured = Boolean(process.env.NEXT_PUBLIC_SUPABASE_URL && process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY);
  return <LoginForm configured={configured} />;
}
