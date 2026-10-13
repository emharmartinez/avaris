import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Markdown } from "./markdown";

describe("Markdown", () => {
  it("renders raw HTML blocks as literal text", () => {
    const script = "<script>alert(1)</script>";
    const { container } = render(<Markdown>{`# Report\n\n${script}\n\nAfter`}</Markdown>);
    expect(container).toHaveTextContent(script);
    expect(container.querySelector("script")).toBeNull();
  });

  it("renders inline raw HTML as literal text", () => {
    const img = `<img src=x onerror="alert(1)">`;
    const { container } = render(<Markdown>{`Before ${img} after`}</Markdown>);
    expect(container).toHaveTextContent(img);
    expect(container.querySelector("img")).toBeNull();
  });

  it("renders markdown images as their alt text", () => {
    const { container } = render(<Markdown>{"![a chart](https://example.com/c.svg)"}</Markdown>);
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("a chart")).toBeInTheDocument();
  });

  it("renders GFM tables inside a scroll container", () => {
    const { container } = render(<Markdown>{"| a | b |\n|---|---|\n| 1 | 2 |\n"}</Markdown>);
    const table = container.querySelector("table");
    expect(table).not.toBeNull();
    expect(table?.parentElement).toHaveClass("overflow-x-auto");
    expect(screen.getByRole("columnheader", { name: "a" })).toBeInTheDocument();
  });

  it("drops javascript: links but keeps http(s) and anchor links", () => {
    const { container } = render(<Markdown>{"[bad](javascript:alert(1))"}</Markdown>);
    expect(screen.getByText("bad")).toBeInTheDocument();
    expect(container.querySelector("a[href]")).toBeNull();

    render(<Markdown>{"[docs](https://example.com) [top](#top)"}</Markdown>);
    expect(screen.getByRole("link", { name: "docs" })).toHaveAttribute("href", "https://example.com");
    expect(screen.getByRole("link", { name: "docs" })).toHaveAttribute("rel", "noreferrer");
    expect(screen.getByRole("link", { name: "top" })).toHaveAttribute("href", "#top");
  });
});
