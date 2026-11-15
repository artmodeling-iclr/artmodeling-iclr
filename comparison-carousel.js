(() => {
  function initCarousel() {
    const viewport = document.getElementById("comparison-viewport");
    const previous = document.getElementById("comparison-prev");
    const next = document.getElementById("comparison-next");
    const pagination = document.getElementById("comparison-dots");
    if (!viewport || !previous || !next || !pagination) return;

    const slides = Array.from(viewport.querySelectorAll(".comparison-slide"));
    if (!slides.length) return;

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const dots = slides.map((slide, index) => {
      const dot = document.createElement("button");
      const label = slide.dataset.label || `Comparison ${index + 1}`;
      dot.type = "button";
      dot.className = "comparison-dot";
      dot.setAttribute("aria-label", `Show ${label} comparison, ${index + 1} of ${slides.length}`);
      dot.addEventListener("click", () => goTo(index));
      pagination.appendChild(dot);
      return dot;
    });

    let activeIndex = 0;
    let requestedIndex = null;
    let scrollFrame = 0;
    let settleTimer = 0;

    function slideOffset(index) {
      return slides[index].offsetLeft - slides[0].offsetLeft;
    }

    function showActive(index) {
      activeIndex = index;
      dots.forEach((dot, dotIndex) => {
        if (dotIndex === index) dot.setAttribute("aria-current", "true");
        else dot.removeAttribute("aria-current");
      });
    }

    function indexFromScroll() {
      let nearest = 0;
      let distance = Infinity;
      slides.forEach((_, index) => {
        const nextDistance = Math.abs(viewport.scrollLeft - slideOffset(index));
        if (nextDistance < distance) {
          nearest = index;
          distance = nextDistance;
        }
      });
      return nearest;
    }

    function updateFromScroll() {
      scrollFrame = 0;
      if (requestedIndex !== null) {
        if (Math.abs(viewport.scrollLeft - slideOffset(requestedIndex)) > 2) return;
        requestedIndex = null;
      }
      showActive(indexFromScroll());
    }

    function goTo(index) {
      const wrapped = index < 0 || index >= slides.length;
      const target = (index + slides.length) % slides.length;
      requestedIndex = target;
      showActive(target);
      viewport.scrollTo({
        left: slideOffset(target),
        behavior: reducedMotion.matches || wrapped ? "auto" : "smooth",
      });
      window.clearTimeout(settleTimer);
      settleTimer = window.setTimeout(() => {
        requestedIndex = null;
        showActive(indexFromScroll());
      }, 650);
    }

    previous.addEventListener("click", () => goTo((requestedIndex ?? activeIndex) - 1));
    next.addEventListener("click", () => goTo((requestedIndex ?? activeIndex) + 1));

    viewport.addEventListener("scroll", () => {
      if (!scrollFrame) scrollFrame = window.requestAnimationFrame(updateFromScroll);
    }, { passive: true });

    viewport.addEventListener("keydown", (event) => {
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        goTo((requestedIndex ?? activeIndex) + (event.key === "ArrowRight" ? 1 : -1));
      }
    });

    pagination.addEventListener("keydown", (event) => {
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        const target = (activeIndex + (event.key === "ArrowRight" ? 1 : -1) + slides.length) % slides.length;
        goTo(target);
        dots[target].focus();
      }
    });

    if ("ResizeObserver" in window) {
      new ResizeObserver(() => viewport.scrollTo({ left: slideOffset(activeIndex), behavior: "auto" })).observe(viewport);
    }

    showActive(0);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initCarousel, { once: true });
  } else {
    initCarousel();
  }
})();
