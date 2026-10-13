import { describe, expect, it } from "vitest";
import { normalCurve, normalPdf } from "./distribution";

describe("normal distribution", () => {
  it("has the standard normal density at the mean", () => {
    expect(normalPdf(0, 0, 1)).toBeCloseTo(0.398942, 5);
    expect(normalPdf(10, 10, 2)).toBeCloseTo(0.398942 / 2, 5);
  });
  it("samples a curve over mu ± 3 sigma and marks the 80% interval", () => {
    const curve = normalCurve({ mu: 0, sigma: 10, lo: -12.8, hi: 12.8 }, 61);
    expect(curve).toHaveLength(61);
    expect(curve[0].x).toBeCloseTo(-30);
    expect(curve[60].x).toBeCloseTo(30);
    expect(curve[30]).toMatchObject({ x: 0 });
    expect(curve[30].band).toBeCloseTo(curve[30].density);
    expect(curve[0].band).toBeNull();
  });
});
