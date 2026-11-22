"use client";
import { Notice } from "@/components/ui";
export default function ErrorPage({ reset }: { reset: () => void }) {
  return <div className="main-content"><h1>Unable to load this page</h1><Notice error>The workspace encountered an unexpected error. No operation has been retried automatically.</Notice><button className="button secondary" onClick={reset}>Try again</button></div>;
}
