import { render, screen } from "@testing-library/react";
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
});
