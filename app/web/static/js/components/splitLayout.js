export function initSplitLayout() {
  const root = document.documentElement;
  const grid = document.querySelector(".grid-main");
  const savedLeft = localStorage.getItem("lca-left-w");
  const savedRight = localStorage.getItem("lca-right-w");
  if (savedLeft) root.style.setProperty("--left-w", `${savedLeft}px`);
  if (savedRight) root.style.setProperty("--right-w", `${savedRight}px`);
  const savedBottom = localStorage.getItem("lca-bottom-h");
  if (savedBottom) root.style.setProperty("--bottom-h", `${savedBottom}px`);

  document.querySelectorAll(".splitter").forEach((splitter) => {
    splitter.addEventListener("mousedown", (event) => {
      event.preventDefault();
      const side = splitter.dataset.resize;
      const startX = event.clientX;
      const startY = event.clientY;
      splitter.classList.add("dragging");

      const onMove = (moveEvent) => {
        if (side === "bottom") {
          const startHeight = parseFloat(root.style.getPropertyValue("--bottom-h") || "210");
          const delta = moveEvent.clientY - startY;
          const height = Math.min(420, Math.max(120, startHeight + delta));
          root.style.setProperty("--bottom-h", `${height}px`);
          localStorage.setItem("lca-bottom-h", String(height));
        } else {
          const startWidth = side === "left"
            ? parseFloat(root.style.getPropertyValue("--left-w") || "320")
            : parseFloat(root.style.getPropertyValue("--right-w") || "340");
          const delta = moveEvent.clientX - startX;
          const width = Math.min(440, Math.max(220, startWidth + (side === "left" ? delta : -delta)));
          root.style.setProperty(side === "left" ? "--left-w" : "--right-w", `${width}px`);
          localStorage.setItem(
            side === "left" ? "lca-left-w" : "lca-right-w",
            String(width),
          );
        }
      };
      const onUp = () => {
        splitter.classList.remove("dragging");
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  });

  document.querySelectorAll("[data-collapse]").forEach((button) => {
    button.addEventListener("click", () => {
      const side = button.dataset.collapse;
      const panel = side === "input" ? document.querySelector(".input-panel") : document.querySelector(".node-panel");
      const splitter = side === "input" ? document.querySelector(".splitter-left") : document.querySelector(".splitter-right");
      const collapsed = panel.classList.toggle("collapsed");
      root.style.setProperty(side === "input" ? "--left-w" : "--right-w", collapsed ? "0px" : (side === "input" ? "320px" : "340px"));
      if (splitter) splitter.style.display = collapsed ? "none" : "";
    });
  });
}
