/* Delux M618XSD // Linux Hardware Control Center Frontend Controller */
(function () {
  "use strict";

  const TOKEN = new URLSearchParams(window.location.search).get("token") || "";

  const DEFAULT_SLOT_DESC = {
    forward: "默认：前进 (网页前进 / 文件目录前进)",
    backward: "默认：后退 (网页后退 / 文件目录后退)",
    middle: "默认：中键点击 (后台打开链接 / 关闭标签 / 画布平移)",
    thumb_up: "默认：水平向左滚动 (宽表格 / 代码横向左移)",
    thumb_down: "默认：水平向右滚动 (宽表格 / 代码横向右移)",
  };

  const DEFAULT_SLOT_SHORT = {
    forward: "前进",
    backward: "后退",
    middle: "中键点击",
    thumb_up: "水平向左滚动",
    thumb_down: "水平向右滚动",
  };

  const SLOT_SUBCODE = {
    forward: "LEFT SIDE // BTN_EXTRA",
    backward: "LEFT SIDE // BTN_SIDE",
    middle: "RIGHT WHEEL // BTN_MIDDLE",
    thumb_up: "THUMB WHEEL // UP",
    thumb_down: "THUMB WHEEL // DOWN",
  };

  const GESTURE_DIRS = [
    { key: "tap", code: "TAP", label: "单击松开 (不移动)" },
    { key: "up", code: "UP", label: "按住 + 向上滑鼠标" },
    { key: "down", code: "DOWN", label: "按住 + 向下滑鼠标" },
    { key: "left", code: "LEFT", label: "按住 + 向左滑鼠标" },
    { key: "right", code: "RIGHT", label: "按住 + 向右滑鼠标" },
    { key: "wheel_up", code: "WHL+", label: "按住 + 主滚轮上滚" },
    { key: "wheel_down", code: "WHL-", label: "按住 + 主滚轮下滚", full: true },
  ];

  let APP = {
    hardware: null,
    daemon: null,
    config: null,
    meta: null,
    selectedProfileId: "global",
    gestureHostSlot: "backward",
    editingSlot: null,
    macroStepsDraft: [],
    recordingCombo: false,
    recordingMacro: false,
    discoverableApps: { running: [], installed: [] },
    viewer3d: null,
  };

  async function apiGet(path) {
    const res = await fetch(path, {
      headers: { "X-Studio-Token": TOKEN },
    });
    return res.json();
  }

  async function apiPost(path, body) {
    const res = await fetch(path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Studio-Token": TOKEN,
      },
      body: JSON.stringify(body || {}),
    });
    return res.json();
  }

  let toastTimer = null;
  function showToast(msg, isError = false) {
    const el = document.getElementById("cyber-toast");
    if (!el) return;
    el.textContent = msg;
    el.style.borderColor = isError ? "var(--accent-danger)" : "var(--accent-cyan)";
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function rgbToHex(rgb) {
    if (!Array.isArray(rgb) || rgb.length < 3) return "#00e5ff";
    return (
      "#" +
      rgb
        .slice(0, 3)
        .map((x) => Math.max(0, Math.min(255, Math.round(x))).toString(16).padStart(2, "0"))
        .join("")
    );
  }

  function hexToRgb(hex) {
    const clean = (hex || "#00e5ff").replace("#", "");
    if (clean.length !== 6) return [0, 229, 255];
    return [
      parseInt(clean.slice(0, 2), 16),
      parseInt(clean.slice(2, 4), 16),
      parseInt(clean.slice(4, 6), 16),
    ];
  }

  function summarizeSpec(spec, slotKey) {
    if (!spec || !spec.kind || spec.kind === "passthrough") {
      return DEFAULT_SLOT_DESC[slotKey] || "默认：保持鼠标硬件原厂动作";
    }
    if (spec.kind === "disabled") return "已禁用该输入";
    if (spec.kind === "key_combo") return "快捷键: " + (spec.combo || "");
    if (spec.kind === "media") {
      const m = {
        VOLUMEUP: "系统音量增加 (Volume +)",
        VOLUMEDOWN: "系统音量减小 (Volume -)",
        MUTE: "系统静音切换",
        PLAYPAUSE: "媒体播放 / 暂停",
        NEXTSONG: "下一曲",
        PREVIOUSSONG: "上一曲",
      };
      return m[spec.media] || "媒体键: " + spec.media;
    }
    if (spec.kind === "zoom") {
      const dir = (spec.direction || 1) > 0 ? "放大" : "缩小";
      const mode = spec.zoom_mode || "auto";
      if (mode === "keys") return `键盘缩放：画面${dir} (Ctrl+${(spec.direction || 1) > 0 ? "=" : "-"})`;
      if (mode === "wheel") return `滚轮缩放：画面${dir} (Ctrl+滚轮)`;
      return `智能画面${dir} (自动适配图片/PDF/WPS/浏览器)`;
    }
    if (spec.kind === "scroll") {
      return `${spec.axis === "h" ? "水平横向" : "垂直纵向"}滚动 (${spec.step > 0 ? "+" : ""}${spec.step || 1})`;
    }
    if (spec.kind === "sniper_dpi") return `按住降速微操 (${Number(spec.scale || 0.4).toFixed(2)}x 速度)`;
    if (spec.kind === "command") return `执行命令: ${spec.command || ""}`;
    if (spec.kind === "macro") {
      const steps = spec.macro_steps || [];
      const prev = steps.slice(0, 3).map((s) => s.combo).filter(Boolean).join(" -> ");
      return `多步宏序列 (${steps.length} 步${prev ? ": " + prev : ""})`;
    }
    if (spec.kind === "gesture_4way") {
      const tapShort =
        !spec.tap || spec.tap.kind === "passthrough"
          ? DEFAULT_SLOT_SHORT[slotKey] || "原厂默认"
          : summarizeSpec(spec.tap, slotKey);
      return `四向滑动手势 + 主滚轮弦 [单击: ${tapShort} | 按住上/下/左/右滑已启用]`;
    }
    return spec.kind;
  }

  function defaultGestureSpec() {
    return {
      kind: "gesture_4way",
      gesture_threshold: 45,
      tap: { kind: "passthrough" },
      up: { kind: "key_combo", combo: "Super" },
      down: { kind: "key_combo", combo: "Super+H" },
      left: { kind: "key_combo", combo: "Super+PageUp" },
      right: { kind: "key_combo", combo: "Super+PageDown" },
      wheel_up: { kind: "media", media: "VOLUMEUP" },
      wheel_down: { kind: "media", media: "VOLUMEDOWN" },
    };
  }

  function switchPane(paneId) {
    document.querySelectorAll("#left-nav .nav-item").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.pane === paneId);
    });
    document.querySelectorAll(".view-pane").forEach((sec) => {
      sec.classList.toggle("active", sec.id === "pane-" + paneId);
    });
  }

  function activeDpiValue(hw) {
    if (!hw || !hw.dpi || !Array.isArray(hw.dpi.stages)) return 1200;
    const idx = Math.max(0, Math.min(4, (hw.dpi.current_stage || 1) - 1));
    return (hw.dpi.stages[idx] && hw.dpi.stages[idx].dpi) || 1200;
  }

  function sync3DModel() {
    if (!APP.viewer3d || !APP.hardware) return;
    const hw = APP.hardware;
    const lt = hw.lighting || {};
    const dpiObj = hw.dpi || {};
    let rgbNorm = [0.0, 0.9, 1.0];
    if (Array.isArray(lt.rgb)) {
      rgbNorm = [lt.rgb[0] / 255, lt.rgb[1] / 255, lt.rgb[2] / 255];
    }
    if ((lt.mode === 5 || lt.mode === 6) && Array.isArray(dpiObj.stages)) {
      const st = dpiObj.stages[Math.max(0, (dpiObj.current_stage || 1) - 1)];
      if (st && Array.isArray(st.rgb)) {
        rgbNorm = [st.rgb[0] / 255, st.rgb[1] / 255, st.rgb[2] / 255];
      }
    }
    const rawBat = hw.battery && typeof hw.battery.percent === "number" ? hw.battery.percent : null;
    APP.viewer3d.updateTelemetry({
      dpi: activeDpiValue(hw),
      hz: (hw.polling && hw.polling.hz) || 250,
      battery: rawBat,
      rgbMode: lt.mode !== undefined ? lt.mode : 8,
      rgbColor: rgbNorm,
      rgbBright: (lt.brightness !== undefined ? lt.brightness : 8) / 8.0,
      rgbSpeed: lt.led_speed || 3,
    });
  }

  // =========================================================================
  // TOP TELEMETRY STRIP, SIDEBAR ROUTER & MODULE 01 OVERVIEW
  // =========================================================================
  function renderTelemetryAndOverview() {
    const hw = APP.hardware || {};
    const dm = APP.daemon || {};
    const cfg = APP.config || {};

    const connected = !!hw.connected;
    const curDpi = activeDpiValue(hw);
    const curHz = (hw.polling && hw.polling.hz) || 250;
    const lt = hw.lighting || {};
    const batObj = hw.battery || {};
    const hasBat = typeof batObj.percent === "number";
    const batPct = hasBat ? Math.max(0, Math.min(100, Math.round(batObj.percent))) : null;

    document.getElementById("hud-hw-dot").classList.toggle("offline", !connected);
    document.getElementById("hud-conn-text").textContent = connected
      ? `M618XSD 在线 (${hw.node || "2.4G"})`
      : "硬件未连接或待机";
    document.getElementById("hud-dpi-text").textContent = `${curDpi} DPI`;
    document.getElementById("hud-hz-text").textContent = `${curHz} Hz`;
    document.getElementById("hud-bat-text").textContent = hasBat ? `${batPct}%` : "读取中";
    document.getElementById("hud-fw-text").textContent = hw.firmware || "--";

    // Daemon status
    const daemonOk = !!(dm.ok && dm.grabbed);
    const dBtn = document.getElementById("btn-restart-daemon");
    dBtn.textContent = daemonOk ? "守护进程运行中" : "启动守护进程";
    document.getElementById("sidebar-daemon-dot").classList.toggle("offline", !daemonOk);

    const winLabel = (dm.window && dm.window.label) || "桌面环境";
    const activeProfName = (dm.active_profile && dm.active_profile.name) || "全局默认配置";
    const activeProfId = (dm.active_profile && dm.active_profile.id) || "global";

    document.getElementById("sidebar-win-label").textContent = winLabel;
    document.getElementById("sidebar-prof-name").textContent = activeProfName.split(" (")[0];
    document.getElementById("ov-win-label").textContent = winLabel;
    document.getElementById("ov-prof-badge").textContent =
      cfg.per_app_enabled !== false
        ? `当前生效: ${activeProfName.split(" (")[0]}`
        : "已锁定全局方案";

    // Synchronize Per-App switches
    const perApp = cfg.per_app_enabled !== false;
    ["chk-perapp-sidebar", "chk-perapp-overview", "chk-perapp-main"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.checked = perApp;
    });
    const dmChk = document.getElementById("chk-daemon-enabled");
    if (dmChk) dmChk.checked = cfg.daemon_enabled !== false;

    // Prominent Overview Battery Panel
    const batBigEl = document.getElementById("ov-bat-big");
    const batStateEl = document.getElementById("ov-bat-state");
    const batCardEl = document.getElementById("ov-bat-card");
    if (hasBat) {
      batBigEl.innerHTML = `${batPct}<small>%</small>`;
      batStateEl.textContent = `${batObj.state_label || "电池供电中"}${batObj.charging ? " · USB 充电输入" : " · 2.4G 无线通道"}`;
      const colorVar =
        batPct <= 15
          ? "var(--accent-danger)"
          : batPct <= 28
          ? "var(--accent-amber)"
          : "var(--accent-emerald)";
      batBigEl.style.color = colorVar;
      batCardEl.style.borderLeftColor = colorVar;
    } else {
      batBigEl.innerHTML = `--<small>%</small>`;
      batStateEl.textContent = connected ? "正在读取电池状态..." : "等待鼠标唤醒响应";
    }

    const segs = document.querySelectorAll("#ov-bat-segments .bat-seg");
    const litCount = hasBat ? Math.max(1, Math.round(batPct / 10)) : 0;
    segs.forEach((seg, idx) => {
      seg.className = "bat-seg";
      if (hasBat && idx < litCount) {
        seg.classList.add("lit");
        if (batPct <= 15) seg.classList.add("low");
        else if (batPct <= 28) seg.classList.add("warn");
      }
    });

    document.getElementById("ov-node-path").textContent = hw.sleeping
      ? `节点: ${hw.node || "/dev/hidraw5"} · 无线休眠中 (移动鼠标自动唤醒)`
      : hw.error
      ? `状态提示: ${hw.error}`
      : `设备节点: ${hw.node || "/dev/hidraw5"} · 固件 ${hw.firmware || "--"}`;
    document.getElementById("ov-sleep-sub").textContent = `浅眠 ${lt.light_sleep_minutes || 0.5}m / 深眠 ${lt.deep_sleep_minutes || 10}m`;

    // Overview 3 Hardware Metric Boxes
    document.getElementById("ov-dpi-big").innerHTML = `${curDpi} <span>DPI</span>`;
    document.getElementById("ov-dpi-stage").textContent = `第 ${(hw.dpi && hw.dpi.current_stage) || 1} 档 · 点击设置`;
    document.getElementById("ov-hz-big").innerHTML = `${curHz} <span>Hz</span>`;
    document.getElementById("ov-hz-ms").textContent = `${(1000 / curHz).toFixed(1)} ms 传输周期`;
    document.getElementById("ov-rgb-mode").textContent = lt.mode_label || "流光溢彩";
    document.getElementById("ov-rgb-sub").textContent = `亮度 ${lt.brightness || 8}/8 · 速度 ${lt.led_speed || 3}/5`;

    // Overview Profile Routing Table
    const sumBox = document.getElementById("ov-rules-summary");
    if (sumBox && Array.isArray(cfg.profiles)) {
      sumBox.innerHTML = cfg.profiles
        .filter((p) => p.enabled || p.is_global)
        .slice(0, 6)
        .map((p) => {
          const matched = p.id === activeProfId;
          const twUp = p.bindings && p.bindings.thumb_up;
          const twText =
            !twUp || twUp.kind === "passthrough"
              ? "水平横向滚动"
              : summarizeSpec(twUp, "thumb_up")
                  .replace("快捷键: ", "")
                  .replace(" (自动适配图片/PDF/WPS/浏览器)", "");
          return `<div class="ov-prof-row ${matched ? "matched" : ""}">
            <strong style="color:${matched ? "#ffffff" : "var(--text-main)"};">${escapeHtml(p.name.split(" (")[0])}</strong>
            <span style="color:var(--text-sec);">拇指轮: ${escapeHtml(twText)}</span>
          </div>`;
        })
        .join("");
    }

    // Module 05 Live Terminal Logs
    const pidBadge = document.getElementById("term-pid-badge");
    if (pidBadge) pidBadge.textContent = dm.pid ? `PID ${dm.pid} // GRABBED` : "OFFLINE";
    const logBox = document.getElementById("daemon-log-box");
    if (logBox && Array.isArray(dm.logs)) {
      logBox.innerHTML = dm.logs.length
        ? dm.logs.map((l) => `<div>${escapeHtml(l)}</div>`).join("")
        : "<div>守护进程已就绪，等待按键、滚轮或焦点切换事件...</div>";
    }

    sync3DModel();
  }

  // =========================================================================
  // MODULE 02: PER-APP PROFILES, BINDINGS & INLINE LOGITECH GESTURE MATRIX
  // =========================================================================
  function getSelectedProfile() {
    if (!APP.config || !Array.isArray(APP.config.profiles)) return null;
    return (
      APP.config.profiles.find((p) => p.id === APP.selectedProfileId) || APP.config.profiles[0]
    );
  }

  async function persistConfig(toastText) {
    const res = await apiPost("/api/config/save", APP.config);
    if (res.ok) {
      APP.config = res.config;
      APP.daemon = res.daemon;
      renderBindingsPane();
      renderTelemetryAndOverview();
      if (toastText) showToast(toastText);
    } else {
      showToast("保存配置失败: " + (res.error || ""), true);
    }
  }

  function detectActiveThumbScenario(prof) {
    if (!prof || !prof.bindings) return "";
    const u = prof.bindings.thumb_up || { kind: "passthrough" };
    const d = prof.bindings.thumb_down || { kind: "passthrough" };
    if (u.kind === "passthrough" && d.kind === "passthrough") return "hscroll";
    if (u.kind === "zoom" && d.kind === "zoom") return "zoom";
    if (u.kind === "media" && u.media === "VOLUMEUP") return "volume";
    if (u.kind === "key_combo" && u.combo === "Ctrl+Shift+Tab") return "tabs";
    if (u.kind === "key_combo" && u.combo === "Left") return "timeline";
    if (u.kind === "key_combo" && u.combo === "Super+PageUp") return "workspace";
    return "";
  }

  function buildPresetOptionsHtml(slotKey, selectedId) {
    const presets = (APP.meta && APP.meta.action_presets) || [];
    return presets
      .map((p) => {
        const label =
          p.id === "passthrough"
            ? DEFAULT_SLOT_DESC[slotKey] || "保持原厂默认功能"
            : p.label;
        const sel = p.id === selectedId ? "selected" : "";
        return `<option value="${escapeHtml(p.id)}" ${sel}>${escapeHtml(label)}</option>`;
      })
      .join("");
  }

  function findPresetIdForSpec(spec) {
    if (!spec || !spec.kind || spec.kind === "passthrough") return "passthrough";
    if (!APP.meta) return null;
    const sJson = JSON.stringify(spec);
    for (const p of APP.meta.action_presets || []) {
      if (JSON.stringify(p.spec) === sJson) return p.id;
    }
    return null;
  }

  function presetSpecById(id) {
    const presets = (APP.meta && APP.meta.action_presets) || [];
    const found = presets.find((p) => p.id === id);
    return found ? JSON.parse(JSON.stringify(found.spec)) : { kind: "passthrough" };
  }

  function renderInlineGestureMatrix(prof) {
    const hostSel = document.getElementById("sel-gesture-host");
    const toggleBtn = document.getElementById("btn-toggle-gesture-host");
    const bodyBox = document.getElementById("inline-gesture-body");
    if (!hostSel || !toggleBtn || !bodyBox || !prof) return;

    hostSel.value = APP.gestureHostSlot;
    const hostSlot = APP.gestureHostSlot;
    const spec = (prof.bindings && prof.bindings[hostSlot]) || { kind: "passthrough" };
    const isGesture = spec.kind === "gesture_4way";

    toggleBtn.textContent = isGesture ? "关闭该键四向手势" : "开启该键四向手势";
    toggleBtn.classList.toggle("primary", !isGesture);

    if (!isGesture) {
      const curDesc = summarizeSpec(spec, hostSlot);
      bodyBox.innerHTML = `
        <div style="padding:10px 12px;background:var(--bg-panel);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);color:var(--text-sec);font-size:12px;">
          当前按键状态：<strong style="color:#ffffff;">${escapeHtml(curDesc)}</strong>。
          点击右上角「开启该键四向手势」即可保留轻按原功能，同时激活「按住 + 上/下/左/右移动鼠标」与「按住 + 主滚轮上/下」共 6 个快捷手势。
        </div>
      `;
      return;
    }

    bodyBox.innerHTML = `
      <div class="gesture-matrix-grid">
        ${GESTURE_DIRS.map((g) => {
          const subSpec = spec[g.key] || { kind: "passthrough" };
          const pid = findPresetIdForSpec(subSpec) || "passthrough";
          return `
            <div class="gesture-cell ${g.full ? "full-span" : ""}">
              <span class="gesture-dir-tag"><code>${g.code}</code>${escapeHtml(g.label)}</span>
              <select class="cyber-select inline-gest-sel" data-gsub="${g.key}">
                ${buildPresetOptionsHtml(hostSlot, pid)}
              </select>
            </div>
          `;
        }).join("")}
      </div>
    `;

    bodyBox.querySelectorAll(".inline-gest-sel").forEach((sel) => {
      sel.addEventListener("change", (e) => {
        const gsub = e.target.dataset.gsub;
        spec[gsub] = presetSpecById(e.target.value);
        prof.bindings[hostSlot] = spec;
        persistConfig("四向手势动作已更新并生效");
      });
    });
  }

  function renderBindingsPane() {
    if (!APP.config) return;
    const listBox = document.getElementById("profile-list-box");
    const activeId = (APP.daemon && APP.daemon.active_profile && APP.daemon.active_profile.id) || "";

    listBox.innerHTML = "";
    for (const prof of APP.config.profiles) {
      const card = document.createElement("div");
      card.className = "profile-card" + (prof.id === APP.selectedProfileId ? " selected" : "");
      const liveTag = prof.id === activeId ? `<span class="prof-tag live">生效中</span>` : "";
      const tagsHtml = prof.is_global
        ? `<span class="prof-tag">全局默认兜底</span>`
        : (prof.match_patterns || [])
            .slice(0, 5)
            .map((t) => `<span class="prof-tag">${escapeHtml(t)}</span>`)
            .join("");

      card.innerHTML = `
        <div class="prof-top">
          <strong>${escapeHtml(prof.name.split(" (")[0])}</strong>
          ${
            prof.is_global
              ? liveTag
              : `<label class="hw-switch" onclick="event.stopPropagation()">
                   <input type="checkbox" data-prof-toggle="${escapeHtml(prof.id)}" ${
                  prof.enabled ? "checked" : ""
                } />
                   <span class="switch-track"></span>
                 </label>`
          }
        </div>
        <div class="prof-tags">${prof.is_global ? "" : liveTag}${tagsHtml}</div>
      `;
      card.addEventListener("click", () => {
        APP.selectedProfileId = prof.id;
        // Auto-select whichever slot has gesture_4way on this profile
        for (const cand of ["backward", "forward", "middle"]) {
          if (prof.bindings && prof.bindings[cand] && prof.bindings[cand].kind === "gesture_4way") {
            APP.gestureHostSlot = cand;
            break;
          }
        }
        renderBindingsPane();
      });
      listBox.appendChild(card);
    }

    listBox.querySelectorAll("input[data-prof-toggle]").forEach((chk) => {
      chk.addEventListener("change", (e) => {
        const pid = e.target.dataset.profToggle;
        const target = APP.config.profiles.find((p) => p.id === pid);
        if (target) {
          target.enabled = e.target.checked;
          persistConfig(`已${target.enabled ? "启用" : "停用"}方案：${target.name.split(" (")[0]}`);
        }
      });
    });

    const prof = getSelectedProfile();
    if (!prof) return;

    document.getElementById("ed-prof-title").textContent = prof.name;
    document.getElementById("ed-match-section").style.display = prof.is_global ? "none" : "grid";
    document.getElementById("btn-del-profile").style.display = prof.is_global ? "none" : "inline-flex";

    if (!prof.is_global) {
      document.getElementById("inp-prof-name").value = prof.name;
      document.getElementById("inp-prof-patterns").value = (prof.match_patterns || []).join(", ");
    }

    // Highlight active thumbwheel preset
    const activeTw = detectActiveThumbScenario(prof);
    document.querySelectorAll("#scenario-grid-box .scenario-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tw === activeTw);
    });

    // Render 5 bindable physical slots with explicit default descriptions
    const slotBox = document.getElementById("slot-rows-box");
    slotBox.innerHTML = "";
    const inputs = (APP.meta && APP.meta.bindable_inputs) || {
      forward: "前进侧键 (Forward)",
      backward: "后退侧键 (Backward)",
      middle: "滚轮中键 (Middle Click)",
      thumb_up: "拇指侧滚轮 · 上拨",
      thumb_down: "拇指侧滚轮 · 下拨",
    };

    Object.entries(inputs).forEach(([slotKey, slotLabel]) => {
      const spec = (prof.bindings && prof.bindings[slotKey]) || { kind: "passthrough" };
      const isCustom = spec.kind && spec.kind !== "passthrough";
      const row = document.createElement("div");
      row.className = "slot-row";
      row.innerHTML = `
        <div class="slot-name">
          ${escapeHtml(slotLabel)}
          <small>${SLOT_SUBCODE[slotKey] || slotKey.toUpperCase()}</small>
        </div>
        <div class="slot-desc ${isCustom ? "customized" : ""}">${escapeHtml(summarizeSpec(spec, slotKey))}</div>
        <div style="display:flex;gap:6px;">
          <button type="button" class="hw-btn sm primary" data-edit-slot="${slotKey}">编辑动作 / 宏</button>
          <button type="button" class="hw-btn sm" data-reset-slot="${slotKey}">恢复默认</button>
        </div>
      `;
      slotBox.appendChild(row);
    });

    slotBox.querySelectorAll("button[data-edit-slot]").forEach((btn) => {
      btn.addEventListener("click", () => openActionModal(btn.dataset.editSlot));
    });
    slotBox.querySelectorAll("button[data-reset-slot]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const sk = btn.dataset.resetSlot;
        prof.bindings[sk] = { kind: "passthrough" };
        persistConfig(`已恢复为 ${DEFAULT_SLOT_DESC[sk] || "原厂默认功能"}`);
      });
    });

    // Inline Logitech-Style Hold + Slide Gesture Matrix
    renderInlineGestureMatrix(prof);

    // Sliders & checkboxes
    document.getElementById("rng-ptr-scale").value = prof.pointer_scale || 1.0;
    document.getElementById("lbl-ptr-scale").textContent = Number(prof.pointer_scale || 1.0).toFixed(2) + "x";
    document.getElementById("rng-thumb-spd").value = prof.thumb_speed || 1.5;
    document.getElementById("lbl-thumb-spd").textContent = Number(prof.thumb_speed || 1.5).toFixed(2) + "x";
    document.getElementById("chk-thumb-inv").checked = !!prof.thumb_invert;
    document.getElementById("chk-wheel-inv").checked = !!prof.wheel_invert;
  }

  // =========================================================================
  // MODULE 03: SENSOR DPI STAGES, POLLING HZ & DEBOUNCE
  // =========================================================================
  function renderDpiAndPollingPane() {
    if (!APP.hardware) return;
    const dpiObj = APP.hardware.dpi || { current_stage: 2, stages: [] };
    const box = document.getElementById("dpi-stages-box");
    box.innerHTML = "";

    (dpiObj.stages || []).forEach((st) => {
      const isCur = st.stage === dpiObj.current_stage;
      const pct = Math.round(((st.dpi - 400) / (4000 - 400)) * 100);
      const hex = rgbToHex(st.rgb);
      const card = document.createElement("div");
      card.className =
        "dpi-col-card" + (isCur ? " current" : "") + (!st.enabled ? " disabled-stage" : "");
      card.innerHTML = `
        <div style="display:flex;justify-content:space-between;width:100%;align-items:center;">
          <span style="font-family:var(--font-mono);font-size:11px;font-weight:700;color:var(--accent-cyan);">STAGE 0${st.stage}</span>
          <input type="checkbox" class="dpi-en-chk" data-stage="${st.stage}" ${st.enabled ? "checked" : ""} title="启用或禁用此档位" />
        </div>
        <div class="dpi-val-big" id="dpi-lbl-${st.stage}">${st.dpi}</div>
        <div class="dpi-bar-meter"><div class="dpi-bar-fill" id="dpi-fill-${st.stage}" style="width:${Math.max(4, pct)}%;background:${hex};"></div></div>
        <input type="range" class="hw-range dpi-rng" data-stage="${st.stage}" min="400" max="4000" step="50" value="${st.dpi}" />
        <div style="display:flex;justify-content:space-between;width:100%;align-items:center;margin-top:4px;">
          <input type="color" class="dpi-col-inp" data-stage="${st.stage}" value="${hex}" style="width:30px;height:24px;border:1px solid var(--border-std);background:transparent;cursor:pointer;" title="档位指示灯颜色" />
          <button type="button" class="hw-btn sm ${isCur ? "primary" : ""}" data-activate-stage="${st.stage}">
            ${isCur ? "当前档位" : "激活此档"}
          </button>
        </div>
      `;
      box.appendChild(card);
    });

    box.querySelectorAll(".dpi-rng").forEach((rng) => {
      rng.addEventListener("input", (e) => {
        const s = Number(e.target.dataset.stage);
        const val = Number(e.target.value);
        const target = APP.hardware.dpi.stages.find((x) => x.stage === s);
        if (target) target.dpi = val;
        document.getElementById(`dpi-lbl-${s}`).textContent = val;
        document.getElementById(`dpi-fill-${s}`).style.width =
          Math.max(4, Math.round(((val - 400) / 3600) * 100)) + "%";
        sync3DModel();
      });
    });

    box.querySelectorAll(".dpi-col-inp").forEach((inp) => {
      inp.addEventListener("input", (e) => {
        const s = Number(e.target.dataset.stage);
        const target = APP.hardware.dpi.stages.find((x) => x.stage === s);
        if (target) target.rgb = hexToRgb(e.target.value);
        document.getElementById(`dpi-fill-${s}`).style.background = e.target.value;
        sync3DModel();
      });
    });

    box.querySelectorAll(".dpi-en-chk").forEach((chk) => {
      chk.addEventListener("change", (e) => {
        const s = Number(e.target.dataset.stage);
        const target = APP.hardware.dpi.stages.find((x) => x.stage === s);
        if (target) target.enabled = e.target.checked;
        renderDpiAndPollingPane();
      });
    });

    box.querySelectorAll("button[data-activate-stage]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const s = Number(btn.dataset.activateStage);
        APP.hardware.dpi.current_stage = s;
        const target = APP.hardware.dpi.stages.find((x) => x.stage === s);
        if (target) target.enabled = true;
        renderDpiAndPollingPane();
        await writeDpiNow();
      });
    });

    const curHz = (APP.hardware.polling && APP.hardware.polling.hz) || 250;
    document.querySelectorAll("#hz-cards-box .hz-card").forEach((c) => {
      c.classList.toggle("active", Number(c.dataset.hz) === curHz);
    });

    const deb = (APP.hardware.lighting && APP.hardware.lighting.debounce_ms) || 8;
    document.getElementById("rng-debounce-ms").value = deb;
    document.getElementById("lbl-debounce-ms").textContent = `${deb} ms`;
  }

  async function writeDpiNow() {
    const res = await apiPost("/api/hardware/dpi", APP.hardware.dpi);
    if (res.ok) {
      APP.hardware.dpi = res.dpi;
      renderDpiAndPollingPane();
      renderTelemetryAndOverview();
      showToast(`传感器 DPI 已更新 (当前: ${activeDpiValue(APP.hardware)} DPI)`);
    } else {
      showToast("写入 DPI 失败: " + (res.error || ""), true);
    }
  }

  // =========================================================================
  // MODULE 04: HONEYCOMB RGB & SLEEP
  // =========================================================================
  function renderRgbPane() {
    if (!APP.hardware || !APP.meta) return;
    const lt = APP.hardware.lighting || {};
    const modesBox = document.getElementById("rgb-modes-box");
    modesBox.innerHTML = "";

    (APP.meta.light_modes || []).forEach((m) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "rgb-mode-card" + (lt.mode === m.code ? " active" : "");
      card.innerHTML = `
        <strong style="display:block;color:#ffffff;font-size:12.5px;">${escapeHtml(m.label)}</strong>
        <span style="display:block;margin-top:4px;font-family:var(--font-mono);font-size:10px;color:var(--accent-cyan);">MODE 0x0${m.code} // ${m.key.toUpperCase()}</span>
      `;
      card.addEventListener("click", async () => {
        APP.hardware.lighting.mode = m.code;
        APP.hardware.lighting.mode_label = m.label;
        renderRgbPane();
        sync3DModel();
        const res = await apiPost("/api/hardware/lighting", { mode: m.code });
        if (res.ok) {
          APP.hardware.lighting = res.lighting;
          renderTelemetryAndOverview();
          showToast(`尾部背光已切换为：${m.label}`);
        } else {
          showToast("切换灯光失败: " + (res.error || ""), true);
        }
      });
      modesBox.appendChild(card);
    });

    document.getElementById("inp-rgb-color").value = rgbToHex(lt.rgb || [0, 229, 255]);
    document.getElementById("rng-rgb-bright").value = lt.brightness || 8;
    document.getElementById("lbl-rgb-bright").textContent = `${lt.brightness || 8} / 8`;
    document.getElementById("rng-rgb-speed").value = lt.led_speed || 3;
    document.getElementById("lbl-rgb-speed").textContent = `${lt.led_speed || 3} / 5`;
    document.getElementById("rng-light-sleep").value = lt.light_sleep_minutes || 0.5;
    document.getElementById("lbl-light-sleep").textContent = `${lt.light_sleep_minutes || 0.5} 分钟`;
    document.getElementById("rng-deep-sleep").value = lt.deep_sleep_minutes || 10;
    document.getElementById("lbl-deep-sleep").textContent = `${lt.deep_sleep_minutes || 10} 分钟`;
  }

  // =========================================================================
  // MODULE 05: ONBOARD FLASH REGISTER MAP
  // =========================================================================
  function renderOnboardPane() {
    if (!APP.hardware || !APP.meta) return;
    const profCur = (APP.hardware.profile_settings && APP.hardware.profile_settings.current) || 1;
    document.getElementById("sel-onboard-prof").value = String(profCur);

    const tbody = document.getElementById("onboard-tbody");
    tbody.innerHTML = "";
    const slots = (APP.hardware.buttons && APP.hardware.buttons.slots) || [];
    const fwActions = APP.meta.firmware_actions || [];

    slots.forEach((sl) => {
      const tr = document.createElement("tr");
      const opts = fwActions
        .map(
          (a) =>
            `<option value="${escapeHtml(a.key)}" ${a.key === sl.action_key ? "selected" : ""}>${escapeHtml(
              a.label
            )}</option>`
        )
        .join("");
      const lockLeft = sl.slot === 1 ? "disabled title='主左键硬件锁定保护'" : "";
      tr.innerHTML = `
        <td style="font-family:var(--font-mono);color:var(--accent-cyan);">#${String(sl.slot).padStart(2, "0")}</td>
        <td><strong style="color:#ffffff;">${escapeHtml(sl.label)}</strong></td>
        <td><select class="cyber-select ob-act-sel" data-slot="${sl.slot}" style="width:100%;min-width:210px;" ${lockLeft}>${opts}</select></td>
        <td><input type="text" class="hw-input ob-combo-inp" data-slot="${sl.slot}" value="${escapeHtml(
        sl.combo || ""
      )}" placeholder="如 Ctrl+C" style="width:128px;${
        sl.action_key === "keyboard-key" ? "" : "opacity:0.42;"
      }" /></td>
      `;
      tbody.appendChild(tr);
    });

    tbody.querySelectorAll(".ob-act-sel").forEach((sel) => {
      sel.addEventListener("change", (e) => {
        const s = e.target.dataset.slot;
        const inp = tbody.querySelector(`.ob-combo-inp[data-slot="${s}"]`);
        if (inp) inp.style.opacity = e.target.value === "keyboard-key" ? "1" : "0.42";
      });
    });
  }

  // =========================================================================
  // 1-CLICK APPLICATION SELECTOR MODAL (REPLACES 3-SECOND COUNTDOWN)
  // =========================================================================
  async function openAppPickerModal() {
    document.getElementById("app-picker-modal").classList.add("open");
    document.getElementById("inp-app-search").value = "";
    await refreshAppPickerList();
  }

  async function refreshAppPickerList() {
    const runBox = document.getElementById("app-running-list");
    const instBox = document.getElementById("app-installed-list");
    runBox.innerHTML = `<div style="color:var(--text-muted);font-size:12px;">正在扫描活动窗口...</div>`;
    const res = await apiGet("/api/apps");
    if (res && res.ok) {
      APP.discoverableApps = {
        running: res.running || [],
        installed: res.installed || [],
      };
    }
    renderAppPickerItems("");
    if (instBox) instBox.scrollTop = 0;
  }

  function renderAppPickerItems(filterText) {
    const q = (filterText || "").trim().toLowerCase();
    const runBox = document.getElementById("app-running-list");
    const instBox = document.getElementById("app-installed-list");

    const running = APP.discoverableApps.running || [];
    if (!running.length) {
      runBox.innerHTML = `<div style="color:var(--text-muted);font-size:12px;grid-column:span 2;">当前未检测到第三方桌面窗口，可直接从下方已安装软件中选择。</div>`;
    } else {
      runBox.innerHTML = running
        .map(
          (a) => `
          <button type="button" class="app-pick-item" data-pick-name="${escapeHtml(a.name)}" data-pick-pat="${escapeHtml(a.pattern)}">
            <strong>${escapeHtml(a.name)}</strong>
            <code>${escapeHtml(a.pattern)}</code>
          </button>`
        )
        .join("");
    }

    const installed = (APP.discoverableApps.installed || []).filter(
      (a) => !q || a.name.toLowerCase().includes(q) || a.pattern.toLowerCase().includes(q)
    );
    instBox.innerHTML = installed.length
      ? installed
          .map(
            (a) => `
            <button type="button" class="app-pick-item" data-pick-name="${escapeHtml(a.name)}" data-pick-pat="${escapeHtml(a.pattern)}">
              <strong>${escapeHtml(a.name)}</strong>
              <code>${escapeHtml(a.pattern)}</code>
            </button>`
          )
          .join("")
      : `<div style="color:var(--text-muted);font-size:12px;grid-column:span 2;">无匹配软件，可手动新建方案并输入进程名。</div>`;

    document.querySelectorAll("#app-picker-modal .app-pick-item").forEach((btn) => {
      btn.addEventListener("click", () => {
        selectAppForProfile(btn.dataset.pickName, btn.dataset.pickPat);
      });
    });
  }

  async function selectAppForProfile(appName, pattern) {
    document.getElementById("app-picker-modal").classList.remove("open");
    switchPane("bindings");
    const pat = (pattern || "").trim().toLowerCase();
    if (!pat) return;

    const existing = APP.config.profiles.find(
      (p) =>
        !p.is_global &&
        (p.match_patterns || []).some((m) => m.toLowerCase() === pat)
    );
    if (existing) {
      APP.selectedProfileId = existing.id;
      existing.enabled = true;
      APP.config.per_app_enabled = true;
      await persistConfig(`已定位并启用方案：${existing.name.split(" (")[0]} (${pat})`);
      return;
    }

    const isBrowser = /(chrome|chromium|firefox|edge|brave|vivaldi|opera)/.test(pat);
    const newId = "app_" + Date.now();
    APP.config.profiles.push({
      id: newId,
      name: `${appName} (${pat})`,
      enabled: true,
      is_global: false,
      match_patterns: [pat],
      pointer_scale: 1.0,
      thumb_speed: 1.5,
      thumb_invert: false,
      wheel_invert: false,
      bindings: {
        forward: { kind: "passthrough" },
        backward: defaultGestureSpec(),
        middle: { kind: "passthrough" },
        thumb_up: isBrowser
          ? { kind: "key_combo", combo: "Ctrl+Shift+Tab" }
          : { kind: "zoom", direction: 1, zoom_mode: "auto" },
        thumb_down: isBrowser
          ? { kind: "key_combo", combo: "Ctrl+Tab" }
          : { kind: "zoom", direction: -1, zoom_mode: "auto" },
      },
    });
    APP.selectedProfileId = newId;
    APP.config.per_app_enabled = true;
    await persistConfig(`已创建「${appName}」专属方案`);
  }

  // =========================================================================
  // ACTION & MULTI-STEP MACRO MODAL
  // =========================================================================
  function populateModalPresets(slotKey) {
    if (!APP.meta) return;
    const sk = slotKey || APP.editingSlot || "backward";
    const mainSel = document.getElementById("modal-preset-sel");
    mainSel.innerHTML = buildPresetOptionsHtml(sk, "passthrough");

    document.querySelectorAll(".gest-sel").forEach((gs) => {
      gs.innerHTML = buildPresetOptionsHtml(sk, "passthrough");
    });
  }

  function syncModalVisibility() {
    const kind = document.getElementById("modal-kind").value;
    document.getElementById("modal-preset-wrap").style.display = kind === "preset" ? "block" : "none";
    document.getElementById("modal-combo-wrap").style.display = kind === "key_combo" ? "block" : "none";
    document.getElementById("modal-macro-wrap").style.display = kind === "macro" ? "block" : "none";
    document.getElementById("modal-gesture-wrap").style.display = kind === "gesture_4way" ? "block" : "none";
    document.getElementById("modal-zoom-wrap").style.display = kind === "zoom" ? "block" : "none";
    document.getElementById("modal-sniper-wrap").style.display = kind === "sniper_dpi" ? "block" : "none";
    document.getElementById("modal-cmd-wrap").style.display = kind === "command" ? "block" : "none";
  }

  function renderMacroStepsDraft() {
    const box = document.getElementById("macro-steps-list");
    box.innerHTML = "";
    if (!APP.macroStepsDraft.length) {
      box.innerHTML = `<div style="color:var(--text-muted);font-size:12px;">暂无步骤 — 点击「连续按键录制」直接按键盘，或点击「+ 添加步骤」。</div>`;
      return;
    }
    APP.macroStepsDraft.forEach((st, idx) => {
      const row = document.createElement("div");
      row.className = "macro-step-row";
      row.innerHTML = `
        <span style="font-family:var(--font-mono);color:var(--accent-cyan);width:44px;">#${idx + 1}</span>
        <input type="text" class="hw-input m-combo" data-idx="${idx}" value="${escapeHtml(
        st.combo || ""
      )}" placeholder="如 Ctrl+C" style="flex:1;font-family:var(--font-mono);" />
        <span style="font-size:11.5px;color:var(--text-sec);">间隔(ms)</span>
        <input type="number" class="hw-input m-delay" data-idx="${idx}" value="${
        st.delay_ms ?? 40
      }" min="0" max="5000" style="width:74px;" />
        <button type="button" class="hw-btn sm danger m-del" data-idx="${idx}">删除</button>
      `;
      box.appendChild(row);
    });
    box.querySelectorAll(".m-combo").forEach((inp) => {
      inp.addEventListener("input", (e) => {
        APP.macroStepsDraft[Number(e.target.dataset.idx)].combo = e.target.value;
      });
    });
    box.querySelectorAll(".m-delay").forEach((inp) => {
      inp.addEventListener("input", (e) => {
        APP.macroStepsDraft[Number(e.target.dataset.idx)].delay_ms = Number(e.target.value);
      });
    });
    box.querySelectorAll(".m-del").forEach((btn) => {
      btn.addEventListener("click", () => {
        APP.macroStepsDraft.splice(Number(btn.dataset.idx), 1);
        renderMacroStepsDraft();
      });
    });
  }

  function openActionModal(slotKey) {
    const prof = getSelectedProfile();
    if (!prof) return;
    APP.editingSlot = slotKey;
    APP.recordingCombo = false;
    APP.recordingMacro = false;

    populateModalPresets(slotKey);

    const slotLabel = (APP.meta && APP.meta.bindable_inputs && APP.meta.bindable_inputs[slotKey]) || slotKey;
    document.getElementById("modal-slot-title").textContent = `${prof.name.split(" (")[0]} // ${slotLabel}`;

    // Make the "passthrough" option in modal-kind explicit too
    const ptOpt = document.querySelector('#modal-kind option[value="passthrough"]');
    if (ptOpt) ptOpt.textContent = DEFAULT_SLOT_DESC[slotKey] || "恢复该按键原厂默认功能";

    const spec = (prof.bindings && prof.bindings[slotKey]) || { kind: "passthrough" };
    const matchedPreset = findPresetIdForSpec(spec);

    const kindSel = document.getElementById("modal-kind");
    if (matchedPreset && !["macro", "gesture_4way", "command"].includes(spec.kind)) {
      kindSel.value = "preset";
      document.getElementById("modal-preset-sel").value = matchedPreset;
    } else if (spec.kind === "key_combo") {
      kindSel.value = "key_combo";
      document.getElementById("modal-combo-inp").value = spec.combo || "";
    } else if (spec.kind === "macro") {
      kindSel.value = "macro";
      APP.macroStepsDraft = JSON.parse(JSON.stringify(spec.macro_steps || []));
      renderMacroStepsDraft();
    } else if (spec.kind === "gesture_4way") {
      kindSel.value = "gesture_4way";
      document.getElementById("modal-gest-thresh").value = spec.gesture_threshold || 45;
      ["tap", "up", "down", "left", "right", "wheel_up", "wheel_down"].forEach((gsub) => {
        const sel = document.querySelector(`.gest-sel[data-gsub="${gsub}"]`);
        if (sel) sel.value = findPresetIdForSpec(spec[gsub]) || "passthrough";
      });
    } else if (spec.kind === "zoom") {
      kindSel.value = "zoom";
      document.getElementById("modal-zoom-dir").value = String(spec.direction || 1);
      document.getElementById("modal-zoom-mode").value = spec.zoom_mode || "auto";
    } else if (spec.kind === "sniper_dpi") {
      kindSel.value = "sniper_dpi";
      document.getElementById("modal-sniper-scale").value = spec.scale || 0.4;
    } else if (spec.kind === "command") {
      kindSel.value = "command";
      document.getElementById("modal-cmd-inp").value = spec.command || "";
    } else {
      kindSel.value = spec.kind || "passthrough";
    }

    if (kindSel.value !== "macro") {
      APP.macroStepsDraft = [
        { combo: "Ctrl+C", delay_ms: 40 },
        { combo: "Ctrl+V", delay_ms: 40 },
      ];
      renderMacroStepsDraft();
    }

    document.getElementById("btn-record-combo").textContent = "按下键盘录制";
    document.getElementById("btn-macro-rec").textContent = "连续按键录制";
    syncModalVisibility();
    document.getElementById("action-modal").classList.add("open");
  }

  function browserKeyEventToCombo(e) {
    const modKeys = ["Control", "Shift", "Alt", "Meta"];
    if (modKeys.includes(e.key)) return null;
    const parts = [];
    if (e.ctrlKey) parts.push("Ctrl");
    if (e.shiftKey) parts.push("Shift");
    if (e.altKey) parts.push("Alt");
    if (e.metaKey) parts.push("Super");

    const map = {
      " ": "Space",
      ArrowUp: "Up",
      ArrowDown: "Down",
      ArrowLeft: "Left",
      ArrowRight: "Right",
      Escape: "Esc",
      "+": "=",
      "_": "-",
    };
    let k = map[e.key] || e.key;
    if (k.length === 1) k = k.toUpperCase();
    parts.push(k);
    return parts.join("+");
  }

  // =========================================================================
  // GLOBAL EVENT WIRING
  // =========================================================================
  function bindGlobalUI() {
    document.querySelectorAll("#left-nav .nav-item").forEach((btn) => {
      btn.addEventListener("click", () => switchPane(btn.dataset.pane));
    });

    document.querySelectorAll(".metric-box[data-jump]").forEach((tile) => {
      tile.addEventListener("click", () => switchPane(tile.dataset.jump));
    });
    document.getElementById("btn-goto-bindings").addEventListener("click", () => switchPane("bindings"));

    // 3D vs Factory Reference Photo switcher
    document.querySelectorAll(".mode-tab[data-vmode]").forEach((tab) => {
      tab.addEventListener("click", () => {
        const is3d = tab.dataset.vmode === "3d";
        document.querySelectorAll(".mode-tab[data-vmode]").forEach((t) => t.classList.toggle("active", t === tab));
        document.getElementById("webgl-stage-wrap").style.display = is3d ? "block" : "none";
        document.getElementById("photo-stage-wrap").classList.toggle("active", !is3d);
        document.getElementById("cam-3d-controls").style.display = is3d ? "flex" : "none";
        document.getElementById("cam-photo-controls").style.display = is3d ? "none" : "flex";
        document.getElementById("btn-3d-autorotate").style.display = is3d ? "inline-block" : "none";
      });
    });

    // 3D Camera Presets
    document.querySelectorAll("#cam-3d-controls .cam-pill").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#cam-3d-controls .cam-pill").forEach((b) => b.classList.toggle("active", b === btn));
        if (APP.viewer3d) APP.viewer3d.setCameraPreset(btn.dataset.cam);
      });
    });
    document.getElementById("btn-3d-autorotate").addEventListener("click", (e) => {
      if (!APP.viewer3d) return;
      const on = APP.viewer3d.toggleAutoRotate();
      e.currentTarget.classList.toggle("active", on);
    });

    // Factory Photo Switcher
    document.querySelectorAll("#cam-photo-controls .cam-pill").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#cam-photo-controls .cam-pill").forEach((b) => b.classList.toggle("active", b === btn));
        document.getElementById("photo-view-img").src = btn.dataset.photo;
      });
    });

    // Top Bar Hardware Sync & Daemon Control
    document.getElementById("btn-sync-hw").addEventListener("click", async () => {
      showToast("正在同步鼠标硬件寄存器与实时电量...");
      const res = await apiPost("/api/hardware/refresh", {});
      APP.hardware = res.hardware;
      renderAll();
      showToast(res.ok ? "硬件参数与电量已同步" : "读取提示: " + (res.hardware.error || ""), !res.ok);
    });

    document.getElementById("btn-restart-daemon").addEventListener("click", async () => {
      showToast("正在重启后台守护进程...");
      const res = await apiPost("/api/daemon/control", { action: "restart" });
      if (res.daemon) APP.daemon = res.daemon;
      renderTelemetryAndOverview();
      showToast("守护进程已就绪");
    });

    // Per-App Master Switches
    ["chk-perapp-sidebar", "chk-perapp-overview", "chk-perapp-main"].forEach((id) => {
      document.getElementById(id).addEventListener("change", (e) => {
        if (!APP.config) return;
        APP.config.per_app_enabled = e.target.checked;
        persistConfig(
          APP.config.per_app_enabled
            ? "已开启按焦点应用自动切换方案"
            : "已关闭应用切换，固定使用全局默认方案"
        );
      });
    });

    document.getElementById("chk-daemon-enabled").addEventListener("change", (e) => {
      if (!APP.config) return;
      APP.config.daemon_enabled = e.target.checked;
      persistConfig(
        APP.config.daemon_enabled ? "已开启软件增强接管引擎" : "已切换为纯硬件板载直通模式"
      );
    });

    // 1-Click Application Selector Modal Triggers
    document.getElementById("btn-open-app-picker").addEventListener("click", openAppPickerModal);
    document.getElementById("btn-quick-pick-ov").addEventListener("click", openAppPickerModal);
    document.getElementById("btn-app-modal-close").addEventListener("click", () => {
      document.getElementById("app-picker-modal").classList.remove("open");
    });
    document.getElementById("btn-refresh-apps").addEventListener("click", refreshAppPickerList);
    document.getElementById("inp-app-search").addEventListener("input", (e) => {
      renderAppPickerItems(e.target.value);
    });

    // Inline Gesture Host Controls
    document.getElementById("sel-gesture-host").addEventListener("change", (e) => {
      APP.gestureHostSlot = e.target.value;
      const prof = getSelectedProfile();
      if (prof) renderInlineGestureMatrix(prof);
    });

    document.getElementById("btn-toggle-gesture-host").addEventListener("click", () => {
      const prof = getSelectedProfile();
      if (!prof) return;
      const host = APP.gestureHostSlot;
      const cur = (prof.bindings && prof.bindings[host]) || { kind: "passthrough" };
      if (cur.kind === "gesture_4way") {
        prof.bindings[host] = { kind: "passthrough" };
        persistConfig(`已关闭四向手势，恢复为 ${DEFAULT_SLOT_SHORT[host] || "原厂默认"}`);
      } else {
        prof.bindings[host] = defaultGestureSpec();
        persistConfig("已开启罗技式按住四向滑动与主滚轮手势");
      }
    });

    // Profile CRUD
    document.getElementById("btn-add-profile").addEventListener("click", () => {
      const id = "custom_" + Date.now();
      APP.config.profiles.push({
        id,
        name: "新建自定义软件方案",
        enabled: true,
        is_global: false,
        match_patterns: ["my-app"],
        pointer_scale: 1.0,
        thumb_speed: 1.5,
        thumb_invert: false,
        wheel_invert: false,
        bindings: {
          forward: { kind: "passthrough" },
          backward: defaultGestureSpec(),
          middle: { kind: "passthrough" },
          thumb_up: { kind: "zoom", direction: 1, zoom_mode: "auto" },
          thumb_down: { kind: "zoom", direction: -1, zoom_mode: "auto" },
        },
      });
      APP.selectedProfileId = id;
      persistConfig("已创建空白方案，请填写进程/窗口匹配词");
    });

    document.getElementById("btn-save-prof-meta").addEventListener("click", () => {
      const prof = getSelectedProfile();
      if (!prof || prof.is_global) return;
      prof.name = document.getElementById("inp-prof-name").value.trim() || "自定义应用";
      prof.match_patterns = document
        .getElementById("inp-prof-patterns")
        .value.split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      persistConfig("应用匹配词已保存");
    });

    document.getElementById("btn-del-profile").addEventListener("click", () => {
      const prof = getSelectedProfile();
      if (!prof || prof.is_global) return;
      APP.config.profiles = APP.config.profiles.filter((p) => p.id !== prof.id);
      APP.selectedProfileId = "global";
      persistConfig("已删除该方案");
    });

    // 1-Click Thumbwheel Presets
    document.querySelectorAll(".scenario-btn[data-tw]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const prof = getSelectedProfile();
        if (!prof) return;
        const mode = btn.dataset.tw;
        if (mode === "tabs") {
          prof.bindings.thumb_up = { kind: "key_combo", combo: "Ctrl+Shift+Tab" };
          prof.bindings.thumb_down = { kind: "key_combo", combo: "Ctrl+Tab" };
        } else if (mode === "zoom") {
          prof.bindings.thumb_up = { kind: "zoom", direction: 1, zoom_mode: "auto" };
          prof.bindings.thumb_down = { kind: "zoom", direction: -1, zoom_mode: "auto" };
        } else if (mode === "hscroll") {
          prof.bindings.thumb_up = { kind: "passthrough" };
          prof.bindings.thumb_down = { kind: "passthrough" };
        } else if (mode === "volume") {
          prof.bindings.thumb_up = { kind: "media", media: "VOLUMEUP" };
          prof.bindings.thumb_down = { kind: "media", media: "VOLUMEDOWN" };
        } else if (mode === "timeline") {
          prof.bindings.thumb_up = { kind: "key_combo", combo: "Left" };
          prof.bindings.thumb_down = { kind: "key_combo", combo: "Right" };
        } else if (mode === "workspace") {
          prof.bindings.thumb_up = { kind: "key_combo", combo: "Super+PageUp" };
          prof.bindings.thumb_down = { kind: "key_combo", combo: "Super+PageDown" };
        }
        persistConfig(`已更新「${prof.name.split(" (")[0]}」拇指滚轮预设`);
      });
    });

    // Pointer & Scroll Sliders
    document.getElementById("rng-ptr-scale").addEventListener("change", (e) => {
      const prof = getSelectedProfile();
      if (!prof) return;
      prof.pointer_scale = Number(e.target.value);
      document.getElementById("lbl-ptr-scale").textContent = prof.pointer_scale.toFixed(2) + "x";
      persistConfig("已更新方案指针倍率");
    });
    document.getElementById("rng-ptr-scale").addEventListener("input", (e) => {
      document.getElementById("lbl-ptr-scale").textContent = Number(e.target.value).toFixed(2) + "x";
    });

    document.getElementById("rng-thumb-spd").addEventListener("change", (e) => {
      const prof = getSelectedProfile();
      if (!prof) return;
      prof.thumb_speed = Number(e.target.value);
      document.getElementById("lbl-thumb-spd").textContent = prof.thumb_speed.toFixed(2) + "x";
      persistConfig("已更新拇指横向滚动倍率");
    });
    document.getElementById("rng-thumb-spd").addEventListener("input", (e) => {
      document.getElementById("lbl-thumb-spd").textContent = Number(e.target.value).toFixed(2) + "x";
    });

    document.getElementById("chk-thumb-inv").addEventListener("change", (e) => {
      const prof = getSelectedProfile();
      if (!prof) return;
      prof.thumb_invert = e.target.checked;
      persistConfig("已更新拇指滚轮方向");
    });
    document.getElementById("chk-wheel-inv").addEventListener("change", (e) => {
      const prof = getSelectedProfile();
      if (!prof) return;
      prof.wheel_invert = e.target.checked;
      persistConfig("已更新主滚轮方向");
    });

    // DPI, Polling & Debounce
    document.getElementById("btn-apply-dpi").addEventListener("click", writeDpiNow);

    document.querySelectorAll("#hz-cards-box .hz-card").forEach((card) => {
      card.addEventListener("click", async () => {
        const hz = Number(card.dataset.hz);
        const res = await apiPost("/api/hardware/polling", { hz });
        if (res.ok) {
          APP.hardware.polling = res.polling;
          renderDpiAndPollingPane();
          renderTelemetryAndOverview();
          showToast(`硬件回报率已切换至 ${hz} Hz`);
        } else {
          showToast("切换回报率失败: " + (res.error || ""), true);
        }
      });
    });

    document.getElementById("rng-debounce-ms").addEventListener("input", (e) => {
      document.getElementById("lbl-debounce-ms").textContent = `${e.target.value} ms`;
    });
    document.getElementById("btn-apply-debounce").addEventListener("click", async () => {
      const debounce_ms = Number(document.getElementById("rng-debounce-ms").value);
      const res = await apiPost("/api/hardware/lighting", { debounce_ms });
      if (res.ok) {
        APP.hardware.lighting = res.lighting;
        showToast(`微动消抖延迟已设为 ${debounce_ms} ms`);
      } else {
        showToast("写入消抖失败: " + (res.error || ""), true);
      }
    });

    // RGB & Power Sleep
    document.querySelectorAll("#rgb-swatches .color-swatch").forEach((sw) => {
      sw.addEventListener("click", () => {
        const hex = sw.dataset.hex;
        document.getElementById("inp-rgb-color").value = hex;
        APP.hardware.lighting.rgb = hexToRgb(hex);
        if (![1, 2].includes(APP.hardware.lighting.mode)) {
          APP.hardware.lighting.mode = 1;
        }
        renderRgbPane();
        sync3DModel();
      });
    });

    document.getElementById("inp-rgb-color").addEventListener("input", (e) => {
      APP.hardware.lighting.rgb = hexToRgb(e.target.value);
      sync3DModel();
    });
    document.getElementById("rng-rgb-bright").addEventListener("input", (e) => {
      APP.hardware.lighting.brightness = Number(e.target.value);
      document.getElementById("lbl-rgb-bright").textContent = `${e.target.value} / 8`;
      sync3DModel();
    });
    document.getElementById("rng-rgb-speed").addEventListener("input", (e) => {
      APP.hardware.lighting.led_speed = Number(e.target.value);
      document.getElementById("lbl-rgb-speed").textContent = `${e.target.value} / 5`;
      sync3DModel();
    });
    document.getElementById("rng-light-sleep").addEventListener("input", (e) => {
      APP.hardware.lighting.light_sleep_minutes = Number(e.target.value);
      document.getElementById("lbl-light-sleep").textContent = `${e.target.value} 分钟`;
    });
    document.getElementById("rng-deep-sleep").addEventListener("input", (e) => {
      APP.hardware.lighting.deep_sleep_minutes = Number(e.target.value);
      document.getElementById("lbl-deep-sleep").textContent = `${e.target.value} 分钟`;
    });

    document.getElementById("btn-apply-rgb").addEventListener("click", async () => {
      const lt = APP.hardware.lighting;
      const res = await apiPost("/api/hardware/lighting", {
        mode: lt.mode,
        rgb: lt.rgb,
        brightness: lt.brightness,
        led_speed: lt.led_speed,
        light_sleep_minutes: lt.light_sleep_minutes,
        deep_sleep_minutes: lt.deep_sleep_minutes,
      });
      if (res.ok) {
        APP.hardware.lighting = res.lighting;
        renderRgbPane();
        renderTelemetryAndOverview();
        showToast("灯光与电源管理参数已写入硬件");
      } else {
        showToast("写入失败: " + (res.error || ""), true);
      }
    });

    // Onboard Flash & Backup/Restore
    document.getElementById("btn-write-onboard").addEventListener("click", async () => {
      const slotsPayload = [];
      document.querySelectorAll("#onboard-tbody .ob-act-sel").forEach((sel) => {
        const slot = Number(sel.dataset.slot);
        const comboInp = document.querySelector(`#onboard-tbody .ob-combo-inp[data-slot="${slot}"]`);
        slotsPayload.push({
          slot,
          action_key: sel.value,
          combo: comboInp ? comboInp.value.trim() : "",
        });
      });
      const active_onboard_profile = Number(document.getElementById("sel-onboard-prof").value);
      const res = await apiPost("/api/hardware/buttons", {
        active_onboard_profile,
        slots: slotsPayload,
      });
      if (res.ok) {
        APP.hardware.buttons = res.buttons;
        renderOnboardPane();
        showToast("板载芯片映射已烧录完成");
      } else {
        showToast("烧录失败: " + (res.error || ""), true);
      }
    });

    document.getElementById("btn-backup-user").addEventListener("click", async () => {
      const res = await apiPost("/api/hardware/backup", {});
      showToast(res.ok ? "硬件参数备份已保存" : "备份失败: " + (res.error || ""), !res.ok);
    });
    document.getElementById("btn-restore-user").addEventListener("click", async () => {
      const res = await apiPost("/api/hardware/restore", { source: "user" });
      if (res.ok) {
        APP.hardware = res.hardware;
        renderAll();
        showToast("已恢复您的硬件参数备份");
      } else {
        showToast("恢复失败: " + (res.error || ""), true);
      }
    });
    document.getElementById("btn-restore-factory").addEventListener("click", async () => {
      const res = await apiPost("/api/hardware/restore", { source: "factory" });
      if (res.ok) {
        APP.hardware = res.hardware;
        renderAll();
        showToast("已恢复多彩 M618XSD 原厂默认硬件设置");
      } else {
        showToast("恢复出厂失败: " + (res.error || ""), true);
      }
    });

    // Action Modal Controls
    document.getElementById("modal-kind").addEventListener("change", syncModalVisibility);
    const closeModal = () => {
      APP.recordingCombo = false;
      APP.recordingMacro = false;
      document.getElementById("action-modal").classList.remove("open");
    };
    document.getElementById("btn-modal-close").addEventListener("click", closeModal);
    document.getElementById("btn-modal-cancel").addEventListener("click", closeModal);

    document.getElementById("btn-record-combo").addEventListener("click", (e) => {
      APP.recordingCombo = !APP.recordingCombo;
      APP.recordingMacro = false;
      e.currentTarget.textContent = APP.recordingCombo ? "正在监听键盘 (请按键)..." : "按下键盘录制";
    });

    document.getElementById("btn-macro-rec").addEventListener("click", (e) => {
      APP.recordingMacro = !APP.recordingMacro;
      APP.recordingCombo = false;
      e.currentTarget.textContent = APP.recordingMacro ? "停止录制" : "连续按键录制";
    });

    document.getElementById("btn-macro-add").addEventListener("click", () => {
      APP.macroStepsDraft.push({ combo: "Ctrl+C", delay_ms: 40 });
      renderMacroStepsDraft();
    });

    window.addEventListener(
      "keydown",
      (e) => {
        if (!APP.recordingCombo && !APP.recordingMacro) return;
        e.preventDefault();
        e.stopPropagation();
        const combo = browserKeyEventToCombo(e);
        if (!combo) return;
        if (APP.recordingCombo) {
          document.getElementById("modal-combo-inp").value = combo;
          APP.recordingCombo = false;
          document.getElementById("btn-record-combo").textContent = "按下键盘录制";
        } else if (APP.recordingMacro) {
          APP.macroStepsDraft.push({ combo, delay_ms: 45 });
          renderMacroStepsDraft();
        }
      },
      true
    );

    document.getElementById("btn-modal-save").addEventListener("click", () => {
      const prof = getSelectedProfile();
      if (!prof || !APP.editingSlot) return;
      const kind = document.getElementById("modal-kind").value;

      let newSpec = { kind: "passthrough" };
      if (kind === "preset") {
        newSpec = presetSpecById(document.getElementById("modal-preset-sel").value);
      } else if (kind === "key_combo") {
        newSpec = {
          kind: "key_combo",
          combo: document.getElementById("modal-combo-inp").value.trim() || "Ctrl+C",
        };
      } else if (kind === "macro") {
        newSpec = {
          kind: "macro",
          macro_steps: APP.macroStepsDraft.filter((s) => s.combo && s.combo.trim()),
        };
      } else if (kind === "gesture_4way") {
        newSpec = {
          kind: "gesture_4way",
          gesture_threshold: Number(document.getElementById("modal-gest-thresh").value) || 45,
        };
        ["tap", "up", "down", "left", "right", "wheel_up", "wheel_down"].forEach((gsub) => {
          const sel = document.querySelector(`.gest-sel[data-gsub="${gsub}"]`);
          newSpec[gsub] = presetSpecById(sel ? sel.value : "passthrough");
        });
        if (["backward", "forward", "middle"].includes(APP.editingSlot)) {
          APP.gestureHostSlot = APP.editingSlot;
        }
      } else if (kind === "zoom") {
        newSpec = {
          kind: "zoom",
          direction: Number(document.getElementById("modal-zoom-dir").value) || 1,
          zoom_mode: document.getElementById("modal-zoom-mode").value || "auto",
        };
      } else if (kind === "sniper_dpi") {
        newSpec = {
          kind: "sniper_dpi",
          scale: Number(document.getElementById("modal-sniper-scale").value) || 0.4,
        };
      } else if (kind === "command") {
        newSpec = {
          kind: "command",
          command: document.getElementById("modal-cmd-inp").value.trim(),
        };
      } else if (kind === "disabled") {
        newSpec = { kind: "disabled" };
      }

      prof.bindings[APP.editingSlot] = newSpec;
      closeModal();
      persistConfig("按键动作已保存并实时生效");
    });
  }

  function renderAll() {
    populateModalPresets("backward");
    renderTelemetryAndOverview();
    renderBindingsPane();
    renderDpiAndPollingPane();
    renderRgbPane();
    renderOnboardPane();
  }

  async function init() {
    const canvas = document.getElementById("mouse3d-canvas");
    const overlay = document.getElementById("hotspot-overlay");
    APP.viewer3d = new window.M618XSDViewer3D(canvas, overlay, (hotspot) => {
      if (hotspot && hotspot.nav) {
        switchPane(hotspot.nav);
      }
    });

    bindGlobalUI();

    const state = await apiGet("/api/state");
    APP.hardware = state.hardware;
    APP.daemon = state.daemon;
    APP.config = state.config;
    APP.meta = state.meta;
    renderAll();

    // Single non-intrusive initial hardware check (zero retry spam if in 30s wireless sleep)
    apiPost("/api/hardware/refresh", { fast: true }).then((res) => {
      if (res && res.hardware) {
        APP.hardware = res.hardware;
        renderAll();
      }
    });

    // Live 1.1s active window focus & passive daemon telemetry loop (ZERO USB control transfers)
    setInterval(async () => {
      try {
        const tel = await apiGet("/api/telemetry");
        if (tel && tel.ok) {
          APP.daemon = tel.daemon;
          if (tel.hardware) {
            const wasSleeping = !!APP.hardware.sleeping;
            APP.hardware.connected = tel.hardware.connected;
            APP.hardware.sleeping = tel.hardware.sleeping;
            APP.hardware.error = tel.hardware.error || "";
            if (tel.hardware.firmware && tel.hardware.firmware !== "--") {
              APP.hardware.firmware = tel.hardware.firmware;
            }
            if (tel.hardware.battery && typeof tel.hardware.battery.percent === "number") {
              APP.hardware.battery = tel.hardware.battery;
            }
            if (wasSleeping && !tel.hardware.sleeping) {
              APP.hardware.dpi = tel.hardware.dpi || APP.hardware.dpi;
              APP.hardware.lighting = tel.hardware.lighting || APP.hardware.lighting;
              APP.hardware.polling = tel.hardware.polling || APP.hardware.polling;
              renderAll();
              return;
            }
          }
          renderTelemetryAndOverview();
        }
      } catch (_e) {}
    }, 1100);
  }

  window.addEventListener("DOMContentLoaded", init);
})();
