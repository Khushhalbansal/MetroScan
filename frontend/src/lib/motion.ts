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
