import type { PreviewFault } from "../types";
import { PREVIEW } from "../constants";

const faults: PreviewFault[] = [];
const listeners = new Set<(faults: readonly PreviewFault[]) => void>();
export function reportPreviewFault(fault: PreviewFault): void {
  faults.push(fault);
  if (faults.length > PREVIEW.maxFaults) faults.shift();
  for (const listener of listeners) listener([...faults]);
}
export function subscribePreviewFaults(listener: (faults: readonly PreviewFault[]) => void): () => void {
  listeners.add(listener);
  listener([...faults]);
  return () => { listeners.delete(listener); };
}
