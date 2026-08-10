import { esc } from "../util.js";

export function openModal({ title, fields, confirmText = "确定", onConfirm }) {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-head"><h3>${title}</h3><button type="button" class="modal-close" aria-label="关闭">×</button></div>
      <div class="modal-body">${fields.map((field) => `
        <label class="modal-field">
          <span>${field.label}</span>
          ${field.type === "textarea"
            ? `<textarea placeholder="${esc(field.placeholder || "")}">${esc(field.value || "")}</textarea>`
            : `<input value="${(field.value || "").replace(/"/g, "&quot;")}" placeholder="${field.placeholder || ""}">`}
        </label>`).join("")}
      </div>
      <div class="modal-actions">
        <button type="button" class="ghost-btn modal-cancel">取消</button>
        <button type="button" class="primary-btn modal-confirm">${confirmText}</button>
      </div>
      <div class="modal-error"></div>
    </div>`;

  const close = () => overlay.remove();
  overlay.querySelector(".modal-close").addEventListener("click", close);
  overlay.querySelector(".modal-cancel").addEventListener("click", close);
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) close();
  });
  overlay.querySelector(".modal-confirm").addEventListener("click", async () => {
    const values = {};
    overlay.querySelectorAll(".modal-field").forEach((field, index) => {
      const input = field.querySelector("input, textarea");
      values[fields[index].key] = input.value.trim();
    });
    try {
      await onConfirm(values);
      close();
    } catch (error) {
      overlay.querySelector(".modal-error").textContent = error.message;
    }
  });

  document.body.appendChild(overlay);
}

export function confirmModal(message, onConfirm) {
  openModal({
    title: "确认操作",
    fields: [{ key: "message", label: "", value: message, type: "textarea", placeholder: "" }],
    confirmText: "确认",
    onConfirm,
  });
}
