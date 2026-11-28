import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AppShell } from "./app-shell";

const route = vi.hoisted(() => ({ path: "/workspace/ai" }));
vi.mock("next/navigation", () => ({ usePathname: () => route.path, useRouter: () => ({}) }));
vi.mock("@/hooks/use-backend-health", () => ({ useBackendHealth: () => ({ isPending: false }) }));
vi.mock("@/hooks/use-workspace-scroll", () => ({ useWorkspaceScroll: () => null }));

afterEach(() => { cleanup(); localStorage.clear(); });

it("returns from AI Settings to the last case and keeps the case list accessible", () => {
  const casePath = "/workspace/case/12345678-1234-1234-1234-123456789abc";
  const shell = <AppShell accountId="account">Workspace content</AppShell>;
  const caseLink = () => screen.getByRole("link", { name: "AI Case Workspace" });

  route.path = "/workspace/ai";
  const view = render(shell);
  expect(caseLink()).toHaveAttribute("href", "/workspace/case");

  route.path = casePath;
  view.rerender(<AppShell accountId="account">Case content</AppShell>);
  expect(screen.getByRole("link", { name: "Recent cases" })).toHaveAttribute("href", "/workspace/case");

  route.path = "/workspace/ai";
  view.unmount();
  const returned = render(shell);
  expect(caseLink()).toHaveAttribute("href", casePath);
  expect(screen.getByRole("link", { name: "AI Settings" })).toHaveAttribute("href", "/workspace/ai");

  route.path = "/workspace/case";
  returned.rerender(<AppShell accountId="account">Recent cases</AppShell>);
  expect(caseLink()).toHaveAttribute("href", "/workspace/case");
});
