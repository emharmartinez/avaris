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

function erf(x: number): number {
  // Abramowitz & Stegun 7.1.26, absolute error below 1.5e-7
  const sign = x < 0 ? -1 : 1;
  const a = Math.abs(x);
  const t = 1 / (1 + 0.3275911 * a);
  const poly = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741
    + t * (-1.453152027 + t * 1.061405429))));
  return sign * (1 - poly * Math.exp(-a * a));
}

export function normalCdf(x: number, mu: number, sigma: number): number {
  return 0.5 * (1 + erf((x - mu) / (sigma * Math.SQRT2)));
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
