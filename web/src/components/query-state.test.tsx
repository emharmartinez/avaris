import { render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { QueryState } from "./query-state";

describe("QueryState", () => {
  it("shows the error when there is nothing to show", () => {
    render(<QueryState query={{ data: undefined, error: new Error("down"), isPending: false }} label="teams">
      {(d: string) => d}
    </QueryState>);
    expect(screen.getByText("Could not load teams")).toBeInTheDocument();
  });

  it("keeps the data when a background refetch fails", () => {
    render(<QueryState query={{ data: "the table", error: new Error("down"), isPending: false }} label="teams">
      {(d: string) => d}
    </QueryState>);
    expect(screen.getByText("the table")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Could not refresh teams: down");
  });

  it("keeps the children mounted, with their state, when a refetch starts or stops failing", () => {
    function Counter() {
      const [n] = useState(() => Math.random());
      return <span data-testid="child">{n}</span>;
    }
    const ok = { data: "x", error: null, isPending: false };
    const { rerender } = render(<QueryState query={ok}>{() => <Counter />}</QueryState>);
    const before = screen.getByTestId("child").textContent;
    rerender(<QueryState query={{ ...ok, error: new Error("down") }}>{() => <Counter />}</QueryState>);
    expect(screen.getByTestId("child").textContent).toBe(before);
    rerender(<QueryState query={ok}>{() => <Counter />}</QueryState>);
    expect(screen.getByTestId("child").textContent).toBe(before);
  });
});
