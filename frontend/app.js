"use strict";

const el = (id) => document.getElementById(id);
let busy = false;
let shownAll = false;

function pill(node, text, kind) {
  node.textContent = text;
  node.className = "pill" + (kind ? " " + kind : "");
}

async function post(path, body) {
  busy = true;
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    return await response.json();
  } catch (error) {
    return { ok: false, error: "Панель не ответила: " + error.message };
  } finally {
    busy = false;
    refresh();
  }
}

function renderCounts(counts, names, total) {
  const table = el("counts");
  table.textContent = "";
  if (!names.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 2;
    cell.className = "muted";
    cell.textContent = "счётчики появятся после первого распознавания";
    row.append(cell);
    return table.append(row);
  }
  // With many model classes show what was actually counted, the rest on demand.
  const counted = names.filter((name) => counts[name]);
  const rest = names.filter((name) => !counts[name]);
  const hidden = rest.length > 8 && !shownAll ? rest.length : 0;
  const rows = hidden ? counted : counted.concat(rest);
  for (const name of rows) {
    const row = document.createElement("tr");
    const label = document.createElement("td");
    label.textContent = name;
    const value = document.createElement("td");
    value.textContent = counts[name] || 0;
    row.append(label, value);
    table.append(row);
  }
  if (hidden && !shownAll) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 2;
    cell.className = "muted";
    cell.style.cursor = "pointer";
    cell.textContent = "показать ещё классы модели: " + hidden;
    cell.onclick = () => { shownAll = true; refresh(); };
    row.append(cell);
    table.append(row);
  }
}

function renderState(state) {
  const belt = state.conveyor;
  pill(el("belt-state"), belt.running ? "лента работает" : "лента остановлена", belt.running ? "ok" : "");
  el("port").textContent = belt.port || "порт не найден";
  const error = belt.error;
  el("belt-error").hidden = !error;
  el("belt-error").textContent = error || "";
  const canStart = belt.connected && !belt.busy;
  el("start").disabled = busy || !canStart;
  el("stop").disabled = busy || !belt.port || belt.busy;

  const camera = state.camera;
  pill(el("cam-state"), camera.error ? "камера: ошибка" : "камера: ок", camera.error ? "bad" : "ok");
  el("fps").textContent = camera.fps ? camera.fps.toFixed(1) + " кадр/с" : "нет кадров";
  el("tracked").textContent = "в кадре: " + camera.detections + "  ·  треков: " + state.tracked;
  el("model").textContent = "модель: " + (camera.model || "—") +
    (camera.tracking ? "" : "  ·  трекинг недоступен, классы не считаются");
  el("total").textContent = state.total;
  renderCounts(state.counts, Object.keys(state.counts));
}

async function refresh() {
  if (busy && document.hidden) return;
  try {
    const response = await fetch("/api/state", { cache: "no-store" });
    renderState(await response.json());
  } catch (error) {
    pill(el("belt-state"), "панель недоступна", "bad");
  }
}

el("start").onclick = () => post("/api/start", { speed: Number(el("speed").value) || 50 });
el("stop").onclick = () => post("/api/stop");
el("reset").onclick = () => {
  if (confirm("Обнулить все счётчики? Делайте это только перед новым прогоном.")) {
    post("/api/reset");
  }
};

refresh();
setInterval(refresh, 500);
