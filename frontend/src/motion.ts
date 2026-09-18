export type MotionEventName =
  | "material.parsed"
  | "knowledge.ready"
  | "scene.entered"
  | "concept.focused"
  | "relation.selected"
  | "path.ready"
  | "review.persisted"
  | "motion.cancelled";

type MotionEvent = { name: MotionEventName; version: number; objectId?: string };
type Listener = (event: MotionEvent) => void;

class MotionOrchestrator {
  private version = 0;
  private listeners = new Set<Listener>();
  private systemReduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  private mode: "full" | "light" | "static" = "full";

  subscribe(listener: Listener) { this.listeners.add(listener); return () => this.listeners.delete(listener); }
  emit(name: MotionEventName, objectId?: string) {
    const event = { name, objectId, version: ++this.version } satisfies MotionEvent;
    this.listeners.forEach((listener) => listener(event));
    return event;
  }
  isReduced() { return this.systemReduced || this.mode === "static"; }
  setMode(mode: "full" | "light" | "static") { this.mode = mode; document.documentElement.dataset.motion = mode; }
}

export const motionOrchestrator = new MotionOrchestrator();
