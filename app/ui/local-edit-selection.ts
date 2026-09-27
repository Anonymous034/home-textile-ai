export type SelectionPoint = { x: number; y: number };
export type SelectionRect = SelectionPoint & { width: number; height: number };

export function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, value));
}

export function selectionFromPoints(start: SelectionPoint, end: SelectionPoint): SelectionRect {
  const ax = clampPercent(start.x);
  const ay = clampPercent(start.y);
  const bx = clampPercent(end.x);
  const by = clampPercent(end.y);
  return { x: Math.min(ax, bx), y: Math.min(ay, by), width: Math.abs(ax - bx), height: Math.abs(ay - by) };
}

export function moveSelection(rect: SelectionRect, dx: number, dy: number): SelectionRect {
  return { ...rect, x: Math.max(0, Math.min(100 - rect.width, rect.x + dx)), y: Math.max(0, Math.min(100 - rect.height, rect.y + dy)) };
}
