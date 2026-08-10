export function initSplitLayout() {
  const grid = document.querySelector(".grid-main");
  const savedLeft = localStorage.getItem("lca-left-w");
  const savedRight = localStorage.getItem("lca-right-w");
  if (savedLeft) {
    grid.style.setProperty("--left-w", `${clamp(parseFloat(savedLeft) || 240, 44, 440)}px`);
  }
  if (savedRight) {
    grid.style.setProperty("--right-w", `${clamp(parseFloat(savedRight) || 260, 44, 440)}px`);
  }
  const savedBottom = localStorage.getItem("lca-bottom-h");
  if (savedBottom) {
    grid.style.setProperty("--bottom-h", `${clamp(parseFloat(savedBottom) || 210, 120, 420)}px`);
  }

  document.querySelectorAll(".splitter").forEach((splitter) => {
    splitter.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      try {
        splitter.setPointerCapture(event.pointerId);
      } catch {
        // synthetic events and some browsers do not support pointer capture
      }
      splitter.classList.add("dragging");
      const side = splitter.dataset.resize;
      const startX = event.clientX;
      const startY = event.clientY;
      const startWidth = side === "bottom"
        ? readVar("--bottom-h", 210, grid)
        : readVar(
            side === "left" ? "--left-w" : "--right-w",
            side === "left" ? 320 : 340,
            grid,
          );

      const onMove = (moveEvent) => {
        if (side === "bottom") {
          const height = clamp(startWidth + moveEvent.clientY - startY, 120, 420);
          grid.style.setProperty("--bottom-h", `${height}px`);
          localStorage.setItem("lca-bottom-h", String(height));
        } else {
          const delta = moveEvent.clientX - startX;
          const width = clamp(
            startWidth + (side === "left" ? delta : -delta),
            220,
            440,
          );
          grid.style.setProperty(
            side === "left" ? "--left-w" : "--right-w",
            `${width}px`,
          );
          localStorage.setItem(
            side === "left" ? "lca-left-w" : "lca-right-w",
            String(width),
          );
        }
      };
      const onUp = () => {
        splitter.classList.remove("dragging");
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    });
  });

  document.querySelectorAll("[data-collapse]").forEach((button) => {
    button.addEventListener("click", () => {
      const side = button.dataset.collapse;
      const panel = side === "input"
        ? document.querySelector(".input-panel")
        : document.querySelector(".node-panel");
      const splitter = side === "input"
        ? document.querySelector(".splitter-left")
        : document.querySelector(".splitter-right");
      const collapsed = panel.classList.toggle("collapsed");
      const width = collapsed ? 44 : side === "input" ? 320 : 340;
      grid.style.setProperty(
        side === "input" ? "--left-w" : "--right-w",
        `${width}px`,
      );
      localStorage.setItem(
        side === "input" ? "lca-left-w" : "lca-right-w",
        String(width),
      );
      if (splitter) splitter.style.display = collapsed ? "none" : "";
    });
  });
}

function readVar(name, fallback, element) {
  const value = parseFloat(getComputedStyle(element).getPropertyValue(name));
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}
