const ORDER = [
  "drawdown",
  "weekly_rsi",
  "vix",
  "ma200",
  "daily_rsi",
  "fear_greed",
];

let radarChart;
let historyChart;

function $(id) {
  return document.getElementById(id);
}

function fmt(n, d = 1) {
  return Number(n).toLocaleString("ko-KR", {
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  });
}

function zoneClass(key) {
  document.body.classList.remove("zone-buy", "zone-event", "zone-worry", "zone-wait");
  document.body.classList.add(`zone-${key}`);
}

function renderBars(components) {
  $("bars").innerHTML = components
    .map((c) => {
      const pct = Math.max(0, Math.min(100, c.cell));
      return `<div class="bar-row">
        <span>${c.label}</span>
        <div class="bar-track"><span style="width:${pct}%"></span></div>
        <strong>${fmt(c.contribution, 1)}점</strong>
      </div>`;
    })
    .join("");
}

function renderCards(components) {
  $("cards").innerHTML = components
    .map(
      (c) => `<article>
        <h3>${c.label} · ${Math.round(c.weight * 100)}%</h3>
        <p class="cell-num">${fmt(c.cell, 0)}</p>
        <p class="cell-sub">${c.detail}</p>
        <div class="meter"><span style="width:${Math.max(0, Math.min(100, c.cell))}%"></span></div>
      </article>`
    )
    .join("");
}

function renderTable(id, rows) {
  const el = $(id);
  if (!rows.length) {
    el.innerHTML = `<tr><td colspan="3">해당 기간에 없습니다.</td></tr>`;
    return;
  }
  el.innerHTML = rows
    .slice()
    .reverse()
    .map(
      (r) =>
        `<tr><td>${r.date}</td><td>${fmt(r.score, 1)}</td><td>${fmt(r.tqqq, 2)}</td></tr>`
    )
    .join("");
}

function renderWait(wait) {
  const days = $("wait-days");
  days.innerHTML = [1, 2, 3, 4, 5]
    .map((n) => `<span class="${wait && wait.days >= n ? "done" : ""}">${n}일</span>`)
    .join("");
  if (!wait) {
    $("wait-copy").textContent = "지금은 90점 구간이 아닙니다.";
    return;
  }
  $("wait-copy").textContent = wait.label;
}

function renderRadar(cells) {
  const data = ORDER.map((k) => cells[k]);
  const labels = ["고점 대비", "주간 RSI", "VIX", "200일선", "일간 RSI", "공포탐욕"];
  const ctx = $("radar").getContext("2d");
  if (radarChart) radarChart.destroy();
  radarChart = new Chart(ctx, {
    type: "radar",
    data: {
      labels,
      datasets: [
        {
          data,
          borderColor: "#e2c36b",
          backgroundColor: "rgba(226, 195, 107, 0.22)",
          pointBackgroundColor: "#e2c36b",
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: { legend: { display: false } },
      scales: {
        r: {
          min: 0,
          max: 100,
          ticks: { display: false },
          grid: { color: "rgba(140, 196, 180, 0.18)" },
          angleLines: { color: "rgba(140, 196, 180, 0.18)" },
          pointLabels: { color: "#e7f2ee", font: { size: 12 } },
        },
      },
    },
  });
}

function renderHistory(history) {
  const rows = history.filter((h) => h.date >= "2023-01-01");
  const ctx = $("history").getContext("2d");
  if (historyChart) historyChart.destroy();
  historyChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: rows.map((h) => h.date),
      datasets: [
        {
          label: "웅덩이 매수 신호지수",
          data: rows.map((h) => h.score),
          borderColor: "#e2c36b",
          backgroundColor: "rgba(226, 195, 107, 0.12)",
          fill: true,
          tension: 0.2,
          pointRadius: 0,
          borderWidth: 2,
        },
        {
          label: "90점 이상",
          data: rows.map((h) => (h.score >= 90 ? h.score : null)),
          borderColor: "#e23b3b",
          backgroundColor: "#e23b3b",
          spanGaps: false,
          tension: 0.2,
          pointRadius: rows.map((h) => (h.score >= 90 ? 2 : 0)),
          pointHoverRadius: 4,
          borderWidth: 3,
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          ticks: { color: "#8aa39a", maxTicksLimit: 8 },
          grid: { color: "rgba(140, 196, 180, 0.08)" },
        },
        y: {
          min: 0,
          max: 100,
          ticks: { color: "#8aa39a" },
          grid: { color: "rgba(140, 196, 180, 0.08)" },
        },
      },
    },
    plugins: [
      {
        id: "thresholds",
        beforeDraw(chart) {
          const { ctx: c, chartArea, scales } = chart;
          if (!chartArea) return;
          [
            [70, "#e2c36b"],
            [80, "#d98a3a"],
            [90, "#d45b4a"],
          ].forEach(([y, color]) => {
            const py = scales.y.getPixelForValue(y);
            c.save();
            c.strokeStyle = color;
            c.globalAlpha = 0.55;
            c.setLineDash([5, 5]);
            c.beginPath();
            c.moveTo(chartArea.left, py);
            c.lineTo(chartArea.right, py);
            c.stroke();
            c.restore();
          });
        },
      },
    ],
  });
}

function render(data) {
  zoneClass(data.zone.key);
  $("ring").style.setProperty("--p", data.score);
  $("score").textContent = String(data.score_int);
  $("delta").textContent =
    data.score_delta == null
      ? "전일 대비 없음"
      : `전일 대비 ${data.score_delta > 0 ? "+" : ""}${fmt(data.score_delta, 1)}점`;
  $("zone").textContent = data.zone.label;
  $("hint").textContent = data.zone.hint;
  $("asof").textContent = `기준 ${data.as_of_label} · 갱신 ${data.fetched_at_kst}`;
  $("tqqq").textContent = `$${fmt(data.tqqq, 2)}`;
  $("qqq-dd").textContent =
    data.qqq_drawdown_pct == null ? "--" : `${fmt(data.qqq_drawdown_pct, 1)}%`;
  $("cnn").textContent = fmt(data.raw.fear_greed, 1);
  $("updated").textContent = data.fetched_at_kst;
  $("disclaimer").textContent = `${data.disclaimer} ${data.formula_note}`;

  const broken = data.rate.broken;
  $("rate-flag").textContent = broken ? "금리 꺾임" : "아직 안 꺾임";
  $("rate-flag").className = `rate-flag ${broken ? "on" : "off"}`;
  $("rate-now").textContent = `${fmt(data.rate.yield_10y, 3)}%`;
  $("rate-high").textContent = `${fmt(data.rate.high_3m, 3)}%`;
  $("rate-sma").textContent = `${fmt(data.rate.sma50, 3)}%`;

  renderWait(data.wait);
  renderBars(data.components);
  renderCards(data.components);
  renderRadar(data.cells);
  renderHistory(data.history);
  renderTable("ev90", data.events_90);
  renderTable("ev80", data.events_80);
}

function msUntilKstEight() {
  const offset = 9 * 60 * 60 * 1000;
  const view = new Date(Date.now() + offset);
  const next = new Date(view);
  next.setUTCHours(8, 0, 0, 0);
  if (view.getTime() >= next.getTime()) next.setUTCDate(next.getUTCDate() + 1);
  return next.getTime() - view.getTime();
}

function load() {
  if (!window.__SNAPSHOT) return;
  render(window.__SNAPSHOT);
  const wait = msUntilKstEight();
  setTimeout(() => {
    const top = window.parent && window.parent !== window ? window.parent : window;
    top.location.reload();
  }, wait);
}

load();
