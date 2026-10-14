"use strict";

const el = (id) => document.getElementById(id);
let busy = 0;
let shownAll = false;
let lastState = null;
let commandError = "";

function pill(node, text, kind) {
  node.textContent = text;
  node.className = "pill" + (kind ? " " + kind : "");
}

async function post(path, body) {
  busy += 1;
  commandError = "";
  if (lastState) renderState(lastState);
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) commandError = result.error || "Команда не выполнена";
    return result;
  } catch (error) {
    commandError = "Панель не ответила: " + error.message;
    return { ok: false, error: commandError };
  } finally {
    busy -= 1;
    if (lastState) renderState(lastState);
    refresh();
  }
}

function renderCounts(counts, names, labels) {
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
    label.textContent = labels?.[name] || name;
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
  lastState = state;
  const belt = state.conveyor;
  pill(el("belt-state"), belt.running ? "лента работает" : "лента остановлена", belt.running ? "ok" : "");
  el("port").textContent = belt.port || "порт не найден";
  const error = commandError || belt.error;
  el("belt-error").hidden = !error;
  el("belt-error").textContent = error || "";
  const camera = state.camera;
  const report = state.report;
  const canStart = belt.connected && !belt.busy && !belt.status?.stop_pending &&
    !camera.error && camera.fps > 0 && !report?.error;
  el("start").disabled = busy > 0 || !canStart;
  el("stop").disabled = !belt.port;
  el("reset").disabled = busy > 0 || belt.running || belt.busy || Boolean(belt.status?.stop_pending);

  pill(el("cam-state"), camera.error ? "камера: ошибка" : "камера: ок", camera.error ? "bad" : "ok");
  el("fps").textContent = camera.fps ? camera.fps.toFixed(1) + " кадр/с" : "нет кадров";
  el("tracked").textContent = "в кадре: " + camera.in_frame + "  ·  треков: " + state.tracked;
  el("model").textContent = "модель: " + (camera.model || "—") +
    (camera.tracking ? "" : "  ·  трекинг недоступен, классы не считаются");
  el("total").textContent = state.total;
  renderCounts(state.counts, Object.keys(state.counts), state.labels);
  el("team").textContent = report?.team || "отчёты отключены";
  el("report-dir").textContent = report?.directory || "";
  el("report-time").textContent = report?.updated_at ? "Сохранён: " + new Date(report.updated_at).toLocaleString("ru-RU") : "";
  el("report-error").hidden = !report?.error;
  el("report-error").textContent = report?.error || "";
  el("report-links").hidden = !report || Boolean(report.error);
}

async function refresh() {
  if (busy && document.hidden) return;
  try {
    const response = await fetch("/api/state", { cache: "no-store" });
    renderState(await response.json());
  } catch (error) {
    pill(el("belt-state"), "панель недоступна", "bad");
    pill(el("cam-state"), "нет связи с панелью", "bad");
    el("start").disabled = true;
    el("reset").disabled = true;
  }
}

el("start").onclick = () => {
  const speed = Number(el("speed").value);
  if (!Number.isInteger(speed) || Math.abs(speed) < 1 || Math.abs(speed) > 300) {
    commandError = "Введите целую скорость от 1 до 300 по модулю. Ноль не запускает ленту.";
    if (lastState) renderState(lastState);
    return;
  }
  post("/api/start", { speed });
};
el("stop").onclick = () => post("/api/stop");
el("reset").onclick = () => {
  if (confirm("Начать новый прогон? Текущий отчёт останется в папке, счётчики обнулятся. Лента должна быть пустой.")) {
    post("/api/reset");
  }
};

refresh();
setInterval(refresh, 500);
