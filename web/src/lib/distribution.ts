import type { Interval } from "./types";

export interface CurvePoint {
  x: number;
  density: number;
  band: number | null; // density inside the 80% interval, null outside (for the shaded area)
}

export function normalPdf(x: number, mu: number, sigma: number): number {
  const z = (x - mu) / sigma;
  return Math.exp(-0.5 * z * z) / (sigma * Math.sqrt(2 * Math.PI));
}

export function normalCurve(i: Interval, points = 81): CurvePoint[] {
  const from = i.mu - 3 * i.sigma;
  const step = (6 * i.sigma) / (points - 1);
  return Array.from({ length: points }, (_, k) => {
    const x = from + k * step;
    const density = normalPdf(x, i.mu, i.sigma);
    return { x, density, band: x >= i.lo && x <= i.hi ? density : null };
  });
}
