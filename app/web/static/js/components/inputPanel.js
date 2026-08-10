import { api } from "../api.js";
import { emit } from "../bus.js";
import { setStatus, toast } from "./statusBar.js";

export function initInputPanel() {
  const content = document.getElementById("contentInput");
  const fileInput = document.getElementById("fileInput");
  const dropZone = document.getElementById("dropZone");
  const urlInput = document.getElementById("urlInput");
  const parseMeta = document.getElementById("parseMeta");
  const generateBtn = document.getElementById("generateBtn");
  const clearBtn = document.getElementById("clearBtn");
  const webSearchToggle = document.getElementById("webSearchToggle");
  const formatSelect = document.getElementById("formatSelect");
  const autoLinkToggle = document.getElementById("autoLinkToggle");

  document.getElementById("pickFileBtn").addEventListener("click", () => fileInput.click());

  fileInput.addEventListener("change", () => {
    for (const file of fileInput.files) uploadFile(file);
    fileInput.value = "";
  });

  ["dragover", "dragenter"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.add("dragover");
    });
  });
  ["dragleave", "drop"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.remove("dragover");
    });
  });
  dropZone.addEventListener("drop", (event) => {
    for (const file of event.dataTransfer.files) uploadFile(file);
  });

  document.getElementById("fetchUrlBtn").addEventListener("click", fetchUrl);
  urlInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") fetchUrl();
  });

  generateBtn.addEventListener("click", generate);
  clearBtn.addEventListener("click", () => {
    content.value = "";
    parseMeta.hidden = true;
    setStatus("已清空输入");
  });

  content.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") generate();
  });

  async function uploadFile(file) {
    const form = new FormData();
    form.append("file", file);
    setStatus(`正在解析 ${file.name}...`, "busy");
    try {
      const data = await api("/graphs/parse", { method: "POST", form });
      content.value = data.content;
      parseMeta.textContent = `已解析：${data.source_name || file.name}${previewText(data.preview)}`;
      parseMeta.hidden = false;
      setStatus(`已解析 ${data.source_name || file.name}`);
    } catch (error) {
      toast(error.message, true);
      setStatus("解析失败", "error");
    }
  }

  async function fetchUrl() {
    const url = urlInput.value.trim();
    if (!url) return;
    const form = new FormData();
    form.append("url", url);
    setStatus("正在抓取网页...", "busy");
    try {
      const data = await api("/graphs/parse", { method: "POST", form });
      content.value = data.content;
      parseMeta.textContent = `已抓取：${data.source_name || url}${previewText(data.preview)}`;
      parseMeta.hidden = false;
      setStatus("网页内容已加载");
    } catch (error) {
      toast(error.message, true);
      setStatus("抓取失败", "error");
    }
  }

  function generate() {
    const value = content.value.trim();
    if (!value) {
      toast("请先输入内容", true);
      return;
    }
    emit("generate", {
      content: value,
      output_format: formatSelect.value,
      web_search_enabled: webSearchToggle.checked,
      auto_link: autoLinkToggle.checked,
    });
  }

  function previewText(preview) {
    if (!preview || preview.blocks <= 1) return "";
    return ` · ${(preview.char_count / 10000).toFixed(1)} 万字 · `
      + `${preview.blocks} 块 · 预计 ${preview.estimated_minutes} 分钟 / `
      + `${(preview.estimated_tokens / 10000).toFixed(1)} 万 tokens`;
  }
}
