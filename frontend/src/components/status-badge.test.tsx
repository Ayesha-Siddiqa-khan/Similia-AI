import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusBadge } from "@/components/status-badge";

describe("StatusBadge", () => {
  it("shows the connected label for a healthy backend", () => {
    render(<StatusBadge status="ok" />);
    expect(screen.getByText("Backend connected")).toBeInTheDocument();
  });

  it("shows the unreachable label when the backend is down", () => {
    render(<StatusBadge status="down" />);
    expect(screen.getByText("Backend unreachable")).toBeInTheDocument();
  });
});
