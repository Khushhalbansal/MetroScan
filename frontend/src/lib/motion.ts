/*
  Motion primitives — the small amount of shared machinery behind the v2
  "Motion & depth" amendment to docs/design-direction.md.

  Deliberately tiny and dependency-free. The v2 amendment caps every effect
  (≤ 6° tilt, ≤ 12px parallax, ≤ 240ms transitions, one overshoot, never looping),
  so none of it needs a physics engine — a well-chosen easing token and an
  IntersectionObserver cover the whole surface. The CSS side collapses under
  `prefers-reduced-motion` via tokens.css; anything driven from JS gates on
  usePrefersReducedMotion() here so the two paths agree.
*/

import { useEffect, useRef, useState } from "react";

const REDUCE_QUERY = "(prefers-reduced-motion: reduce)";

/** Synchronous read, for a one-off decision outside React (e.g. an event handler). */
export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.(REDUCE_QUERY).matches;
}

/**
 * Live `prefers-reduced-motion`. Re-renders if the OS setting changes mid-session,
 * so a running view honours it without a reload.
 */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(prefersReducedMotion);

  useEffect(() => {
    const mq = window.matchMedia?.(REDUCE_QUERY);
    if (!mq) return;
    const onChange = () => setReduced(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  return reduced;
}

interface InViewOptions {
  /** Fire once and stop observing. Default true — data "draws itself once". */
  once?: boolean;
  /** Margin around the root before the element counts as in view. */
  rootMargin?: string;
  /** How much of the element must be visible, 0–1. */
  amount?: number;
}

/**
 * `[ref, inView]` — attach `ref` to an element, read `inView` to drive a
 * draw-on-enter animation. Under reduced motion it reports `true` immediately so
 * the content is simply present, never staged.
 */
export function useInView<T extends Element = HTMLDivElement>(
  options: InViewOptions = {},
): [React.RefObject<T | null>, boolean] {
  const { once = true, rootMargin = "0px 0px -10% 0px", amount = 0.15 } = options;
  const ref = useRef<T>(null);
  const reduced = usePrefersReducedMotion();
  const [inView, setInView] = useState(reduced);

  useEffect(() => {
    if (reduced) {
      setInView(true);
      return;
    }
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") {
      setInView(true);
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setInView(true);
          if (once) observer.disconnect();
        } else if (!once) {
          setInView(false);
        }
      },
      { rootMargin, threshold: amount },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [once, rootMargin, amount, reduced]);

  return [ref, inView];
}

/**
 * A staggered per-item delay in milliseconds, capped so a long list never turns
 * into a slow cascade. Used by list/grid enters (v2: "stagger ≤ 40ms per item").
 */
export function stagger(index: number, step = 32, cap = 240): number {
  return Math.min(index * step, cap);
}

/**
 * Pointer-follow tilt for a physical-object component (v2: "The Measure may tilt",
 * ≤ 6° with a spring back). Sets `--tilt-x` / `--tilt-y` / `--tilt-settle` on the
 * element; the element's CSS turns those into a `perspective()` transform. The tilt
 * carries no information — it is the feel of a rule under a desk lamp.
 *
 * No-ops on touch, on coarse pointers, and under reduced motion.
 */
export function useTilt<T extends HTMLElement = HTMLElement>(
  maxDeg = 6,
): React.RefObject<T | null> {
  const ref = useRef<T>(null);
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    const el = ref.current;
    if (!el || reduced) return;
    if (!window.matchMedia?.("(hover: hover) and (pointer: fine)").matches) return;

    const settle = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) return;
      const px = (e.clientX - r.left) / r.width - 0.5; // -0.5 … 0.5
      const py = (e.clientY - r.top) / r.height - 0.5;
      el.style.setProperty("--tilt-y", `${(px * 2 * maxDeg).toFixed(2)}deg`);
      el.style.setProperty("--tilt-x", `${(-py * 2 * maxDeg * 0.6).toFixed(2)}deg`);
      el.style.setProperty("--tilt-settle", "0ms"); // follow directly while pointing
    };
    const rest = () => {
      el.style.setProperty("--tilt-x", "0deg");
      el.style.setProperty("--tilt-y", "0deg");
      el.style.setProperty("--tilt-settle", "260ms"); // spring back on leave
    };

    el.addEventListener("pointermove", settle);
    el.addEventListener("pointerleave", rest);
    el.addEventListener("pointercancel", rest);
    return () => {
      el.removeEventListener("pointermove", settle);
      el.removeEventListener("pointerleave", rest);
      el.removeEventListener("pointercancel", rest);
    };
  }, [maxDeg, reduced]);

  return ref;
}

/**
 * Pointer parallax for a layered panel (v2: "the bench has up to three planes",
 * translation capped at 12px). Sets `--par-x` / `--par-y` on the element in the
 * range ±`maxPx`; children multiply those by their own depth factor and sign so
 * the planes slide against each other. No-ops on touch / coarse / reduced motion.
 */
export function useParallax<T extends HTMLElement = HTMLElement>(
  maxPx = 12,
): React.RefObject<T | null> {
  const ref = useRef<T>(null);
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    const el = ref.current;
    if (!el || reduced) return;
    if (!window.matchMedia?.("(hover: hover) and (pointer: fine)").matches) return;

    const move = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) return;
      const px = ((e.clientX - r.left) / r.width - 0.5) * 2; // -1 … 1
      const py = ((e.clientY - r.top) / r.height - 0.5) * 2;
      el.style.setProperty("--par-x", `${(px * maxPx).toFixed(1)}px`);
      el.style.setProperty("--par-y", `${(py * maxPx).toFixed(1)}px`);
      el.style.setProperty("--par-settle", "0ms");
    };
    const rest = () => {
      el.style.setProperty("--par-x", "0px");
      el.style.setProperty("--par-y", "0px");
      el.style.setProperty("--par-settle", "300ms");
    };

    el.addEventListener("pointermove", move);
    el.addEventListener("pointerleave", rest);
    el.addEventListener("pointercancel", rest);
    return () => {
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerleave", rest);
      el.removeEventListener("pointercancel", rest);
    };
  }, [maxPx, reduced]);

  return ref;
}
