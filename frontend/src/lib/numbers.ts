export function formatDisplayNumber(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "Unknown";
  const rounded = Math.round((value + Number.EPSILON) * 100) / 100;
  return rounded.toFixed(2);
}
