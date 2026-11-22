import Link from "next/link";
export default function NotFound() {
  return <main className="main-content"><h1>Page not found</h1><p>This workspace page is unavailable.</p><Link className="button secondary" href="/">Return to Similia AI</Link></main>;
}
