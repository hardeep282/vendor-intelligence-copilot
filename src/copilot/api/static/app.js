// Day 8 step 7: the minimal UI's only script. Vanilla JS, no build step, no framework -- talks
// directly to this same server's /auth/redeem, /ask and /ask/approve with `fetch`. EventSource
// can't set an Authorization header, so SSE is parsed by hand from a streamed fetch() body;
// that's the one piece of non-obvious plumbing here.

const API_KEY_STORAGE_KEY = "copilot_api_key";

const el = (id) => document.getElementById(id);

function getApiKey() {
  return localStorage.getItem(API_KEY_STORAGE_KEY) || "";
}

function setApiKey(key) {
  localStorage.setItem(API_KEY_STORAGE_KEY, key);
  el("api-key").value = key;
  el("auth-status").textContent = key ? "API key saved (this browser only)." : "";
}

// -- thread_id: one per conversation, so a paused approval-gate run can be resumed against the
// same checkpoint. Persisted in a page-level variable, not localStorage -- a fresh thread per
// tab/reload is the simpler, safer default; "New thread" makes starting over explicit.
let currentThreadId = crypto.randomUUID();

function renderThreadId() {
  el("thread-id").textContent = `thread: ${currentThreadId}`;
}

function resetThread() {
  currentThreadId = crypto.randomUUID();
  renderThreadId();
  el("agent-status").innerHTML = "";
  el("answer-panel").hidden = true;
}

// -- auth panel ----------------------------------------------------------------------------

el("redeem-btn").addEventListener("click", async () => {
  const invite_code = el("invite-code").value.trim();
  const label = el("invite-label").value.trim();
  if (!invite_code || !label) {
    el("auth-status").textContent = "invite code and label are both required";
    return;
  }
  el("auth-status").textContent = "redeeming...";
  try {
    const resp = await fetch("/auth/redeem", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ invite_code, label }),
    });
    const body = await resp.json();
    if (!resp.ok) {
      el("auth-status").textContent = `error: ${body.detail || resp.status}`;
      return;
    }
    setApiKey(body.api_key);
    el("auth-status").textContent = `redeemed -- role: ${body.role}. Key saved.`;
  } catch (err) {
    el("auth-status").textContent = `network error: ${err}`;
  }
});

el("save-key-btn").addEventListener("click", () => {
  setApiKey(el("api-key").value.trim());
});

el("new-thread-btn").addEventListener("click", resetThread);

// -- agent status strip ---------------------------------------------------------------------

const NODE_LABELS = {
  plan: "Planning",
  run_specialist: "Running specialist",
  draft: "Drafting answer",
  verify: "Verifying",
  revise_draft: "Revising draft",
  finalize: "Finalizing",
  guardian: "Guardian review",
  approval_gate: "Approval gate",
};

function appendNodeStatus(node) {
  const strip = el("agent-status");
  // Mark every existing chip as no-longer-current, then add this one as current -- a simple
  // left-to-right trace of what the graph actually ran, in the real execution order LangGraph
  // reported it (same order `stream_mode="updates"` yields -- see the orchestrator's own
  // docstring for how that was confirmed).
  strip.querySelectorAll(".node.current").forEach((n) => n.classList.remove("current"));
  const chip = document.createElement("span");
  chip.className = "node current";
  chip.textContent = NODE_LABELS[node] || node;
  strip.appendChild(chip);
}

// -- rendering the final OrchestratorResult --------------------------------------------------

function renderBadges(result) {
  const badges = el("badges");
  badges.innerHTML = "";
  const add = (cls, text) => {
    const b = document.createElement("span");
    b.className = `badge ${cls}`;
    b.textContent = text;
    badges.appendChild(b);
  };

  if (result.input_gate_verdict && result.input_gate_verdict.outcome === "block") {
    add("blocked", "Blocked by input gate");
    return;
  }
  add(result.verified ? "verified" : "unverified", result.verified ? "Verified" : "Not verified");
  if (result.guardian_verdict) {
    const outcome = result.guardian_verdict.outcome;
    if (outcome === "escalate") add("escalated", "Escalated");
    if (outcome === "block") add("blocked", "Guardian blocked");
  }
  if (result.pending_review) {
    add("escalated", `Pending review: ${result.pending_review.review_id}`);
  }
  if (result.pending_approval) {
    add("pending-approval", "Awaiting approval");
  }
}

function renderCitations(result) {
  const box = el("citations");
  box.innerHTML = "";
  if (!result.results || result.results.length === 0) {
    box.innerHTML = '<p class="hint">No specialist results on this run.</p>';
    return;
  }
  for (const r of result.results) {
    const div = document.createElement("div");
    div.className = "citation";
    const evidence = (r.evidence || []).map((e) => `<li>${escapeHtml(e)}</li>`).join("");
    div.innerHTML = `
      <div><span class="agent-name">${escapeHtml(r.agent)}</span>
        <span class="status-text">(${escapeHtml(r.status)}, confidence: ${escapeHtml(r.confidence)})</span>
      </div>
      <div>${escapeHtml(r.findings)}</div>
      ${evidence ? `<ul class="evidence">${evidence}</ul>` : ""}
    `;
    box.appendChild(div);
  }
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = String(s ?? "");
  return d.innerHTML;
}

function renderResult(result) {
  el("answer-panel").hidden = false;
  el("answer-text").textContent = result.answer || "(no answer text)";
  renderBadges(result);
  renderCitations(result);

  const approvalPanel = el("approval-panel");
  approvalPanel.hidden = !result.pending_approval;
  el("approval-result").textContent = "";
}

// -- /ask: streamed over SSE, parsed by hand (EventSource can't set Authorization) ----------

async function askQuestion(question) {
  const apiKey = getApiKey();
  if (!apiKey) {
    el("agent-status").textContent = "Set an API key first.";
    return;
  }
  el("agent-status").innerHTML = "";
  el("answer-panel").hidden = true;

  const resp = await fetch("/ask", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({ question, thread_id: currentThreadId }),
  });

  if (!resp.ok || !resp.body) {
    let detail = resp.statusText;
    try {
      detail = (await resp.json()).detail || detail;
    } catch {
      /* body wasn't JSON -- keep statusText */
    }
    el("agent-status").textContent = `error ${resp.status}: ${detail}`;
    return;
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line; each frame is "event: <type>\ndata: <json>".
    let boundary;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const lines = frame.split("\n");
      const eventLine = lines.find((l) => l.startsWith("event: "));
      const dataLine = lines.find((l) => l.startsWith("data: "));
      if (!eventLine || !dataLine) continue;
      const type = eventLine.slice("event: ".length);
      const data = JSON.parse(dataLine.slice("data: ".length));
      if (type === "node" && data.node) {
        appendNodeStatus(data.node);
      } else if (type === "result" && data.result) {
        renderResult(data.result);
      }
    }
  }
}

el("ask-btn").addEventListener("click", () => {
  const question = el("question").value.trim();
  if (!question) return;
  askQuestion(question);
});

// -- /ask/approve -----------------------------------------------------------------------------

async function sendApproval(decision) {
  const apiKey = getApiKey();
  const editedAnswer = el("edited-answer").value.trim();
  el("approval-result").textContent = "sending...";
  try {
    const resp = await fetch("/ask/approve", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        thread_id: currentThreadId,
        decision,
        edited_answer: decision === "edit" ? editedAnswer || null : null,
      }),
    });
    const body = await resp.json();
    if (!resp.ok) {
      el("approval-result").textContent = `error: ${body.detail || resp.status}`;
      return;
    }
    el("approval-result").textContent = `decision recorded: ${body.approval_decision}`;
    renderResult(body);
  } catch (err) {
    el("approval-result").textContent = `network error: ${err}`;
  }
}

el("approve-btn").addEventListener("click", () => sendApproval("approve"));
el("edit-btn").addEventListener("click", () => sendApproval("edit"));
el("reject-btn").addEventListener("click", () => sendApproval("reject"));

// -- init ---------------------------------------------------------------------------------

(function init() {
  const stored = getApiKey();
  if (stored) {
    el("api-key").value = stored;
    el("auth-status").textContent = "Using a previously saved API key.";
  }
  renderThreadId();
})();
