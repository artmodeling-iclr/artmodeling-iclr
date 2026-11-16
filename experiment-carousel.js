(() => {
  function init() {
    const viewport = document.getElementById("experiment-viewport");
    const previous = document.getElementById("experiment-prev");
    const next = document.getElementById("experiment-next");
    const pagination = document.getElementById("experiment-dots");
    if (!viewport || !previous || !next || !pagination) return;

    const slides = Array.from(viewport.querySelectorAll(".experiment-slide"));
    if (!slides.length) return;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let activeIndex = -1;
    let requestedIndex = null;
    let scrollFrame = 0;
    let settleTimer = 0;

    function offset(index) {
      return slides[index].offsetLeft - slides[0].offsetLeft;
    }

    function syncHeight() {
      viewport.style.height = `${Math.ceil(slides[activeIndex].getBoundingClientRect().height)}px`;
    }

    function showActive(index) {
      if (index !== activeIndex) {
        slides.forEach((slide, slideIndex) => {
          slide.querySelectorAll("video").forEach((video) => {
            if (slideIndex === index) {
              const playback = video.play();
              if (playback) playback.catch(() => {});
            } else {
              video.pause();
            }
          });
        });
      }
      activeIndex = index;
      syncHeight();
      dots.forEach((dot, dotIndex) => {
        if (dotIndex === index) dot.setAttribute("aria-current", "true");
        else dot.removeAttribute("aria-current");
      });
    }

    function nearestIndex() {
      let nearest = 0;
      let distance = Infinity;
      slides.forEach((_, index) => {
        const currentDistance = Math.abs(viewport.scrollLeft - offset(index));
        if (currentDistance < distance) {
          nearest = index;
          distance = currentDistance;
        }
      });
      return nearest;
    }

    function goTo(index) {
      const wrapped = index < 0 || index >= slides.length;
      const target = (index + slides.length) % slides.length;
      requestedIndex = target;
      showActive(target);
      viewport.scrollTo({ left: offset(target), behavior: wrapped || reducedMotion.matches ? "auto" : "smooth" });
      window.clearTimeout(settleTimer);
      settleTimer = window.setTimeout(() => {
        requestedIndex = null;
        showActive(nearestIndex());
      }, 650);
    }

    const dots = slides.map((slide, index) => {
      const dot = document.createElement("button");
      dot.type = "button";
      dot.setAttribute("aria-label", `Show ${slide.dataset.label || `evaluation ${index + 1}`}, ${index + 1} of ${slides.length}`);
      dot.addEventListener("click", () => goTo(index));
      pagination.appendChild(dot);
      return dot;
    });

    previous.addEventListener("click", () => goTo((requestedIndex ?? activeIndex) - 1));
    next.addEventListener("click", () => goTo((requestedIndex ?? activeIndex) + 1));
    viewport.addEventListener("scroll", () => {
      if (scrollFrame) return;
      scrollFrame = window.requestAnimationFrame(() => {
        scrollFrame = 0;
        if (requestedIndex !== null && Math.abs(viewport.scrollLeft - offset(requestedIndex)) > 2) return;
        requestedIndex = null;
        showActive(nearestIndex());
      });
    }, { passive: true });
    viewport.addEventListener("keydown", (event) => {
      if (event.target instanceof HTMLMediaElement) return;
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        goTo((requestedIndex ?? activeIndex) + (event.key === "ArrowRight" ? 1 : -1));
      }
    });
    pagination.addEventListener("keydown", (event) => {
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        const index = (activeIndex + (event.key === "ArrowRight" ? 1 : -1) + slides.length) % slides.length;
        goTo(index);
        dots[index].focus();
      }
    });
    if ("ResizeObserver" in window) {
      const observer = new ResizeObserver(() => {
        syncHeight();
        viewport.scrollTo({ left: offset(activeIndex), behavior: "auto" });
      });
      slides.forEach((slide) => observer.observe(slide));
    }
    window.addEventListener("resize", syncHeight);
    showActive(0);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
})();
