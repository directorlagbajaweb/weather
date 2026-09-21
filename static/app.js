const input = document.getElementById("city-input");
const results = document.getElementById("search-results");
const current = document.getElementById("current");
const hourlyCard = document.getElementById("hourly-chart");
const hourlyCanvas = document.getElementById("hourly-canvas");

const css = getComputedStyle(document.documentElement);
const COLOURS = {
  accent: css.getPropertyValue("--accent").trim(),
  muted: css.getPropertyValue("--muted").trim(),
  grid: css.getPropertyValue("--border").trim(),
};

const mapCard = document.getElementById("map");
const airCard = document.getElementById("air-quality");
const airBody = document.getElementById("air-body");
const advisoryCard = document.getElementById("advisory");
const advisoryBody = document.getElementById("advisory-body");
const activityPills = document.getElementById("activity-pills");
const tabBar = document.getElementById("tab-bar");
const feedRecent = document.getElementById("feed-recent");
const feedRecentCard = document.getElementById("feed-recent-card");
const feedOngoing = document.getElementById("feed-ongoing");
const feedOngoingCard = document.getElementById("feed-ongoing-card");
const searchMessage = document.getElementById("search-message");
const chartStatus = document.getElementById("chart-status");
const chartWrap = document.querySelector(".chart-wrap");
const mapStatus = document.getElementById("map-status");
const leafletMap = document.getElementById("leaflet-map");

let hourlyChart = null;
let map = null;
let marker = null;
let activity = "spraying";

let selected = null;
let debounceTimer = null;

function formatCity(city) {
  return [city.name, city.state, city.country].filter(Boolean).join(", ");
}

function renderResults(cities) {
  results.innerHTML = "";
  cities.forEach((city) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "result";
    item.textContent = formatCity(city);
    item.addEventListener("click", () => selectCity(city));
    results.appendChild(item);
  });
}

async function getJSON(url) {
  const response = await fetch(url);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

function skeleton(classes = "", style = "") {
  return `<div class="skeleton ${classes}"${style ? ` style="${style}"` : ""}></div>`;
}

function skeletonRows(count) {
  return Array.from({ length: count }, () => skeleton("skeleton-row")).join("");
}

function skeletonCurrent() {
  return `
    ${skeleton("skeleton-line short")}
    ${skeleton("skeleton-line tall")}
    ${skeleton("skeleton-line medium")}
    <div class="skeleton-stats">
      ${skeleton()}${skeleton()}${skeleton()}
    </div>`;
}

// A block the same height as the card it stands in, so nothing jumps when
// the real chart or map replaces it.
function skeletonBlock(element) {
  const height = element ? getComputedStyle(element).height : "320px";
  return skeleton("", `height: ${height}`);
}

function showError(container, message, retry) {
  container.innerHTML = "";

  const box = document.createElement("div");
  box.className = "section-error";

  const text = document.createElement("p");
  text.className = "section-error-text";
  text.textContent = message;

  const button = document.createElement("button");
  button.type = "button";
  button.className = "retry";
  button.textContent = "Try again";
  button.addEventListener("click", retry);

  box.append(text, button);
  container.appendChild(box);
}

function stat(label, value) {
  return `<div class="stat">
      <span class="stat-label">${label}</span>
      <span class="stat-value">${value}</span>
    </div>`;
}

function renderCurrent(name, weather) {
  current.innerHTML = `
    <h2 class="current-city">${name}</h2>
    <div class="current-main">
      <img class="current-icon"
           src="https://openweathermap.org/img/wn/${weather.icon}@4x.png"
           alt="${weather.description}">
      <span class="current-temp">${Math.round(weather.temp)}°</span>
    </div>
    <p class="current-description">${weather.description}</p>
    <div class="stats">
      ${stat("Feels like", `${Math.round(weather.feels_like)}°C`)}
      ${stat("Humidity", `${weather.humidity}%`)}
      ${stat("Wind", `${weather.wind_speed} m/s`)}
    </div>`;
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

// The API returns local time with an offset; read it as wall-clock so the
// labels show the city's own hours, not the viewer's.
function formatHour(iso) {
  const local = new Date(`${iso.slice(0, 19)}Z`);
  const hours = String(local.getUTCHours()).padStart(2, "0");
  const minutes = String(local.getUTCMinutes()).padStart(2, "0");
  return `${WEEKDAYS[local.getUTCDay()]} ${hours}:${minutes}`;
}

function renderHourly(series) {
  // Chart.js refuses a canvas that still has a chart attached.
  if (hourlyChart) {
    hourlyChart.destroy();
  }

  hourlyChart = new Chart(hourlyCanvas, {
    type: "line",
    data: {
      labels: series.map((entry) => formatHour(entry.dt)),
      datasets: [
        {
          label: "Temperature",
          data: series.map((entry) => entry.temp),
          borderColor: COLOURS.accent,
          backgroundColor: COLOURS.accent,
          tension: 0.3,
          pointRadius: 0,
          pointHoverRadius: 4,
        },
        {
          label: "Feels like",
          data: series.map((entry) => entry.feels_like),
          borderColor: COLOURS.muted,
          backgroundColor: COLOURS.muted,
          borderDash: [5, 4],
          tension: 0.3,
          pointRadius: 0,
          pointHoverRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          position: "top",
          labels: { color: COLOURS.muted, usePointStyle: true },
        },
        tooltip: {
          callbacks: {
            label: (item) => `${item.dataset.label}: ${item.parsed.y}°C`,
          },
        },
      },
      scales: {
        x: {
          grid: { color: COLOURS.grid },
          ticks: { color: COLOURS.muted, maxRotation: 0, autoSkipPadding: 24 },
        },
        y: {
          grid: { color: COLOURS.grid },
          ticks: { color: COLOURS.muted, callback: (value) => `${value}°C` },
        },
      },
    },
  });

  hourlyCard.hidden = false;
}

const WEATHER_LAYERS = {
  Clouds: "clouds_new",
  Precipitation: "precipitation_new",
  Temperature: "temp_new",
  Wind: "wind_new",
};

function createMap(lat, lon) {
  map = L.map("leaflet-map").setView([lat, lon], 8);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  // Overlays go through our proxy so the API key stays server-side.
  const overlays = {};
  Object.entries(WEATHER_LAYERS).forEach(([label, layer]) => {
    overlays[label] = L.tileLayer(`/api/tiles/${layer}/{z}/{x}/{y}.png`, {
      opacity: 0.6,
    });
  });

  overlays.Clouds.addTo(map);
  // Passed as base layers so the control renders them radio-style.
  L.control.layers(overlays).addTo(map);

  marker = L.marker([lat, lon]).addTo(map);
}

function renderMap(lat, lon) {
  mapCard.hidden = false;

  if (!map) {
    // Leaflet throws if the container already holds a map, so only ever once.
    createMap(lat, lon);
    return;
  }

  map.setView([lat, lon], 8);
  marker.setLatLng([lat, lon]);
  map.invalidateSize();
}

const AQI_TONES = { 1: "good", 2: "good", 3: "warn", 4: "bad", 5: "bad" };

const AQI_ADVICE = {
  1: "Air is clean. Fine for outdoor activity of any length.",
  2: "Air is acceptable. Fine for going outside, though anyone unusually sensitive may notice it on a long or strenuous outing.",
  3: "Moderate pollution. Most people are fine outdoors, but children, older people and anyone with asthma or a heart condition should keep hard exercise short.",
  4: "Poor air. Limit time outdoors and avoid strenuous activity. Sensitive groups should stay inside where possible and keep windows shut.",
  5: "Very poor air. Stay indoors if you can, keep windows shut, and avoid outdoor exercise entirely. Wear a proper mask if you must go out.",
};

const VERDICT_TONES = { go: "good", caution: "warn", "no-go": "bad" };

function renderAir(air) {
  const tone = AQI_TONES[air.aqi] || "warn";
  airBody.innerHTML = `
    <p class="aqi-label ${tone}">${air.aqi_label}</p>
    <p class="aqi-advice">${AQI_ADVICE[air.aqi] || ""}</p>
    <div class="stats">
      ${stat("PM2.5", `${air.pm2_5} µg/m³`)}
      ${stat("PM10", `${air.pm10} µg/m³`)}
      ${stat("Ozone", `${air.o3} µg/m³`)}
    </div>
    <p class="caption">
      PM2.5 is the fine dust measure &mdash; it spikes during harmattan, when dust
      blown down from the Sahara can keep levels high for days.
    </p>`;
  airCard.hidden = false;
}

// Dates arrive as plain YYYY-MM-DD; read them as UTC so the weekday cannot
// shift by a day in a western timezone.
function formatDay(isoDate) {
  const day = new Date(`${isoDate}T00:00:00Z`);
  return `${WEEKDAYS[day.getUTCDay()]} ${day.getUTCDate()}`;
}

function renderAdvisory(rows) {
  advisoryBody.innerHTML = rows
    .map(
      (row) => `
      <div class="advisory-row">
        <span class="advisory-day">${formatDay(row.date)}</span>
        <span class="badge ${VERDICT_TONES[row.verdict] || "warn"}">${row.verdict}</span>
        <span class="advisory-reason">${row.reason}</span>
      </div>`
    )
    .join("");
  advisoryCard.hidden = false;
}

async function loadAdvisory() {
  if (!selected) {
    return;
  }

  advisoryCard.hidden = false;
  advisoryBody.innerHTML = skeletonRows(5);

  try {
    const rows = await getJSON(
      `/api/advisory?lat=${selected.lat}&lon=${selected.lon}&activity=${activity}`
    );
    renderAdvisory(rows);
  } catch (error) {
    console.error(error);
    showError(advisoryBody, "Couldn't load the advisory", loadAdvisory);
  }
}

activityPills.addEventListener("click", (event) => {
  const pill = event.target.closest(".pill");
  if (!pill) {
    return;
  }

  activity = pill.dataset.activity;
  activityPills
    .querySelectorAll(".pill")
    .forEach((button) => button.classList.toggle("is-active", button === pill));
  loadAdvisory();
});

// Chart.js and Leaflet both measure a zero-sized container while their panel
// is hidden, so nudge them once their tab becomes visible.
function showTab(name) {
  tabBar
    .querySelectorAll(".tab")
    .forEach((tab) => tab.classList.toggle("is-active", tab.dataset.tab === name));
  document
    .querySelectorAll(".panel")
    .forEach((panel) =>
      panel.classList.toggle("is-active", panel.id === `panel-${name}`)
    );

  if (name === "map" && map) {
    map.invalidateSize();
  }
  if (name === "forecast" && hourlyChart) {
    hourlyChart.resize();
  }
}

tabBar.addEventListener("click", (event) => {
  const tab = event.target.closest(".tab");
  if (tab) {
    showTab(tab.dataset.tab);
  }
});

// Feed titles come from third-party RSS and JSON, so never trust them as HTML.
function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value == null ? "" : String(value);
  return div.innerHTML;
}

function truncate(text, max = 80) {
  const value = text || "";
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

// Sources disagree on wording ("wildfire" vs "wildfires", "severe storms" vs
// "cyclone"), so fold them into one set of badges.
const FEED_TYPES = {
  earthquake: { label: "Earthquake", tone: "earthquake" },
  flood: { label: "Flood", tone: "flood" },
  drought: { label: "Drought", tone: "drought" },
  wildfire: { label: "Wildfire", tone: "wildfire" },
  wildfires: { label: "Wildfire", tone: "wildfire" },
  cyclone: { label: "Severe storm", tone: "storm" },
  "severe storms": { label: "Severe storm", tone: "storm" },
  volcano: { label: "Volcano", tone: "volcano" },
  volcanoes: { label: "Volcano", tone: "volcano" },
};

function relativeTime(iso) {
  if (!iso) {
    return "";
  }

  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) {
    return "Just now";
  }
  if (minutes < 60) {
    return `${minutes}m ago`;
  }

  const hours = Math.round(minutes / 60);
  if (hours < 24) {
    return `${hours}h ago`;
  }

  const days = Math.round(hours / 24);
  return days === 1 ? "Yesterday" : `${days}d ago`;
}

function measure(item) {
  if (item.magnitude !== null && item.magnitude !== undefined) {
    return `M ${item.magnitude}`;
  }
  if (item.value !== null && item.value !== undefined && item.unit) {
    return `${Math.round(item.value).toLocaleString()} ${item.unit}`;
  }
  return "";
}

function feedRow(item, when) {
  const badge = FEED_TYPES[item.type] || { label: item.type || "Event", tone: "other" };
  const url = item.url || "#";

  return `
    <a class="feed-row" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">
      <span class="feed-type ${badge.tone}">${escapeHtml(badge.label)}</span>
      <span class="feed-main">
        <span class="feed-title">${escapeHtml(truncate(item.title))}</span>
        <span class="feed-location">${escapeHtml(item.location || "")}</span>
      </span>
      <span class="feed-meta">
        <span class="feed-when">${escapeHtml(when)}</span>
        <span class="feed-measure">${escapeHtml(measure(item))}</span>
      </span>
    </a>`;
}

function renderFeedGroup(container, card, items, whenFor) {
  if (!items.length) {
    card.hidden = true;
    return;
  }

  container.innerHTML = items.map((item) => feedRow(item, whenFor(item))).join("");
  card.hidden = false;
}

async function loadFeed() {
  feedRecentCard.hidden = false;
  feedRecent.innerHTML = skeletonRows(5);
  feedOngoingCard.hidden = true;

  try {
    const feed = await getJSON("/api/feed");
    renderFeedGroup(feedRecent, feedRecentCard, feed.recent, (item) =>
      relativeTime(item.time)
    );
    renderFeedGroup(feedOngoing, feedOngoingCard, feed.ongoing, (item) =>
      item.since || ""
    );
  } catch (error) {
    console.error(error);
    showError(feedRecent, "Couldn't load the world feed", loadFeed);
    feedRecentCard.hidden = false;
  }
}

async function loadCurrent(city) {
  current.innerHTML = skeletonCurrent();

  try {
    const weather = await getJSON(
      `/api/weather?lat=${city.lat}&lon=${city.lon}`
    );
    renderCurrent(formatCity(city), weather);
  } catch (error) {
    console.error(error);
    showError(current, "Couldn't load current conditions", () =>
      loadCurrent(city)
    );
  }
}

async function loadHourly(city) {
  hourlyCard.hidden = false;
  chartWrap.hidden = true;
  chartStatus.innerHTML = skeletonBlock(chartWrap);

  try {
    const series = await getJSON(`/api/hourly?lat=${city.lat}&lon=${city.lon}`);
    chartStatus.innerHTML = "";
    chartWrap.hidden = false;
    renderHourly(series);
  } catch (error) {
    console.error(error);
    showError(chartStatus, "Couldn't load the forecast", () => loadHourly(city));
  }
}

async function loadMap(city) {
  mapCard.hidden = false;
  leafletMap.hidden = true;
  mapStatus.innerHTML = skeletonBlock(leafletMap);

  try {
    // Ask the tile proxy for one tile first: if the key or the upstream is
    // down, fail here with a retry rather than leaving a blank grey map.
    const probe = await fetch("/api/tiles/clouds_new/1/1/1.png");
    if (!probe.ok) {
      throw new Error(`Tile server returned ${probe.status}`);
    }

    mapStatus.innerHTML = "";
    leafletMap.hidden = false;
    renderMap(city.lat, city.lon);
  } catch (error) {
    console.error(error);
    showError(mapStatus, "Couldn't load the map", () => loadMap(city));
  }
}

async function loadAir(city) {
  airCard.hidden = false;
  airBody.innerHTML = skeletonRows(3);

  try {
    renderAir(await getJSON(`/api/air?lat=${city.lat}&lon=${city.lon}`));
  } catch (error) {
    console.error(error);
    showError(airBody, "Couldn't load air quality", () => loadAir(city));
  }
}

async function selectCity(city) {
  selected = { lat: city.lat, lon: city.lon };
  results.innerHTML = "";
  searchMessage.innerHTML = "";
  input.value = "";

  // The city-specific tabs only exist once there is a city.
  document.body.classList.remove("no-city");
  showTab("forecast");

  // Fired independently, so one failing section cannot blank the others.
  loadCurrent(city);
  loadHourly(city);
  loadMap(city);
  loadAir(city);
  loadAdvisory();
}

async function runSearch(query) {
  searchMessage.innerHTML = "";

  try {
    const cities = await getJSON(`/api/search?q=${encodeURIComponent(query)}`);

    if (!cities.length) {
      results.innerHTML = "";
      searchMessage.textContent = "No cities found";
      return;
    }

    renderResults(cities);
  } catch (error) {
    console.error(error);
    results.innerHTML = "";
    showError(searchMessage, "Couldn't search for cities", () =>
      runSearch(query)
    );
  }
}

input.addEventListener("input", () => {
  clearTimeout(debounceTimer);
  const query = input.value.trim();

  if (!query) {
    results.innerHTML = "";
    searchMessage.innerHTML = "";
    return;
  }

  debounceTimer = setTimeout(() => runSearch(query), 400);
});

// Nothing is selected on load: show the world feed on its own.
document.body.classList.add("no-city");
showTab("world");
loadFeed();
