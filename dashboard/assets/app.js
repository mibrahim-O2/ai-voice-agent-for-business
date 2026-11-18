/* Voice Agent Dashboard: renders the recorded demo snapshot. No secrets, no network calls other
   than loading demo/snapshot.json from this site. All text is inserted with textContent. */
(function () {
  "use strict";

  const config = window.DASHBOARD_CONFIG || { mode: "demo", snapshotUrl: "demo/snapshot.json" };
  const TABS = [
    ["overview", "Overview"],
    ["calls", "Calls"],
    ["leads", "Leads"],
    ["appointments", "Appointments"],
    ["approvals", "Approvals"],
    ["knowledge", "Knowledge"],
  ];
  const STATUS_LABEL = { approved: "Approved", rejected: "Rejected", pending: "Pending" };
  const STATUS_ICON = { approved: "✓", rejected: "✕", pending: "…" };
  let data = null;
  let selectedCall = null;

  // ---------- helpers ----------
  function h(tag, attrs, children) {
    const el = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") el.className = value;
      else if (key === "text") el.textContent = value;
      else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
      else el.setAttribute(key, value === true ? "" : String(value));
    }
    for (const child of [].concat(children || [])) {
      if (child === null || child === undefined || child === false) continue;
      el.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return el;
  }
  const fmtTime = (iso) => {
    if (!iso) return "";
    const d = new Date(iso);
    return d.toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
  };
  const titleCase = (s) => (s || "").replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

  function chip(status, label) {
    return h("span", { class: `chip ${status}` }, [
      h("span", { "aria-hidden": "true", text: STATUS_ICON[status] || "" }),
      label || STATUS_LABEL[status] || titleCase(status),
    ]);
  }

  function card(title, body, note) {
    return h("section", { class: "card" }, [h("h3", { text: title }), body, note ? h("p", { class: "card-note", text: note }) : null]);
  }

  function fill(row, max) {
    const el = h("span", { class: `meter-fill ${row.key || ""}${row.value === 0 ? " zero" : ""}` });
    el.style.width = `${(100 * row.value) / max}%`; // CSSOM, allowed by the CSP (no inline styles)
    return el;
  }

  /** Meter list: one row per category with a name, a bar on a shared scale and the value. */
  function meters(rows, opts) {
    const max = Math.max(1, ...rows.map((r) => r.value));
    const total = rows.reduce((s, r) => s + r.value, 0);
    return h(
      "ul",
      { class: "meters", role: "list" },
      rows.map((r) =>
        h("li", {
          class: `meter${opts && opts.status ? " status" : ""}`,
          tabindex: "0",
          "data-tip": `${r.label}: ${r.value}${total ? ` (${Math.round((100 * r.value) / total)}% of ${total})` : ""}`,
          "aria-label": `${r.label}: ${r.value}`,
        }, [
          h("span", { class: "meter-name" }, [opts && opts.status ? chip(r.key, r.label) : r.label]),
          h("span", { class: "meter-track", "aria-hidden": "true" }, [fill(r, max)]),
          h("span", { class: "meter-value", text: r.value }),
        ])
      )
    );
  }

  function table(columns, rows, emptyText) {
    if (!rows.length) return h("p", { class: "muted", text: emptyText || "Nothing to show." });
    return h("div", { class: "table-wrap" }, [
      h("table", {}, [
        h("thead", {}, [h("tr", {}, columns.map((c) => h("th", { scope: "col", class: c.num ? "num" : null, text: c.label })))]),
        h("tbody", {}, rows.map((row) => h("tr", {}, columns.map((c) => {
          const value = c.render ? c.render(row) : row[c.key];
          return h("td", { class: [c.num ? "num" : "", c.mono ? "mono" : ""].join(" ").trim() || null }, [value === null || value === undefined ? "–" : value]);
        })))),
      ]),
    ]);
  }

  // ---------- views ----------
  function overview() {
    const k = data.kpis;
    const tiles = [
      ["Calls handled", k.calls_handled, `${k.caller_turns} caller turns`],
      ["Appointments booked", k.appointments_booked, `${k.appointments_cancelled} cancelled`],
      ["Approved", k.approvals.approved, "by a human reviewer"],
      ["Rejected", k.approvals.rejected, "never executed"],
      ["Pending", k.approvals.pending, "caller hung up first"],
      ["Knowledge searches", k.knowledge_searches, `${k.knowledge_not_found} answered “I don't know”`],
      ["Hand-offs to a human", k.handoffs, `${k.guardrail_hits} guardrail warning`],
    ];
    const tierOrder = [["hot", "Hot (score ≥ 70)"], ["warm", "Warm (40–69)"], ["cold", "Cold (< 40)"], ["unscored", "Not yet scored"]];
    const approvalRows = ["approved", "rejected", "pending"].map((s) => ({ key: s, label: STATUS_LABEL[s], value: k.approvals[s] }));
    return h("div", {}, [
      h("h2", { text: "Overview" }),
      h("p", { class: "lede", text: "Seven scripted sample calls ran through the real MCP tools, the knowledge base and the human approval step. These are the results." }),
      h("div", { class: "kpis" }, tiles.map(([label, value, sub]) => h("div", { class: "kpi" }, [
        h("div", { class: "kpi-label", text: label }), h("div", { class: "kpi-value", text: value }), h("div", { class: "kpi-sub", text: sub }),
      ]))),
      h("div", { class: "grid grid-3" }, [
        card("Leads by tier", meters(tierOrder.map(([key, label]) => ({ label, value: data.leads.by_tier[key] || 0 }))), `${data.leads.total} leads in the demo CRM after the calls.`),
        card("Approvals", meters(approvalRows, { status: true }), "Every write action waits for a person. Pending means nobody decided, so it never ran."),
        card("Knowledge sources used", data.knowledge.sources.length
          ? meters(data.knowledge.sources.map((s) => ({ label: s.title, value: s.uses })))
          : h("p", { class: "muted", text: "No sources used." }), `${k.knowledge_not_found} of ${k.knowledge_searches} searches found nothing, so the agent said it didn't know.`),
      ]),
    ]);
  }

  function transcriptEntry(e) {
    if (e.type === "agent" || e.type === "caller") {
      return h("div", { class: `msg ${e.type}` }, [h("div", { class: "msg-who", text: e.type === "agent" ? (e.greeting ? "AI agent · greeting" : "AI agent") : "Caller" }), e.text]);
    }
    if (e.type === "tool_call") {
      return h("div", { class: "event" }, ["Tool call ", h("span", { class: "mono", text: e.tool }), " ", h("span", { class: "mono muted", text: JSON.stringify(e.arguments) })]);
    }
    if (e.type === "tool_result") {
      const bits = [];
      if (e.tool === "search_knowledge") bits.push(e.found ? `found: ${(e.sources || []).join(", ")}` : "nothing relevant found");
      if (e.booked) bits.push("booked");
      if (e.cancelled) bits.push("cancelled");
      if (e.tier) bits.push(`tier ${e.tier}, score ${e.score}`);
      if (e.rejected) bits.push("not run: rejected by the reviewer");
      return h("div", { class: "event" }, ["Result ", h("span", { class: "mono", text: e.tool }), bits.length ? ` – ${bits.join("; ")}` : ""]);
    }
    if (e.type === "approval_requested") {
      return h("div", { class: "event approval" }, [chip("pending", "Approval requested"), " ", e.summary, (e.warnings || []).length ? h("div", { class: "muted", text: `Warning shown to reviewer: ${e.warnings.join(" ")}` }) : null]);
    }
    if (e.type === "approval_decision") {
      const s = e.approved ? "approved" : "rejected";
      return h("div", { class: `event decision-${s}` }, [chip(s), ` by ${e.decided_by}`, e.reason ? ` – ${e.reason}` : ""]);
    }
    if (e.type === "guardrail") return h("div", { class: "event guardrail" }, [chip("rejected", "Guardrail"), ` suspected prompt injection: “${(e.matches || []).join("”, “")}”`]);
    if (e.type === "handoff") return h("div", { class: "event handoff" }, [h("strong", { text: "Hand-off to a human: " }), `${e.reason}. ${e.summary || ""}`]);
    if (e.type === "error") return h("div", { class: "event error" }, [h("strong", { text: "Event: " }), e.detail]);
    return null;
  }

  function calls() {
    const sessions = data.sessions;
    if (!selectedCall || !sessions.some((s) => s.id === selectedCall)) selectedCall = sessions.length ? sessions[0].id : null;
    const current = sessions.find((s) => s.id === selectedCall);
    const list = h("ul", { class: "call-list", role: "list" }, sessions.map((s) => h("li", {}, [
      h("button", { class: "call-item", type: "button", "aria-current": s.id === selectedCall ? "true" : null, onclick: () => { selectedCall = s.id; render(); } }, [
        h("div", { class: "call-id", text: `${s.id} · ${s.caller_turns} caller turn${s.caller_turns === 1 ? "" : "s"} · ${s.tool_calls} tool calls` }),
        h("div", { class: "call-title", text: s.title }),
        h("div", { class: "call-tags" }, s.outcomes.map((o) => h("span", { class: `chip ${o === "booked" ? "booked" : o === "rejected" ? "rejected" : o === "pending approval" ? "pending" : ""}`, text: o }))),
      ]),
    ])));
    return h("div", {}, [
      h("h2", { text: "Calls" }),
      h("p", { class: "lede", text: "Sample transcripts with every tool call, approval and decision in order. Choose a call to read it." }),
      h("div", { class: "calls" }, [
        list,
        current ? card(`Transcript: ${current.title}`, h("div", { class: "transcript" }, current.transcript.map(transcriptEntry)), `Recorded with ${current.model} (scripted agent words, real tools).`) : h("p", { text: "No calls." }),
      ]),
    ]);
  }

  function leads() {
    const state = leads.state || (leads.state = { tier: "all", status: "all", q: "" });
    const rows = data.leads.rows.filter((r) =>
      (state.tier === "all" || (r.tier || "unscored") === state.tier) &&
      (state.status === "all" || r.status === state.status) &&
      (!state.q || `${r.id} ${r.name} ${r.company || ""} ${r.service}`.toLowerCase().includes(state.q.toLowerCase())));
    const select = (label, key, options) => h("label", {}, [label, h("select", { onchange: (ev) => { state[key] = ev.target.value; render(); } },
      options.map((o) => h("option", { value: o, selected: state[key] === o ? true : null, text: o === "all" ? "All" : titleCase(o) })))]);
    return h("div", {}, [
      h("h2", { text: "Leads" }),
      h("p", { class: "lede", text: "The demo CRM after the calls. Scores and tiers come from the qualify_lead tool; all names are fictional." }),
      h("div", { class: "grid grid-2" }, [
        card("By tier", meters(["hot", "warm", "cold", "unscored"].map((t) => ({ label: titleCase(t === "unscored" ? "not yet scored" : t), value: data.leads.by_tier[t] || 0 })))),
        card("By status", meters(Object.entries(data.leads.by_status).map(([s, n]) => ({ label: titleCase(s), value: n })))),
      ]),
      h("div", { class: "section" }, [
        h("div", { class: "filters" }, [
          select("Tier", "tier", ["all", "hot", "warm", "cold", "unscored"]),
          select("Status", "status", ["all", ...Object.keys(data.leads.by_status)]),
          h("label", {}, ["Search", h("input", { type: "search", value: state.q, placeholder: "name, id, service", oninput: (ev) => { state.q = ev.target.value; render(true); } })]),
          h("span", { class: "muted", text: `${rows.length} of ${data.leads.rows.length}` }),
        ]),
        table([
          { label: "ID", key: "id", mono: true },
          { label: "Name", key: "name" },
          { label: "Company", key: "company" },
          { label: "Service", key: "service" },
          { label: "Status", render: (r) => titleCase(r.status) },
          { label: "Tier", render: (r) => (r.tier ? chip(r.tier === "hot" ? "hot" : "", titleCase(r.tier)) : "–") },
          { label: "Score", key: "score", num: true },
          { label: "Source", render: (r) => titleCase(r.source) },
        ], rows, "No leads match the filters."),
      ]),
    ]);
  }

  function appointments() {
    const booked = data.appointments.filter((a) => a.status === "booked").length;
    return h("div", {}, [
      h("h2", { text: "Appointments" }),
      h("p", { class: "lede", text: `${booked} booked, ${data.appointments.length - booked} cancelled. Times are in ${data.meta.timezone || "local"} time.` }),
      table([
        { label: "ID", key: "id", mono: true },
        { label: "When", render: (a) => fmtTime(a.start) },
        { label: "Customer", render: (a) => `${a.lead_name} (${a.lead_id})` },
        { label: "Service", key: "service" },
        { label: "Technician", key: "staff" },
        { label: "Status", render: (a) => chip(a.status === "booked" ? "booked" : "rejected", titleCase(a.status)) },
      ], data.appointments),
    ]);
  }

  function approvals() {
    const k = data.kpis.approvals;
    return h("div", {}, [
      h("h2", { text: "Approvals" }),
      h("p", { class: "lede", text: "Every action that changes data paused for a person. Approved actions ran exactly as shown; rejected and pending ones never ran." }),
      h("div", { class: "grid grid-3" }, ["approved", "rejected", "pending"].map((s) => h("div", { class: "kpi" }, [h("div", { class: "kpi-label" }, [chip(s)]), h("div", { class: "kpi-value", text: k[s] })]))),
      h("div", { class: "section" }, [table([
        { label: "Call", key: "session_id", mono: true },
        { label: "Action", key: "summary" },
        { label: "Tool", key: "tool", mono: true },
        { label: "Status", render: (a) => chip(a.status) },
        { label: "Decided by", render: (a) => a.decided_by || "–" },
        { label: "Reason", render: (a) => a.reason || "–" },
      ], data.approvals)]),
    ]);
  }

  function knowledge() {
    return h("div", {}, [
      h("h2", { text: "Knowledge (RAG)" }),
      h("p", { class: "lede", text: "Questions the agent looked up in the knowledge base, and the documents its answers came from. When nothing relevant was found it said it didn't know." }),
      h("div", { class: "grid grid-2" }, [
        card("Sources used", meters(data.knowledge.sources.map((s) => ({ label: s.title, value: s.uses })))),
        card("Searches", meters([
          { label: "Answered from a source", value: data.kpis.knowledge_searches - data.kpis.knowledge_not_found },
          { label: "Nothing found: “I don't know”", value: data.kpis.knowledge_not_found },
        ])),
      ]),
      h("div", { class: "section" }, [table([
        { label: "Call", key: "session_id", mono: true },
        { label: "Query", key: "query" },
        { label: "Result", render: (q) => (q.found ? chip("approved", "Found") : chip("pending", "Not found")) },
        { label: "Sources", render: (q) => (q.sources.length ? q.sources.join(", ") : "–") },
      ], data.knowledge.queries)]),
    ]);
  }

  const VIEWS = { overview, calls, leads, appointments, approvals, knowledge };

  // ---------- shell ----------
  function currentTab() {
    const tab = (location.hash || "#overview").slice(1);
    return VIEWS[tab] ? tab : "overview";
  }

  function renderTabs() {
    const nav = document.getElementById("tabs");
    // Section navigation: plain links; the active one carries aria-current="page".
    nav.replaceChildren(...TABS.map(([id, label]) => h("a", {
      class: "tab", href: `#${id}`, "aria-current": currentTab() === id ? "page" : null,
    }, [label])));
  }

  function render(keepFocus) {
    const main = document.getElementById("main");
    const focused = keepFocus ? document.activeElement : null;
    const caret = focused && "selectionStart" in focused ? focused.selectionStart : null;
    main.replaceChildren(VIEWS[currentTab()]());
    renderTabs();
    if (keepFocus) {
      const input = main.querySelector('input[type="search"]');
      if (input) { input.focus(); if (caret !== null) input.setSelectionRange(caret, caret); }
    }
  }

  function setupTooltip() {
    const tip = document.getElementById("tooltip");
    const show = (el, x, y) => {
      tip.textContent = el.getAttribute("data-tip");
      tip.hidden = false;
      const r = tip.getBoundingClientRect();
      tip.style.left = `${Math.min(window.innerWidth - r.width - 8, Math.max(8, x + 12))}px`;
      tip.style.top = `${Math.max(8, y - r.height - 10)}px`;
    };
    document.addEventListener("mousemove", (ev) => {
      const el = ev.target.closest && ev.target.closest("[data-tip]");
      if (el) show(el, ev.clientX, ev.clientY); else tip.hidden = true;
    });
    document.addEventListener("focusin", (ev) => {
      const el = ev.target.closest && ev.target.closest("[data-tip]");
      if (el) { const r = el.getBoundingClientRect(); show(el, r.left + r.width / 2, r.top); } else tip.hidden = true;
    });
    document.addEventListener("scroll", () => { tip.hidden = true; }, true);
  }

  function setupTheme() {
    const btn = document.getElementById("theme-btn");
    const order = ["system", "light", "dark"];
    let theme = "system";
    try { theme = localStorage.getItem("va-theme") || "system"; } catch (_) { /* storage unavailable */ }
    const apply = () => {
      if (theme === "system") document.documentElement.removeAttribute("data-theme");
      else document.documentElement.setAttribute("data-theme", theme);
      btn.textContent = `Theme: ${titleCase(theme)}`;
    };
    btn.addEventListener("click", () => {
      theme = order[(order.indexOf(theme) + 1) % order.length];
      try { localStorage.setItem("va-theme", theme); } catch (_) { /* ignore */ }
      apply();
    });
    apply();
  }

  async function start() {
    setupTheme();
    setupTooltip();
    window.addEventListener("hashchange", () => render());
    try {
      if (config.mode !== "demo") throw new Error("This static site only supports demo mode.");
      const response = await fetch(config.snapshotUrl, { cache: "no-cache" });
      if (!response.ok) throw new Error(`could not load the demo snapshot (HTTP ${response.status})`);
      data = await response.json();
      if (!data.meta || data.meta.demo !== true) throw new Error("the snapshot is not marked as demo data");
      document.getElementById("demo-notice").textContent = data.meta.notice;
      document.getElementById("company").textContent = data.meta.company;
      document.getElementById("footer-meta").textContent = `Demo snapshot recorded ${data.meta.recorded_on} from ${data.meta.source}.`;
      render();
    } catch (err) {
      document.getElementById("main").replaceChildren(h("div", { class: "error-box", role: "alert", text: `The dashboard could not start: ${err.message}` }));
    }
  }

  start();
})();
