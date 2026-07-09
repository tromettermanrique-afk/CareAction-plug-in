(function () {
  const STYLE_ID = "careaction-plugin-style";

  function ensureStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      .ca-plugin {
        border: 1px solid #d9e3ef;
        border-radius: 16px;
        background: #ffffff;
        box-shadow: 0 8px 22px rgba(15, 35, 60, 0.06);
        overflow: hidden;
      }
      .ca-plugin__head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        padding: 14px 14px 10px;
        border-bottom: 1px solid #edf2f7;
      }
      .ca-plugin__brand {
        display: flex;
        align-items: center;
        gap: 8px;
        min-width: 0;
        color: #113455;
        font-size: 16px;
        font-weight: 800;
      }
      .ca-plugin__mark {
        display: inline-grid;
        width: 28px;
        height: 28px;
        place-items: center;
        border-radius: 9px;
        background: #113455;
        color: #fff;
        font-size: 13px;
        letter-spacing: 0;
      }
      .ca-plugin__body {
        padding: 14px;
      }
      .ca-plugin__actions {
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
      }
      .ca-plugin button {
        border: 0;
        border-radius: 12px;
        min-height: 42px;
        padding: 0 14px;
        font-size: 15px;
        font-weight: 750;
        cursor: pointer;
      }
      .ca-plugin button:disabled {
        cursor: not-allowed;
        opacity: .65;
      }
      .ca-plugin__primary {
        background: #2f7d5f;
        color: #fff;
      }
      .ca-plugin__ghost {
        background: #eef5f8;
        color: #214866;
      }
      .ca-plugin__danger {
        background: #fff0f0;
        color: #ad303a;
      }
      .ca-plugin__headline {
        margin: 0 0 12px;
        color: #102d4a;
        font-size: 22px;
        line-height: 1.35;
        font-weight: 850;
      }
      .ca-plugin__grid {
        display: grid;
        gap: 10px;
      }
      .ca-plugin__section {
        border-radius: 14px;
        background: #f7fafc;
        padding: 12px;
      }
      .ca-plugin__label {
        margin-bottom: 6px;
        color: #5f7188;
        font-size: 13px;
        font-weight: 800;
      }
      .ca-plugin__text {
        color: #1d3551;
        font-size: 17px;
        line-height: 1.55;
        font-weight: 650;
      }
      .ca-plugin__steps {
        margin: 0;
        padding-left: 22px;
      }
      .ca-plugin__steps li {
        margin: 4px 0;
        color: #1d3551;
        font-size: 17px;
        line-height: 1.5;
        font-weight: 650;
      }
      .ca-plugin__safety {
        background: #fff3f1;
        border-left: 5px solid #d9574f;
      }
      .ca-plugin__meta {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        color: #6b7d92;
        font-size: 13px;
        line-height: 1.4;
      }
      .ca-plugin__evidence {
        margin: 6px 0 0;
        padding-left: 18px;
        color: #52677e;
        font-size: 14px;
        line-height: 1.5;
      }
      .ca-plugin__state {
        color: #52677e;
        font-size: 16px;
        line-height: 1.5;
        font-weight: 650;
      }
      .ca-plugin__error {
        color: #ad303a;
      }
      .ca-plugin__footer {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        margin-top: 12px;
        flex-wrap: wrap;
      }
    `;
    document.head.appendChild(style);
  }

  function apiUrl(apiBase, path) {
    const base = String(apiBase || "").replace(/\/$/, "");
    return `${base}${path}`;
  }

  function requestHeaders(pluginKey) {
    const headers = { "Content-Type": "application/json" };
    if (pluginKey) headers["X-CareAction-Key"] = pluginKey;
    return headers;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  async function postJson(apiBase, path, payload, pluginKey) {
    const response = await fetch(apiUrl(apiBase, path), {
      method: "POST",
      headers: requestHeaders(pluginKey),
      body: JSON.stringify(payload || {}),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.error) {
      throw new Error(data.error || `HTTP ${response.status}`);
    }
    return data;
  }

  function renderShell(root, title, buttonText) {
    root.innerHTML = `
      <section class="ca-plugin">
        <div class="ca-plugin__head">
          <div class="ca-plugin__brand"><span class="ca-plugin__mark">AI</span><span>${escapeHtml(title)}</span></div>
          <button class="ca-plugin__ghost" data-ca-refresh type="button">${escapeHtml(buttonText)}</button>
        </div>
        <div class="ca-plugin__body" data-ca-body>
          <div class="ca-plugin__state">点击后，从数据库读取老人资料和任务记录生成建议。</div>
        </div>
      </section>
    `;
  }

  function renderLoading(root) {
    const body = root.querySelector("[data-ca-body]");
    const refresh = root.querySelector("[data-ca-refresh]");
    if (refresh) refresh.disabled = true;
    body.innerHTML = `<div class="ca-plugin__state">正在连接数据库并生成建议...</div>`;
  }

  function renderError(root) {
    const body = root.querySelector("[data-ca-body]");
    const refresh = root.querySelector("[data-ca-refresh]");
    if (refresh) refresh.disabled = false;
    body.innerHTML = `<div class="ca-plugin__state ca-plugin__error">数据库未连接 / 建议生成失败</div>`;
  }

  function renderSuggestion(root, data, options) {
    const body = root.querySelector("[data-ca-body]");
    const refresh = root.querySelector("[data-ca-refresh]");
    if (refresh) {
      refresh.disabled = false;
      refresh.textContent = "刷新建议";
    }
    const steps = Array.isArray(data.steps) ? data.steps : [];
    const evidence = Array.isArray(data.evidence) ? data.evidence : [];
    body.innerHTML = `
      <p class="ca-plugin__headline">${escapeHtml(data.headline || "当前任务建议")}</p>
      <div class="ca-plugin__grid">
        <div class="ca-plugin__section">
          <div class="ca-plugin__label">先做什么 / 再做什么</div>
          <ol class="ca-plugin__steps">
            ${steps.map((item) => `<li>${escapeHtml(item)}</li>`).join("") || `<li>${escapeHtml(data.headline || "先确认老人状态。")}</li>`}
          </ol>
        </div>
        <div class="ca-plugin__section">
          <div class="ca-plugin__label">怎么说</div>
          <div class="ca-plugin__text">${escapeHtml(data.script || "先说明，再开始。")}</div>
        </div>
        <div class="ca-plugin__section ca-plugin__safety">
          <div class="ca-plugin__label">注意事项</div>
          <div class="ca-plugin__text">${escapeHtml(data.safety || "异常时遵循机构流程。")}</div>
        </div>
        <div class="ca-plugin__section">
          <div class="ca-plugin__label">依据 / 置信度</div>
          <div class="ca-plugin__meta">
            <span>${escapeHtml(data.source_summary || "来自数据库记录")}</span>
            <strong>${escapeHtml(data.confidence ?? "--")}%</strong>
          </div>
          <ul class="ca-plugin__evidence">
            ${evidence.slice(0, 3).map((item) => `<li>${escapeHtml(item.source || "依据")}：${escapeHtml(item.text || "")}</li>`).join("")}
          </ul>
        </div>
      </div>
      <div class="ca-plugin__footer">
        <div class="ca-plugin__actions">
          <button class="ca-plugin__primary" type="button" data-ca-feedback="有效">有效</button>
          <button class="ca-plugin__ghost" type="button" data-ca-feedback="部分有效">部分有效</button>
          <button class="ca-plugin__danger" type="button" data-ca-feedback="无效">无效</button>
        </div>
        <span class="ca-plugin__state">${escapeHtml(data.warning || (data.cached ? "已读取历史建议" : "已生成建议"))}</span>
      </div>
    `;
    body.querySelectorAll("[data-ca-feedback]").forEach((button) => {
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          await postJson(
            options.apiBase,
            "/api/plugin/feedback",
            { task_id: options.taskId, effect: button.dataset.caFeedback, voice_note: "", observations: [] },
            options.pluginKey
          );
          button.textContent = "已记录";
        } catch (error) {
          button.textContent = "失败";
          button.disabled = false;
        }
      });
    });
  }

  function mount(options) {
    if (!options || !options.root) {
      throw new Error("CareActionPlugin.mount requires root");
    }
    if (!options.taskId) {
      throw new Error("CareActionPlugin.mount requires taskId");
    }
    ensureStyles();
    const root = typeof options.root === "string" ? document.querySelector(options.root) : options.root;
    if (!root) throw new Error("CareActionPlugin root not found");
    const apiBase = options.apiBase || window.CAREACTION_API_BASE || window.location.origin;
    const pluginKey = options.pluginKey || window.CAREACTION_PLUGIN_KEY || "";
    const instanceOptions = { ...options, apiBase, pluginKey };
    renderShell(root, options.title || "CareAction 建议", options.hasSuggestion ? "查看建议" : "生成建议");

    async function load(forceRefresh) {
      renderLoading(root);
      try {
        const data = await postJson(
          apiBase,
          "/api/plugin/suggestions",
          {
            task_id: options.taskId,
            staff_level: options.staffLevel || "normal",
            force_refresh: Boolean(forceRefresh),
          },
          pluginKey
        );
        renderSuggestion(root, data, instanceOptions);
      } catch (error) {
        renderError(root);
      }
    }

    root.querySelector("[data-ca-refresh]").addEventListener("click", () => load(true));
    if (options.autoLoad) load(false);
    return {
      refresh: () => load(true),
      load: () => load(false),
      destroy: () => {
        root.innerHTML = "";
      },
    };
  }

  window.CareActionPlugin = { mount };
})();
