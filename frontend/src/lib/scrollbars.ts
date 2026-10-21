/** Reveal native scrollbars during interaction without changing scroll geometry. */
export function initializeAutoHideScrollbars(): () => void {
  const root = document.documentElement;
  const timers = new Map<HTMLElement, ReturnType<typeof window.setTimeout>>();
  const idleDelay = 2000;
  let pointerDown = false;
  let lastPointerMove = 0;

  const scheduleHide = (element: HTMLElement) => {
    window.clearTimeout(timers.get(element));
    timers.set(element, window.setTimeout(() => {
      if (pointerDown) return;
      element.removeAttribute("data-scrollbar-active");
      timers.delete(element);
    }, idleDelay));
  };

  const reveal = (element: HTMLElement) => {
    element.setAttribute("data-scrollbar-active", "");
    scheduleHide(element);
  };

  const revealAncestors = (event: Event) => {
    let element = event.target instanceof Element ? event.target : null;
    while (element && element !== root) {
      if (element instanceof HTMLElement && (element.scrollHeight > element.clientHeight || element.scrollWidth > element.clientWidth)) {
        const style = window.getComputedStyle(element);
        if (/auto|scroll|overlay/.test(`${style.overflowX} ${style.overflowY}`)) reveal(element);
      }
      element = element.parentElement;
    }
    reveal(root);
  };

  const onScroll = (event: Event) => {
    reveal(event.target instanceof HTMLElement ? event.target : root);
  };

  const onPointerMove = (event: PointerEvent) => {
    const now = performance.now();
    if (now - lastPointerMove < 100) return;
    lastPointerMove = now;
    revealAncestors(event);
  };

  const onPointerDown = (event: PointerEvent) => {
    pointerDown = true;
    revealAncestors(event);
  };

  const onPointerUp = () => {
    pointerDown = false;
    timers.forEach((_, element) => scheduleHide(element));
  };

  document.addEventListener("scroll", onScroll, { capture: true, passive: true });
  document.addEventListener("pointerover", revealAncestors, { passive: true });
  document.addEventListener("pointermove", onPointerMove, { passive: true });
  document.addEventListener("pointerdown", onPointerDown, { passive: true });
  document.addEventListener("focusin", revealAncestors);
  window.addEventListener("pointerup", onPointerUp, { passive: true });
  window.addEventListener("pointercancel", onPointerUp, { passive: true });
  window.addEventListener("blur", onPointerUp);
  root.setAttribute("data-auto-hide-scrollbars", "");
  reveal(root);

  return () => {
    document.removeEventListener("scroll", onScroll, true);
    document.removeEventListener("pointerover", revealAncestors);
    document.removeEventListener("pointermove", onPointerMove);
    document.removeEventListener("pointerdown", onPointerDown);
    document.removeEventListener("focusin", revealAncestors);
    window.removeEventListener("pointerup", onPointerUp);
    window.removeEventListener("pointercancel", onPointerUp);
    window.removeEventListener("blur", onPointerUp);
    timers.forEach((timer, element) => {
      window.clearTimeout(timer);
      element.removeAttribute("data-scrollbar-active");
    });
    timers.clear();
    root.removeAttribute("data-auto-hide-scrollbars");
  };
}
