import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { LoginForm } from "./login-form";

const { signIn, replace, refresh, getSession } = vi.hoisted(() => ({ signIn: vi.fn(), replace: vi.fn(), refresh: vi.fn(), getSession: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, refresh }) }));
vi.mock("@/lib/supabase/client", () => ({ createClient: () => ({ auth: { signInWithPassword: signIn, getSession } }) }));
afterEach(() => { cleanup(); vi.clearAllMocks(); localStorage.clear(); });
beforeEach(() => { getSession.mockResolvedValue({ data: { session: null } }); });
it("keeps sign-in disabled when public configuration is missing", () => {
  render(<LoginForm configured={false} />);
  expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
  expect(screen.queryByRole("link", { name: /preview/i })).toBeNull(); // there is no demo mode
});
it("validates credentials and shows a safe auth failure", async () => {
  signIn.mockResolvedValue({ error: new Error("internal provider details") });
  render(<LoginForm configured />);
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByText("Enter a valid email address.")).toBeInTheDocument();
  expect(signIn).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "fixture@example.invalid" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "synthetic-password" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByText(/Sign-in failed/)).toBeInTheDocument();
  expect(screen.queryByText("internal provider details")).not.toBeInTheDocument();
  expect(replace).not.toHaveBeenCalled();
});
it("refreshes protected routes after a successful fixture sign-in", async () => {
  signIn.mockResolvedValue({ error: null });
  render(<LoginForm configured />);
  fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "fixture@example.invalid" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "synthetic-password" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  await vi.waitFor(() => expect(replace).toHaveBeenCalledWith("/workspace/dashboard"));
  expect(refresh).toHaveBeenCalled();
});
it("shows and hides the password on request", () => {
  render(<LoginForm configured />);
  const input = screen.getByLabelText("Password");
  expect(input).toHaveAttribute("type", "password");
  fireEvent.click(screen.getByRole("button", { name: "Show password" }));
  expect(input).toHaveAttribute("type", "text");
  fireEvent.click(screen.getByRole("button", { name: "Hide password" }));
  expect(input).toHaveAttribute("type", "password");
});
it("remembers only the email, never the password, and can forget it", async () => {
  signIn.mockResolvedValue({ error: null });
  render(<LoginForm configured />);
  fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "fixture@example.invalid" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "synthetic-password" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  await vi.waitFor(() => expect(replace).toHaveBeenCalled());
  expect(localStorage.getItem("similia.remembered-email")).toBe("fixture@example.invalid");
  expect(JSON.stringify({ ...localStorage })).not.toContain("synthetic-password");
  cleanup();
  render(<LoginForm configured />);
  expect(await screen.findByDisplayValue("fixture@example.invalid")).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText(/Remember me/));
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "synthetic-password" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  await vi.waitFor(() => expect(localStorage.getItem("similia.remembered-email")).toBeNull());
});
it("skips the form when a session already exists", async () => {
  getSession.mockResolvedValue({ data: { session: { access_token: "synthetic" } } });
  render(<LoginForm configured />);
  await vi.waitFor(() => expect(replace).toHaveBeenCalledWith("/workspace/dashboard"));
});
