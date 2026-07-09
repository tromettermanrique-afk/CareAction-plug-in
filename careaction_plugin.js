(function () {
  const STYLE_ID = "careaction-plugin-style";

  function ensureStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      .ca-plugin {
        border: 1px solid #d9e3ef;
        border-radius: 18px;
        background: #ffffff;
        box-shadow: 0 8px 22px rgba(15, 35, 60, 0.06);
        overflow: hidden;
      }
      .ca-voice {
        display: grid;
        grid-template-columns: 92px 1fr;
        gap: 14px;
        align-items: stretch;
        padding: 16px;
      }
      .ca-voice__play {
        display: grid;
        place-items: center;
        width: 92px;
        min-height: 92px;
        border: 0;
        border-radius: 24px;
        background: #123b63;
        color: #ffffff;
        box-shadow: 0 14px 28px rgba(18, 59, 99, 0.20);
        cursor: pointer;
      }
      .ca-voice__play:disabled {
        opacity: .72;
        cursor: wait;
      }
      .ca-voice__icon {
        display: block;
        font-size: 34px;
        line-height: 1;
      }
      .ca-voice__label {
        display: block;
        margin-top: 8px;
        font-size: 15px;
        font-weight: 900;
        letter-spacing: 0;
      }
      .ca-voice__copy {
        min-width: 0;
        border-radius: 18px;
        background: #f5f9fc;
        padding: 14px 14px 12px;
      }
      .ca-voice__tag {
        display: inline-flex;
        align-items: center;
        min-height: 28px;
        padding: 0 9px;
        border-radius: 999px;
        background: #eaf6ef;
        color: #2f7d5f;
        font-size: 13px;
        font-weight: 900;
      }
      .ca-voice__tag.warn {
        background: #fff1ef;
        color: #b24545;
      }
      .ca-voice__text {
        margin: 9px 0 0;
        color: #132b46;
        font-size: 20px;
        line-height: 1.45;
        font-weight: 850;
      }
      .ca-voice__mini {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        margin-top: 10px;
      }
      .ca-voice__mini button {
        border: 0;
        border-radius: 12px;
        min-height: 36px;
        padding: 0 12px;
        background: #eef5f8;
        color: #214866;
        font-size: 14px;
        font-weight: 850;
        cursor: pointer;
      }
      .ca-voice__mini button.ca-voice__ok {
        background: #eaf6ef;
        color: #2f7d5f;
      }
      .ca-voice__mini button.ca-voice__bad {
        background: #fff1ef;
        color: #b24545;
      }
      .ca-voice__error {
        color: #b24545;
      }
      @media (max-width: 430px) {
        .ca-voice {
          grid-template-columns: 82px 1fr;
          gap: 12px;
          padding: 14px;
        }
        .ca-voice__play {
          width: 82px;
          min-height: 82px;
          border-radius: 22px;
        }
        .ca-voice__text {
          font-size: 18px;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function apiUrl(apiBase, path) {
    return `${String(apiBase || "").replace(/\/$/, "")}${path}`;
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
    if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  function shortText(value, maxLen) {
    const text = String(value || "").replace(/\s+/g, " ").trim().replace(/[。；;，,、\s]+$/g, "");
    if (text.length <= maxLen) return text;
    return text.slice(0, maxLen).replace(/[。；;，,、\s]+$/g, "");
  }

  function firstEvidence(data) {
    const evidence = Array.isArray(data.evidence) ? data.evidence : [];
    const item = evidence.find((entry) => entry && entry.text) || {};
    return shortText(item.text || data.source_summary || "", 34);
  }

  function mainAction(data) {
    const steps = Array.isArray(data.steps) ? data.steps : [];
    return shortText(steps[0] || data.headline || "", 38);
  }

  function safetyLine(data) {
    return shortText(data.safety || "异常时先停下，按机构流程处理。", 42);
  }

  function buildVoiceText(data) {
    const reason = firstEvidence(data);
    const action = mainAction(data);
    const safety = safetyLine(data);
    const parts = [];
    if (reason) parts.push(`提醒：因为${reason}`);
    if (action) parts.push(`大概这样做：${action}`);
    if (safety) parts.push(`注意：${safety}`);
    return parts.join("。");
  }

  function speak(text) {
    if (!("speechSynthesis" in window)) return false;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "zh-CN";
    utterance.rate = 0.92;
    utterance.pitch = 1;
    window.speechSynthesis.speak(utterance);
    return true;
  }

  function renderShell(root, options) {
    root.innerHTML = `
      <section class="ca-plugin">
        <div class="ca-voice">
          <button class="ca-voice__play" data-ca-play type="button">
            <span>
              <span class="ca-voice__icon">▶</span>
              <span class="ca-voice__label">听提醒</span>
            </span>
          </button>
          <div class="ca-voice__copy">
            <span class="ca-voice__tag">AI 语音</span>
            <p class="ca-voice__text" data-ca-text>点一下，听当前任务提醒。</p>
            <div class="ca-voice__mini">
              <button data-ca-refresh type="button">${options.hasSuggestion ? "重听" : "生成"}</button>
            </div>
          </div>
        </div>
      </section>
    `;
  }

  function setBusy(root, busy) {
    const play = root.querySelector("[data-ca-play]");
    const refresh = root.querySelector("[data-ca-refresh]");
    if (play) play.disabled = busy;
    if (refresh) refresh.disabled = busy;
  }

  function setText(root, text, error) {
    const textEl = root.querySelector("[data-ca-text]");
    if (!textEl) return;
    textEl.textContent = text;
    textEl.classList.toggle("ca-voice__error", Boolean(error));
  }

  function renderLoaded(root, data, options) {
    const voiceText = buildVoiceText(data);
    const tag = root.querySelector(".ca-voice__tag");
    const refresh = root.querySelector("[data-ca-refresh]");
    const mini = root.querySelector(".ca-voice__mini");
    if (tag) {
      tag.textContent = data.warning ? "规则兜底" : data.generated_by === "ai" ? "AI 已生成" : "已读取";
      tag.classList.toggle("warn", Boolean(data.warning) || String(data.safety || "").includes("高风险"));
    }
    if (refresh) refresh.textContent = "重听";
    setText(root, voiceText || "这条任务暂无语音提醒。", false);
    if (mini && !mini.querySelector("[data-ca-feedback]")) {
      mini.insertAdjacentHTML(
        "beforeend",
        `
          <button class="ca-voice__ok" data-ca-feedback="有效" type="button">有用</button>
          <button class="ca-voice__bad" data-ca-feedback="无效" type="button">没用</button>
        `
      );
      mini.querySelectorAll("[data-ca-feedback]").forEach((button) => {
        button.addEventListener("click", async () => {
          button.disabled = true;
          try {
            await postJson(
              options.apiBase,
              "/api/plugin/feedback",
              { task_id: options.taskId, effect: button.dataset.caFeedback, voice_note: "", observations: [] },
              options.pluginKey
            );
            button.textContent = "已记";
          } catch (error) {
            button.disabled = false;
            button.textContent = "重试";
          }
        });
      });
    }
    return voiceText;
  }

  function mount(options) {
    if (!options || !options.root) throw new Error("CareActionPlugin.mount requires root");
    if (!options.taskId) throw new Error("CareActionPlugin.mount requires taskId");
    ensureStyles();
    const root = typeof options.root === "string" ? document.querySelector(options.root) : options.root;
    if (!root) throw new Error("CareActionPlugin root not found");
    const apiBase = options.apiBase || window.CAREACTION_API_BASE || window.location.origin;
    const pluginKey = options.pluginKey || window.CAREACTION_PLUGIN_KEY || "";
    const instanceOptions = { ...options, apiBase, pluginKey };
    let cachedData = null;
    let cachedVoice = "";

    renderShell(root, options);

    async function load(forceRefresh, shouldSpeak) {
      setBusy(root, true);
      setText(root, "正在生成语音提醒...", false);
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
        cachedData = data;
        cachedVoice = renderLoaded(root, data, instanceOptions);
        if (shouldSpeak) speak(cachedVoice);
      } catch (error) {
        setText(root, "连接失败，无法生成提醒。", true);
      } finally {
        setBusy(root, false);
      }
    }

    root.querySelector("[data-ca-play]").addEventListener("click", () => {
      if (cachedVoice) {
        speak(cachedVoice);
      } else {
        load(false, true);
      }
    });
    root.querySelector("[data-ca-refresh]").addEventListener("click", () => {
      if (cachedData && cachedVoice) {
        speak(cachedVoice);
      } else {
        load(false, true);
      }
    });
    if (options.autoLoad) load(false, false);
    return {
      refresh: () => load(true, false),
      play: () => (cachedVoice ? speak(cachedVoice) : load(false, true)),
      destroy: () => {
        if ("speechSynthesis" in window) window.speechSynthesis.cancel();
        root.innerHTML = "";
      },
    };
  }

  window.CareActionPlugin = { mount };
})();
