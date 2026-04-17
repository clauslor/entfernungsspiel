let ws;
let playerName = "";
let currentGameId = "";
let currentPlayerId = "";
let currentPlayers = [];
let currentGameStatus = "waiting";
let currentSettingsLocked = false;
let currentIsHost = false;
let totalTime;
let isConnected = false;
let restorePendingJoinGameId = "";
let gameMap = null;
let gameMapBaseLayer = null;
let gameMapFallbackLayer = null;
let gameMapFeatureLayer = null;
let gameMapFeatureSource = null;
let gameMapResizeObserver = null;
let pendingMapPreparationTimeoutId = null;
let pendingQuestionCoordinates = null;
let countdownTimerId = null;
let countdownEndTime = null;
let countdownRemainingSeconds = 0;
let answerHintTimerId = null;
let guessSubmissionPending = false;
let guessLockedForRound = false;
let currentRoundNumber = null;
let currentMaxRounds = null;

const DEFAULT_MAP_VIEW = {
  center: [51.1657, 10.4515],
  zoom: 4,
};

const STORAGE_KEYS = {
  PLAYER_NAME: "entfernungsspiel.playerName",
  PLAYER_ID: "entfernungsspiel.playerId",
  GAME_ID: "entfernungsspiel.gameId",
};

// Initialize i18n system on page load
document.addEventListener("DOMContentLoaded", async () => {
  await initializeI18n();
  updateUILanguage();
  connect();
});

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }

  const base = window.location.pathname.replace(/\/$/, ""); // trailing slash entfernen
  const storedPlayerId = localStorage.getItem(STORAGE_KEYS.PLAYER_ID);
  const playerParam = storedPlayerId
    ? `?player_id=${encodeURIComponent(storedPlayerId)}`
    : "";
  ws = new WebSocket(`wss://${window.location.host}/ws${playerParam}`);

  ws.onmessage = (event) => {
    const data = event.data;
    try {
      const msg = JSON.parse(data);
      handleJsonMessage(msg);
    } catch {
      appendMessage(data);
    }
  };

  ws.onopen = () => {
    isConnected = true;
    appendMessage(`✅ ${t("messages.ready")}`);
    sendMessage({ type: "tab_active", data: {} });
    restoreSessionFromStorage();
  };

  ws.onclose = () => {
    isConnected = false;
    appendMessage(`❌ ${t("messages.disconnected")}`);
    setTimeout(connect, 2000); // Reconnect after 2 seconds
  };

  ws.onerror = (error) => {
    appendMessage(`❌ ${t("messages.connectionError")}`);
    console.error("WebSocket error:", error);
  };
}

function updateUILayout() {
  const layout = document.querySelector("main.game-layout");
  const inGame = Boolean(currentGameId);
  const roundActiveStatuses = new Set(["active", "playing", "warmup"]);
  const roundActive = inGame && roundActiveStatuses.has((currentGameStatus || "").toLowerCase());

  const lobbyControls = document.getElementById("lobbyControls");
  const matchControls = document.getElementById("matchControls");
  const lobbyGuideCard = document.getElementById("lobbyGuideCard");
  const countdownCard = document.getElementById("countdownCard");
  const rulesCard = document.getElementById("rulesCard");
  const playersCard = document.getElementById("playersCard");
  const answerCard = document.getElementById("answerCard");
  const questionCard = document.getElementById("questionCard");

  if (layout) {
    layout.classList.toggle("lobby-mode", !inGame);
    layout.classList.toggle("in-game", inGame);
    layout.classList.toggle("round-active", roundActive);
    layout.classList.toggle("pre-round", inGame && !roundActive);
  }

  if (lobbyControls) {
    lobbyControls.style.display = inGame ? "none" : "block";
  }
  if (matchControls) {
    matchControls.style.display = inGame ? "block" : "none";
  }
  if (lobbyGuideCard) {
    lobbyGuideCard.style.display = inGame ? "none" : "block";
  }

  if (countdownCard) {
    countdownCard.style.display = inGame ? "block" : "none";
  }
  if (rulesCard) {
    rulesCard.style.display = inGame && !roundActive ? "block" : "none";
  }
  if (playersCard) {
    playersCard.style.display = inGame ? "block" : "none";
  }

  if (answerCard) {
    answerCard.style.display = roundActive ? "block" : "none";
  }

  if (questionCard) {
    questionCard.style.display = roundActive ? "block" : "none";
  }

  if (roundActive) {
    setTimeout(() => focusAndSelect("guessInput"), 0);
    queueMapPreparation();
  }

  updateMatchHud();
}

function getLocalizedPhaseLabel() {
  const status = (currentGameStatus || "waiting").toLowerCase();
  if (!currentGameId) return t("hud.phases.lobby");
  if (["active", "playing", "warmup"].includes(status)) return t("hud.phases.active");
  if (status === "countdown") return t("hud.phases.countdown");
  if (status === "finished") return t("hud.phases.finished");
  return t("hud.phases.waiting");
}

function updateMatchHud() {
  const hud = document.getElementById("matchHud");
  if (!hud) return;

  const phaseEl = document.getElementById("hudPhase");
  const gameEl = document.getElementById("hudGame");
  const roundEl = document.getElementById("hudRound");
  const countdownEl = document.getElementById("hudCountdown");

  let countdownValue = "--:--";
  const countdownDisplay = document.getElementById("countdown");
  if (countdownDisplay && countdownDisplay.textContent && countdownDisplay.textContent.trim()) {
    countdownValue = countdownDisplay.textContent.trim();
  }

  if (phaseEl) phaseEl.textContent = getLocalizedPhaseLabel();
  if (gameEl) gameEl.textContent = currentGameId || "-";
  if (roundEl) {
    roundEl.textContent = currentRoundNumber && currentMaxRounds
      ? `${currentRoundNumber}/${currentMaxRounds}`
      : "-";
  }
  if (countdownEl) countdownEl.textContent = currentGameId ? countdownValue : "--:--";
}

function translateServerMessage(rawMessage) {
  if (!rawMessage || typeof rawMessage !== "string") {
    return t("serverErrors.generic");
  }

  const exactMap = {
    "Unknown message type": "serverErrors.unknownMessageType",
    "Invalid message format": "serverErrors.invalidMessageFormat",
    "Invalid JSON": "serverErrors.invalidJson",
    "Internal server error": "serverErrors.internalServerError",
    "Invalid game creation data": "serverErrors.invalidGameCreationData",
    "Invalid PIN": "serverErrors.invalidPin",
    "Host has locked the lobby": "serverErrors.hostLockedLobby",
    "Invalid game join data": "serverErrors.invalidGameJoinData",
    "Player not registered": "serverErrors.playerNotRegistered",
    "Invalid name format": "serverErrors.invalidNameFormat",
    "Error setting name": "serverErrors.errorSettingName",
    "Invalid ready status": "serverErrors.invalidReadyStatus",
    "Invalid kick request": "serverErrors.invalidKickRequest",
    "You are not in a game": "serverErrors.notInGame",
    "Only host can kick players": "serverErrors.onlyHostKick",
    "Players can only be kicked before countdown": "serverErrors.kickBeforeCountdown",
    "Host cannot kick themselves": "serverErrors.hostCannotKickSelf",
    "Player not found in this game": "serverErrors.playerNotFoundInGame",
    "Invalid lock settings request": "serverErrors.invalidLockSettingsRequest",
    "Only host can lock settings": "serverErrors.onlyHostLockSettings",
    "Invalid update settings request": "serverErrors.invalidUpdateSettingsRequest",
    "Only host can update settings": "serverErrors.onlyHostUpdateSettings",
    "Settings can only be changed before countdown": "serverErrors.settingsOnlyBeforeCountdown",
    "Settings are locked": "serverErrors.settingsLocked",
    "Invalid settings values": "serverErrors.invalidSettingsValues",
    "Only host can start warmup": "serverErrors.onlyHostStartWarmup",
    "Warmup only available before countdown": "serverErrors.warmupOnlyBeforeCountdown",
    "Could not start warmup": "serverErrors.couldNotStartWarmup",
    "No active question": "serverErrors.noActiveQuestion",
    "Not in a game": "serverErrors.notInGame",
    "Invalid answer format": "serverErrors.invalidAnswerFormat",
    "Failed to start game": "serverErrors.failedToStartGame",
    "You were removed by the host": "serverErrors.removedByHost",
  };

  if (exactMap[rawMessage]) {
    return t(exactMap[rawMessage]);
  }

  const gameNotFoundMatch = rawMessage.match(/^Game\s+(.+)\s+not found$/);
  if (gameNotFoundMatch) {
    return t("serverErrors.gameNotFound", { gameId: gameNotFoundMatch[1] });
  }

  const cannotJoinMatch = rawMessage.match(/^Cannot join game\s+(.+)$/);
  if (cannotJoinMatch) {
    return t("serverErrors.cannotJoinGame", { gameId: cannotJoinMatch[1] });
  }

  const gameErrorMatch = rawMessage.match(/^Game error:\s*(.+)$/);
  if (gameErrorMatch) {
    return t("serverErrors.gameError", { details: gameErrorMatch[1] });
  }

  return rawMessage;
}

function isMapContainerReady(container) {
  if (!container) return false;

  // Ensure element is attached to DOM and not explicitly hidden.
  if (!document.body.contains(container)) {
    return false;
  }

  const styles = window.getComputedStyle(container);
  if (styles.display === "none" || styles.visibility === "hidden") {
    return false;
  }

  const rect = container.getBoundingClientRect();
  // Keep threshold permissive so small/transitioning layouts do not block map startup.
  return rect.width >= 40 && rect.height >= 40;
}

function queueMapPreparation(attempt = 0) {
  if (pendingMapPreparationTimeoutId) {
    clearTimeout(pendingMapPreparationTimeoutId);
    pendingMapPreparationTimeoutId = null;
  }

  // First attempt should be immediate, subsequent attempts with backoff.
  // Keep retry window long enough for slower devices/layout reflows.
  const delayMs = attempt === 0 ? 10 : Math.min(150, 25 + attempt * 10);

  pendingMapPreparationTimeoutId = setTimeout(() => {
    pendingMapPreparationTimeoutId = null;

    const container = document.getElementById("mapContainer");
    if (!isMapContainerReady(container)) {
      if (attempt < 40) {
        queueMapPreparation(attempt + 1);
      } else {
        console.warn("[Map] Map preparation timeout after 40 attempts");
      }
      return;
    }

    prepareMapForGameplay();
    scheduleLeafletResize();
    
    // Render the map immediately after map is ready
    if (pendingQuestionCoordinates) {
      renderQuestionMap(pendingQuestionCoordinates);
    }
  }, delayMs);
}

function prepareMapForGameplay() {
  const map = ensureLeafletMap();
  if (!map) {
    console.warn("[Map] ensureLeafletMap returned null, cannot prepare map");
    return;
  }

  // Sanity check: if gameMapFeatureSource is still null after ensureLeafletMap, 
  // there's an initialization issue, bail out
  if (!gameMapFeatureSource) {
    console.error("[Map] gameMapFeatureSource is null after ensureLeafletMap initialization");
    return;
  }

  // If no features yet, center map on default location
  if (gameMapFeatureSource.getFeatures().length === 0) {
    const center25832 = ol.proj.transform(
      [DEFAULT_MAP_VIEW.center[1], DEFAULT_MAP_VIEW.center[0]],
      "EPSG:4326",
      "EPSG:25832",
    );
    map.getView().setCenter(center25832);
    map.getView().setZoom(6);
  }
}

function redrawLeafletMap() {
  if (!gameMap) return;
  try {
    gameMap.updateSize();
  } catch (err) {
    console.warn("[Map] Error during map resize:", err);
  }
}

let resizeDebounceTimer = null;

function scheduleLeafletResize() {
  if (!gameMap) return;

  // Clear any pending resize operation
  if (resizeDebounceTimer) {
    clearTimeout(resizeDebounceTimer);
  }

  // First update immediately to catch synchronous layout changes
  gameMap.updateSize();

  // Then schedule a second update after a short delay to catch cascading reflows
  resizeDebounceTimer = setTimeout(() => {
    if (gameMap) {
      gameMap.updateSize();
    }
    resizeDebounceTimer = null;
  }, 150);
}

function attachLeafletResizeObserver(container) {
  if (!container || gameMapResizeObserver || typeof ResizeObserver === "undefined") {
    return;
  }

  gameMapResizeObserver = new ResizeObserver((entries) => {
    for (const entry of entries) {
      if (entry.target !== container) continue;
      const { width, height } = entry.contentRect;
      if (width > 0 && height > 0) {
        scheduleLeafletResize();
      }
    }
  });

  gameMapResizeObserver.observe(container);
}

function focusAndSelect(elementId) {
  const element = document.getElementById(elementId);
  if (!element) return;
  element.focus();
  if (typeof element.select === "function") {
    element.select();
  }
}

function shouldIgnoreGlobalShortcut(event) {
  const tagName = event.target?.tagName;
  return tagName === "INPUT" || tagName === "TEXTAREA" || event.ctrlKey || event.metaKey || event.altKey;
}

function clearCountdownTimer() {
  if (countdownTimerId) {
    clearInterval(countdownTimerId);
    countdownTimerId = null;
  }
}

function renderCountdownValue(totalSeconds) {
  const safeSeconds = Math.max(0, totalSeconds);
  const minutes = Math.floor(safeSeconds / 60);
  const seconds = safeSeconds % 60;
  document.getElementById("countdown").textContent =
    `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  updateMatchHud();
}

function startManagedCountdown(totalSeconds) {
  clearCountdownTimer();

  countdownRemainingSeconds = Math.max(0, Number(totalSeconds) || 0);
  countdownEndTime = Date.now() + countdownRemainingSeconds * 1000;
  renderCountdownValue(countdownRemainingSeconds);

  countdownTimerId = setInterval(() => {
    const remaining = Math.max(0, Math.ceil((countdownEndTime - Date.now()) / 1000));
    countdownRemainingSeconds = remaining;
    renderCountdownValue(remaining);

    if (remaining <= 0) {
      clearCountdownTimer();
      document.getElementById("countdown").textContent = t("countdown.timesUp");
      updateMatchHud();
    }
  }, 250);
}

function pauseManagedCountdown(remainingSeconds) {
  clearCountdownTimer();
  countdownRemainingSeconds = Math.max(0, Number(remainingSeconds) || countdownRemainingSeconds || 0);
  renderCountdownValue(countdownRemainingSeconds);
}

function resetCountdownDisplay(labelText = t("countdown.waiting")) {
  clearCountdownTimer();
  countdownEndTime = null;
  countdownRemainingSeconds = 0;
  document.getElementById("countdownText").textContent = labelText;
  document.getElementById("countdown").textContent = "--:--";
  updateMatchHud();
}

function setGuessControlsDisabled(disabled) {
  const guessInput = document.getElementById("guessInput");
  const submitButton = document.getElementById("submitGuessBtn");
  if (guessInput) {
    guessInput.disabled = disabled;
  }
  if (submitButton) {
    submitButton.disabled = disabled;
  }
}

function showAnswerSubmissionHint(text, variant = "pending", autoHideMs = 0) {
  const hint = document.getElementById("answerSubmissionHint");
  if (!hint) return;

  if (answerHintTimerId) {
    clearTimeout(answerHintTimerId);
    answerHintTimerId = null;
  }

  hint.textContent = text;
  hint.classList.remove("is-pending", "is-success", "is-error", "is-visible");
  hint.classList.add("is-visible");

  if (variant === "success") {
    hint.classList.add("is-success");
  } else if (variant === "error") {
    hint.classList.add("is-error");
  } else {
    hint.classList.add("is-pending");
  }

  if (autoHideMs > 0) {
    answerHintTimerId = setTimeout(() => {
      clearAnswerSubmissionHint();
    }, autoHideMs);
  }
}

function clearAnswerSubmissionHint() {
  const hint = document.getElementById("answerSubmissionHint");
  if (!hint) return;

  if (answerHintTimerId) {
    clearTimeout(answerHintTimerId);
    answerHintTimerId = null;
  }

  hint.textContent = "";
  hint.classList.remove("is-pending", "is-success", "is-error", "is-visible");
}

function resetAnswerSubmissionState() {
  guessSubmissionPending = false;
  guessLockedForRound = false;
  setGuessControlsDisabled(false);
  clearAnswerSubmissionHint();
}

function formatSubmissionTime(isoValue) {
  if (!isoValue) return "-";

  const parsed = new Date(isoValue);
  if (Number.isNaN(parsed.getTime())) {
    return isoValue;
  }

  return parsed.toLocaleTimeString("de-DE", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function renderRoundHistory(roundHistory) {
  const list = document.getElementById("roundReviewList");
  if (!list) return;

  list.innerHTML = "";

  if (!roundHistory || roundHistory.length === 0) {
    const empty = document.createElement("p");
    empty.className = "round-review-meta";
    empty.textContent = t("gameEnd.noDetailsAvailable");
    list.appendChild(empty);
    return;
  }

  roundHistory.forEach((round) => {
    const card = document.createElement("section");
    card.className = "round-review-card";

    const question = document.createElement("div");
    question.className = "round-review-question";
    question.textContent = `Runde ${round.round}: ${round.question}`;

    const solution = document.createElement("div");
    solution.className = "round-review-solution";
    solution.innerHTML = `✅ <strong>Richtige Antwort: ${round.correct_distance} km</strong> | 🏆 Gewinner: ${round.winner}`;

    card.appendChild(question);
    card.appendChild(solution);

    (round.submissions || []).forEach((submission) => {
      const playerBlock = document.createElement("div");
      playerBlock.className = "round-review-player";

      const playerName = document.createElement("div");
      playerName.className = "round-review-player-name";
      playerName.textContent = submission.player_name;

      const finalEntry = document.createElement("div");
      finalEntry.className = "round-review-player-final";
      if (submission.final_guess === null || submission.final_guess === undefined) {
        finalEntry.textContent = t("gameEnd.noValidAnswer");
      } else {
        finalEntry.textContent = `Gewertet wurde: ${submission.final_guess} km um ${formatSubmissionTime(submission.final_submitted_at)}`;
      }

      const logList = document.createElement("ul");
      logList.className = "round-review-answer-log";

      const receivedAnswers = submission.received_answers || [];
      if (receivedAnswers.length === 0) {
        const none = document.createElement("li");
        none.textContent = t("gameEnd.noAnswersSent");
        logList.appendChild(none);
      } else {
        receivedAnswers.forEach((answer, index) => {
          const item = document.createElement("li");
          const prefix = index === receivedAnswers.length - 1 ? "Letzte Antwort" : `Antwort ${index + 1}`;
          item.textContent = `${prefix}: ${answer.guess} km um ${formatSubmissionTime(answer.submitted_at)}`;
          logList.appendChild(item);
        });
      }

      playerBlock.appendChild(playerName);
      playerBlock.appendChild(finalEntry);
      playerBlock.appendChild(logList);
      card.appendChild(playerBlock);
    });

    list.appendChild(card);
  });
}

function createOrtsschildSvgDataUri(cityName) {
  const label = escapeXml(formatCityLabel(cityName));
  const svg = `
<svg xmlns="http://www.w3.org/2000/svg" width="190" height="64" viewBox="0 0 190 64" role="img" aria-label="Ortsschild ${label}">
  <rect x="4" y="4" width="150" height="40" rx="2" fill="#facc15" stroke="#111827" stroke-width="4"/>
  <rect x="0" y="44" width="8" height="20" rx="1" fill="#475569"/>
  <rect x="150" y="44" width="8" height="20" rx="1" fill="#475569"/>
  <text x="79" y="31" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="17" font-weight="700" fill="#111827">${label}</text>
</svg>`.trim();

  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
}

function ensureLeafletMap() {
  const container = document.getElementById("mapContainer");
  if (!container || typeof ol === "undefined" || typeof proj4 === "undefined") {
    return null;
  }

  if (!isMapContainerReady(container)) {
    return null;
  }

  attachLeafletResizeObserver(container);

  if (!gameMap) {
    try {
      proj4.defs("EPSG:25832", "+proj=utm +zone=32 +ellps=GRS80 +units=m +no_defs");
      if (ol.proj.proj4 && typeof ol.proj.proj4.register === "function") {
        ol.proj.proj4.register(proj4);
      }

      let projection25832 = ol.proj.get("EPSG:25832");
      if (!projection25832) {
        projection25832 = new ol.proj.Projection({
          code: "EPSG:25832",
          units: "m",
          extent: [200000, 5200000, 1000000, 6200000],
        });
        ol.proj.addProjection(projection25832);
      }

      if (!ol.proj.get("EPSG:25832")) {
        console.error("[Map] EPSG:25832 projection registration failed");
        return null;
      }
    } catch (err) {
      console.error("[Map] Error setting up EPSG:25832 projection:", err);
      return null;
    }

    gameMapBaseLayer = new ol.layer.Tile({
      source: new ol.source.XYZ({
        // basemap.de Web Raster with OSM fallback
        url: "https://sgx.geodatenzentrum.de/wmts_basemapde/tile/1.0.0/de_basemapde_web_raster_farbe/default/GLOBAL_WEBMERCATOR/{z}/{y}/{x}.png",
        attributions: "© basemap.de / BKG, © OpenStreetMap contributors",
        crossOrigin: "anonymous",
        imageSmoothing: true,
      }),
    });

    // Add fallback layer (OSM) that will be used if basemap.de fails
    gameMapFallbackLayer = new ol.layer.Tile({
      source: new ol.source.OSM({
        attributions: "© OpenStreetMap contributors",
        crossOrigin: "anonymous",
        imageSmoothing: true,
      }),
      visible: false,
      zIndex: 0,
    });


    gameMapFeatureSource = new ol.source.Vector();
    gameMapFeatureLayer = new ol.layer.Vector({
      source: gameMapFeatureSource,
    });

    gameMap = new ol.Map({
      target: container,
      layers: [gameMapBaseLayer, gameMapFallbackLayer, gameMapFeatureLayer],
      controls: ol.control.defaults().extend([
        new ol.control.ScaleLine({
          units: "metric",
          bar: true,
          text: true,
          minWidth: 120,
        }),
      ]),
      view: new ol.View({
        projection: projection25832,
        center: ol.proj.transform(
          [DEFAULT_MAP_VIEW.center[1], DEFAULT_MAP_VIEW.center[0]],
          "EPSG:4326",
          "EPSG:25832",
        ),
        zoom: 6,
        minZoom: 4,
        maxZoom: 18,
      }),
    });

    // Handle basemap.de tile load failure: switch to OSM fallback
    gameMapBaseLayer.on("error", () => {
      if (gameMapFallbackLayer) {
        gameMapBaseLayer.setVisible(false);
        gameMapFallbackLayer.setVisible(true);
        console.warn("[Map] basemap.de tiles failed to load, switched to OSM fallback");
      }
    });

  }

  container.classList.add("has-map");
  scheduleLeafletResize();

  return gameMap;
}

function escapeXml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatCityLabel(cityName, maxLength = 18) {
  const safeName = String(cityName || "").trim();
  if (safeName.length <= maxLength) {
    return safeName;
  }
  return `${safeName.slice(0, maxLength - 1)}…`;
}

function createOrtsschildIcon(cityName) {
  return new ol.style.Style({
    image: new ol.style.Icon({
      src: createOrtsschildSvgDataUri(cityName),
      anchor: [0.5, 1],
      anchorXUnits: "fraction",
      anchorYUnits: "fraction",
      imgSize: [190, 64],
      scale: 0.84,
    }),
  });
}

function renderQuestionMap(coordinates) {
  const container = document.getElementById("mapContainer");

  if (!coordinates || !coordinates.from || !coordinates.to) {
    pendingQuestionCoordinates = null;
    if (container) {
      container.classList.remove("has-map");
    }
    return;
  }

  const map = ensureLeafletMap();
  if (!map || !gameMapFeatureSource) {
    // Only cache if not already cached (avoid redundant retries with same data)
    if (!pendingQuestionCoordinates) {
      pendingQuestionCoordinates = coordinates;
      queueMapPreparation();
    }
    return;
  }

  pendingQuestionCoordinates = null;

  gameMapFeatureSource.clear();

  try {
    const fromPoint = ol.proj.transform(
      [coordinates.from.lon, coordinates.from.lat],
      "EPSG:4326",
      "EPSG:25832",
    );
    const toPoint = ol.proj.transform(
      [coordinates.to.lon, coordinates.to.lat],
      "EPSG:4326",
      "EPSG:25832",
    );

    const fromFeature = new ol.Feature({ geometry: new ol.geom.Point(fromPoint) });
    fromFeature.setStyle(createOrtsschildIcon(coordinates.from.name));

    const toFeature = new ol.Feature({ geometry: new ol.geom.Point(toPoint) });
    toFeature.setStyle(createOrtsschildIcon(coordinates.to.name));

    const lineFeature = new ol.Feature({ geometry: new ol.geom.LineString([fromPoint, toPoint]) });
    lineFeature.setStyle(
      new ol.style.Style({
        stroke: new ol.style.Stroke({
          color: "#16a34a",
          width: 4,
        }),
      }),
    );

    gameMapFeatureSource.addFeatures([lineFeature, fromFeature, toFeature]);

    const extent = gameMapFeatureSource.getExtent();
    map.getView().fit(extent, {
      padding: [24, 24, 24, 24],
      duration: 0,
      maxZoom: 12,
    });
    scheduleLeafletResize();

    setTimeout(() => {
      if (gameMap && gameMapFeatureSource.getFeatures().length > 0) {
        const extent = gameMapFeatureSource.getExtent();
        gameMap.getView().fit(extent, {
          padding: [24, 24, 24, 24],
          duration: 0,
          maxZoom: 12,
        });
      }
    }, 160);
  } catch (err) {
    console.error("[Map] Error rendering question map:", err);
    if (container) {
      container.classList.remove("has-map");
    }
  }
}

function handleJsonMessage(msg) {
  console.log("Message received:", msg);

  if (msg.type === "lobby_info") {
    const startedGamesCounter = document.getElementById("startedGamesCounter");
    if (startedGamesCounter) {
      startedGamesCounter.textContent = String(msg.started_games_count || 0);
    }
    appendMessage(t("messages.lobbyInfo", { count: msg.active_games.length }));
    if (msg.active_games.length > 0) {
      appendMessage(t("messages.availableGames"));
      msg.active_games.forEach((game) => {
        appendMessage(t("messages.gameListEntry", { gameId: game.id, players: game.player_count }));
      });
    }
    renderLobbyGames(msg.active_games);
  } else if (msg.type === "game_created") {
    currentGameId = msg.game_id;
    saveSessionToStorage();
    currentPlayers = [
      {
        id: currentPlayerId,
        name: playerName,
        ready: false,
        score: 0,
        tab_away: false,
        is_host: true,
      },
    ];
    document.getElementById("gameIdDisplay").textContent = msg.game_id;
    document.getElementById("gameInfo").style.display = "block";

    const pinSection = document.getElementById("pinSection");
    if (msg.pin) {
      pinSection.classList.add("visible");
      document.getElementById("gamePinDisplay").textContent = msg.pin;
    } else {
      pinSection.classList.remove("visible");
      document.getElementById("gamePinDisplay").textContent = "-";
    }

    document.getElementById("inGameButtons").style.display = "block";
    document.getElementById("inGamePlayerList").innerHTML =
      `<li>⏳ ${playerName} (you)</li>`;
    document.getElementById("playerCount").textContent = "1";
    appendMessage(`✅ ${t("messages.gameCreated")} ${msg.game_id}`);
    updateUILayout();
  } else if (msg.type === "game_joined") {
    currentGameId = msg.game_id;
    saveSessionToStorage();
    document.getElementById("gameIdDisplay").textContent = msg.game_id;
    document.getElementById("gameInfo").style.display = "block";
    appendMessage(`✅ ${t("messages.gameJoined")} ${msg.game_id}`);
    document.getElementById("inGameButtons").style.display = "block";
    updateUILayout();
  } else if (msg.type === "game_info") {
    currentGameId = msg.game_id;
    saveSessionToStorage();
    currentGameStatus = msg.status || currentGameStatus;
    currentSettingsLocked = !!msg.settings_locked;
    currentIsHost = !!msg.is_host;
    currentPlayers = msg.players;
    document.getElementById("gameIdDisplay").textContent = msg.game_id;
    
    // Show PIN only to host
    const pinSection = document.getElementById("pinSection");
    if (msg.is_host && msg.pin) {
      pinSection.classList.add("visible");
      document.getElementById("gamePinDisplay").textContent = msg.pin;
    } else {
      pinSection.classList.remove("visible");
    }
    
    document.getElementById("gameInfo").style.display = "block";
    appendMessage(t("messages.gameInfoStatusPlayers", {
      status: msg.status || t("messages.unknownStatus"),
      players: msg.players.length,
    }));
    updateGameList(msg.game_id, msg.players);
    updateGameSettings(msg.game_id, msg.config);
    document.getElementById("inGameButtons").style.display = "block";
    updateHostControls();
    updateUILayout();
  } else if (msg.type === "game_starting") {
    currentGameStatus = "countdown";
    updateHostControls();
    appendMessage(`⏳ ${t("messages.countdownStarting", { seconds: msg.countdown })}`);
    document.getElementById("countdownText").textContent = t("countdown.startingIn");
    renderCountdownValue(msg.countdown);
    updateUILayout();
  } else if (msg.type === "game_started") {
    currentGameStatus = "active";
    updateHostControls();
    appendMessage(`🎮 ${t("messages.gameStarted")}`);
    if (msg.config) {
      currentMaxRounds = msg.config.max_rounds || currentMaxRounds;
      document.getElementById("rulesText").textContent =
        t("messages.settingsSummary", {
          maxRounds: msg.config.max_rounds,
          countdownSeconds: msg.config.countdown_seconds,
          answerSeconds: msg.config.answer_time_seconds,
          pauseSeconds: msg.config.pause_between_rounds_seconds,
        });
    }
    updateUILayout();
  } else if (msg.type === "new_question") {
    // Ensure gameplay panels are visible for every fresh round (including new game sessions)
    const inferredGameId =
      currentGameId
      || msg.game_id
      || restorePendingJoinGameId
      || localStorage.getItem(STORAGE_KEYS.GAME_ID)
      || "";
    if (inferredGameId && inferredGameId !== currentGameId) {
      currentGameId = inferredGameId;
      saveSessionToStorage();
    }

    currentGameStatus = "active";
    currentRoundNumber = msg.round || currentRoundNumber;
    currentMaxRounds = msg.max_rounds || currentMaxRounds;

    const cityFrom = msg.city1 || msg.cities?.[0] || msg.coordinates?.from?.name || "-";
    const cityTo = msg.city2 || msg.cities?.[1] || msg.coordinates?.to?.name || "-";
    const coordinates = msg.coordinates
      && msg.coordinates.from
      && msg.coordinates.to
      && Number.isFinite(Number(msg.coordinates.from.lat))
      && Number.isFinite(Number(msg.coordinates.from.lon))
      && Number.isFinite(Number(msg.coordinates.to.lat))
      && Number.isFinite(Number(msg.coordinates.to.lon))
      ? {
        from: {
          name: msg.coordinates.from.name || cityFrom,
          lat: Number(msg.coordinates.from.lat),
          lon: Number(msg.coordinates.from.lon),
        },
        to: {
          name: msg.coordinates.to.name || cityTo,
          lat: Number(msg.coordinates.to.lat),
          lon: Number(msg.coordinates.to.lon),
        },
      }
      : null;
    
    // Update UI layout
    updateUILayout();

    // Store coordinates FIRST before starting map preparation
    if (coordinates) {
      pendingQuestionCoordinates = coordinates;
      // START MAP PREPARATION IMMEDIATELY (do not wait for updateUILayout)
      queueMapPreparation();
      // Fast path: try rendering immediately; queueMapPreparation remains fallback.
      renderQuestionMap(coordinates);
    }

    // Generate localized question text
    const localizedQuestion = t("question.distanceTemplate", {
      city1: cityFrom,
      city2: cityTo
    });
    appendMessage(`🟡 ${t("messages.roundUpdate")} ${msg.round}/${msg.max_rounds}: ${localizedQuestion}`);
    document.getElementById("city1").textContent = cityFrom;
    document.getElementById("city2").textContent = cityTo;
    document.getElementById("guessInput").value = "";
    resetAnswerSubmissionState();
    document.getElementById("guessInput").focus();
    
    document.getElementById("countdownText").textContent = t("countdown.answerTimeRemaining");
    startManagedCountdown(msg.time_limit);
  } else if (msg.type === "game_status") {
    appendMessage(t("messages.statusValue", { status: msg.status }));
  } else if (msg.type === "answer_received") {
    guessSubmissionPending = false;
    guessLockedForRound = false;
    setGuessControlsDisabled(false);
    showAnswerSubmissionHint(
      msg.updated
        ? t("messages.answerUpdated", { guess: msg.guess, time: formatSubmissionTime(msg.submitted_at) })
        : t("messages.answerRegistered", { guess: msg.guess, time: formatSubmissionTime(msg.submitted_at) }),
      "success",
      2200,
    );
  } else if (msg.type === "countdown") {
    const val = msg.value || "...";
    document.getElementById("countdownText").textContent = `${t("countdown.countdownLabel")}: ${val}`;
    if (typeof msg.value === "number") {
      document.getElementById("countdown").textContent = String(msg.value);
    }
  } else if (msg.type === "game_paused") {
    appendMessage(
      t("messages.gamePausedReconnect", {
        seconds: msg.grace_seconds,
        playerName: msg.player_name || t("playerSetup.player"),
      }),
    );
    document.getElementById("countdownText").textContent = t("countdown.paused");
    pauseManagedCountdown(msg.remaining_seconds);
  } else if (msg.type === "game_resumed") {
    currentGameStatus = "active";
    appendMessage(`▶️ ${t("messages.roundResumed")}`);
    document.getElementById("countdownText").textContent = t("countdown.answerTimeRemaining");
    startManagedCountdown(msg.remaining_seconds);
    updateUILayout();
  } else if (msg.type === "round_result") {
    const summary = msg.standings
      .map((s) => `${s.player_name}: ${s.score} (${s.delta >= 0 ? "+" : ""}${s.delta})`)
      .join(" | ");
    appendMessage(
      t("messages.roundResult", {
        round: msg.round,
        winner: msg.winner,
        distance: msg.correct_distance,
        summary,
      }),
    );
  } else if (msg.type === "warmup_started") {
    currentGameStatus = "warmup";
    appendMessage(`🔥 ${t("messages.warmupStarted")} (${msg.time_limit}s)`);
    updateUILayout();
  } else if (msg.type === "warmup_result") {
    appendMessage(`🔥 ${t("messages.warmupEnded")}: ${msg.message || ""}`);
  } else if (msg.type === "bot_suspected") {
    appendMessage(
      `🚨 Bot-Verdacht: ${msg.player_name} (Score ${msg.suspicion_score}, schnelle Antworten: ${msg.fast_answers})`,
    );
  } else if (msg.type === "kicked") {
    appendMessage(`🚫 ${translateServerMessage(msg.message || "You were removed by the host")}`);
    cleanupGameResources();
    clearStoredGame();
    document.getElementById("inGameButtons").style.display = "none";
    document.getElementById("gameInfo").style.display = "none";
    updateHostControls();
    updateUILayout();
    resetCountdownDisplay();
  } else if (msg.type === "player_joined") {
    // Note: Player joined message doesn't include full player data, so we'll wait for game_info update
    appendMessage(t("messages.playerJoined", { playerName: msg.player || "-" }));
  } else if (msg.type === "player_left") {
    // Remove player from local state
    currentPlayers = currentPlayers.filter((p) => p.id !== msg.player_id);
    // Re-render player lists
    updateGameList(currentGameId, currentPlayers);
    appendMessage(t("messages.playerLeft"));
  } else if (msg.type === "player_ready_changed") {
    // Update local player state
    const playerIndex = currentPlayers.findIndex((p) => p.id === msg.player_id);
    if (playerIndex !== -1) {
      currentPlayers[playerIndex].ready = msg.ready;
      // Re-render player lists
      updateGameList(currentGameId, currentPlayers);
    }
    appendMessage(msg.ready ? t("messages.playerReady") : t("messages.playerNotReady"));
  } else if (msg.type === "player_updated") {
    const playerIndex = currentPlayers.findIndex((p) => p.id === msg.player_id);
    if (playerIndex !== -1) {
      currentPlayers[playerIndex].name = msg.name;
      updateGameList(currentGameId, currentPlayers);
    }
  } else if (msg.type === "player_tab_left") {
    const playerIndex = currentPlayers.findIndex((p) => p.id === msg.player_id);
    if (playerIndex !== -1) {
      currentPlayers[playerIndex].tab_away = true;
      updateGameList(currentGameId, currentPlayers);
    }
    appendMessage(t("messages.playerTabLeft", { playerName: msg.name || "-" }));
  } else if (msg.type === "session_restored") {
    currentPlayerId = msg.player_id;
    playerName = msg.name || playerName;
    if (playerName) {
      localStorage.setItem(STORAGE_KEYS.PLAYER_NAME, playerName);
      localStorage.setItem(STORAGE_KEYS.PLAYER_ID, currentPlayerId);
      document.getElementById("setupPhase").style.display = "none";
      document.getElementById("gamePhase").style.display = "block";
      document.getElementById("currentPlayerName").textContent = playerName;
    }
    if (msg.game_id) {
      currentGameId = msg.game_id;
      restorePendingJoinGameId = msg.game_id;
      localStorage.setItem(STORAGE_KEYS.GAME_ID, msg.game_id);
    }
    updateUILayout();
  } else if (msg.type === "error") {
    const localizedServerMessage = translateServerMessage(msg.message);
    appendMessage(`❌ ${localizedServerMessage}`);
    if (guessSubmissionPending || guessLockedForRound) {
      guessSubmissionPending = false;
      guessLockedForRound = false;
      setGuessControlsDisabled(false);
      showAnswerSubmissionHint(localizedServerMessage || t("messages.answerSubmitFailed"), "error", 3500);
    }
    if (msg.message && msg.message.includes("Cannot join game")) {
      clearStoredGame();
    }
  } else if (msg.type === "game_finished") {
    // Show game finished modal with results
    document.getElementById("winnerName").textContent = msg.winner || t("messages.unknownPlayer");

    const scoresTableBody = document.getElementById("scoresTableBody");
    scoresTableBody.innerHTML = "";
    ["podiumPlace1", "podiumPlace2", "podiumPlace3"].forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.textContent = "";
      el.classList.remove("visible");
    });

    if (msg.final_scores && Object.keys(msg.final_scores).length > 0) {
      let scoreIndex = 1;
      const sortedScores = Object.entries(msg.final_scores).sort(
        (a, b) => b[1].score - a[1].score,
      );

      const podium = [
        { id: "podiumPlace1", key: "gameEnd.firstPlace" },
        { id: "podiumPlace2", key: "gameEnd.secondPlace" },
        { id: "podiumPlace3", key: "gameEnd.thirdPlace" },
      ];
      podium.forEach((slot, index) => {
        const el = document.getElementById(slot.id);
        if (!el) return;
        if (sortedScores[index]) {
          const [name, stats] = sortedScores[index];
          el.textContent = t(slot.key, { name, score: stats.score });
          el.classList.add("visible");
        } else {
          el.textContent = "";
          el.classList.remove("visible");
        }
      });

      sortedScores.forEach(([playerName, stats]) => {
        const row = document.createElement("tr");
        const medal =
          scoreIndex === 1
            ? "🥇"
            : scoreIndex === 2
              ? "🥈"
              : scoreIndex === 3
                ? "🥉"
                : "•";
        row.style.borderBottom = "1px solid #e2e8f0";
        row.style.backgroundColor =
          scoreIndex === 1 ? "#fffaeb" : "transparent";
        row.innerHTML = `
                            <td style="padding: 12px; text-align: left; color: #2d3748;"><strong>${medal} ${playerName}</strong></td>
                            <td style="padding: 12px; text-align: center; color: #4f46e5; font-weight: 600;">${stats.score}</td>
                            <td style="padding: 12px; text-align: center; color: #22c55e; font-weight: 600;">${stats.avg_accuracy}%</td>
                        `;
        scoresTableBody.appendChild(row);
        scoreIndex++;
      });
    }

    renderRoundHistory(msg.round_history || []);

    // Cleanup game resources before showing results
    cleanupGameResources();

    // Show the modal
    const modal = document.getElementById("gameFinishedModal");
    modal.style.display = "flex";

    // Still log to messages for reference
    appendMessage(t("messages.gameFinishedWinner", { winner: msg.winner || "-" }));
    document.getElementById("inGameButtons").style.display = "none";
    document.getElementById("gameInfo").style.display = "none";
    currentGameStatus = "finished";
    updateHostControls();
    clearStoredGame();
    updateUILayout();
    resetCountdownDisplay(t("gameEnd.title"));
  } else if (msg.type === "name_set") {
    currentPlayerId = msg.player_id;
    localStorage.setItem(STORAGE_KEYS.PLAYER_ID, currentPlayerId);
    localStorage.setItem(STORAGE_KEYS.PLAYER_NAME, msg.name);
    if (restorePendingJoinGameId && !currentGameId) {
      joinGameById(restorePendingJoinGameId);
    }
    restorePendingJoinGameId = "";
    appendMessage(t("messages.nameSet", { name: msg.name }));
  }

  updateMatchHud();
}
function set_countdown(countdownLimitSeconds) {
  startManagedCountdown(countdownLimitSeconds);
}
function updateGameSettings(game_id, config) {
  if (config) {
    currentMaxRounds = config.max_rounds || currentMaxRounds;
    document.getElementById("rulesText").textContent =
      t("messages.settingsSummary", {
        maxRounds: config.max_rounds,
        countdownSeconds: config.countdown_seconds,
        answerSeconds: config.answer_time_seconds,
        pauseSeconds: config.pause_between_rounds_seconds,
      });
    const maxRoundsInput = document.getElementById("settingMaxRounds");
    const countdownInput = document.getElementById("settingCountdown");
    const answerTimeInput = document.getElementById("settingAnswerTime");
    const pauseTimeInput = document.getElementById("settingPauseTime");
    const autoAdvanceAllAnsweredInput = document.getElementById("settingAutoAdvanceAllAnswered");
    const firstAnswerEndsRoundInput = document.getElementById("settingFirstAnswerEndsRound");
    const wrongAnswerPointsOthersInput = document.getElementById("settingWrongAnswerPointsOthers");
    if (maxRoundsInput) maxRoundsInput.value = config.max_rounds;
    if (countdownInput) countdownInput.value = config.countdown_seconds;
    if (answerTimeInput) answerTimeInput.value = config.answer_time_seconds;
    if (pauseTimeInput) pauseTimeInput.value = config.pause_between_rounds_seconds;
    if (autoAdvanceAllAnsweredInput) autoAdvanceAllAnsweredInput.checked = !!config.auto_advance_on_all_answers;
    if (firstAnswerEndsRoundInput) firstAnswerEndsRoundInput.checked = !!config.first_answer_ends_round;
    if (wrongAnswerPointsOthersInput) wrongAnswerPointsOthersInput.checked = !!config.wrong_answer_points_others;
  }
  updateHostControls();
}
function updateGameList(game_id, players) {
  // Update right sidebar player list
  const list = document.getElementById("playerList");
  list.innerHTML = "";
  const ul = document.createElement("ul");
  const gameli = document.createElement("li");
  gameli.textContent = `${game_id}`;
  list.appendChild(gameli);
  const ulp = document.createElement("ul");
  gameli.appendChild(ulp);
  players.forEach((p) => {
    const status = p.ready ? "✓ Ready" : "⏳ Waiting";
    const away = p.tab_away ? " ❗" : "";
    const item = document.createElement("li");
    item.textContent = `${p.name}${away} - ${status} (Score: ${p.score || 0})`;
    if (p.bot_flagged) {
      item.textContent += " 🤖";
    }
    if (
      currentIsHost &&
      currentGameStatus === "waiting" &&
      p.id !== currentPlayerId
    ) {
      const kickBtn = document.createElement("button");
      kickBtn.textContent = "Kick";
      kickBtn.style.marginLeft = "8px";
      kickBtn.onclick = () => kickPlayer(p.id);
      item.appendChild(kickBtn);
    }
    ulp.appendChild(item);
  });

  // Update in-game player list in game info section
  const inGameList = document.getElementById("inGamePlayerList");
  inGameList.innerHTML = "";
  document.getElementById("playerCount").textContent = players.length;
  players.forEach((p) => {
    const status = p.ready ? "✓" : "⏳";
    const away = p.tab_away ? "❗" : "";
    const item = document.createElement("li");
    item.textContent = `${status}${away ? ` ${away}` : ""} ${p.name}`;
    inGameList.appendChild(item);
  });
}

function appendMessage(text) {
  const msg = document.createElement("p");
  msg.textContent = text;
  const messagesDiv = document.getElementById("messages");
  messagesDiv.appendChild(msg);
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function saveSessionToStorage() {
  if (playerName) localStorage.setItem(STORAGE_KEYS.PLAYER_NAME, playerName);
  if (currentPlayerId) localStorage.setItem(STORAGE_KEYS.PLAYER_ID, currentPlayerId);
  if (currentGameId) localStorage.setItem(STORAGE_KEYS.GAME_ID, currentGameId);
}

function clearStoredGame() {
  currentGameId = "";
  currentGameStatus = "waiting";
  currentIsHost = false;
  currentSettingsLocked = false;
  localStorage.removeItem(STORAGE_KEYS.GAME_ID);
  updateUILayout();
}

function cleanupGameResources() {
  // Thorough cleanup of game resources after game ends
  
  // Clear any pending resize debounce
  if (resizeDebounceTimer) {
    clearTimeout(resizeDebounceTimer);
    resizeDebounceTimer = null;
  }

  // Cleanup map
  if (gameMapResizeObserver) {
    gameMapResizeObserver.disconnect();
    gameMapResizeObserver = null;
  }
  
  if (gameMapFeatureSource) {
    gameMapFeatureSource.clear();
  }

  if (gameMap) {
    gameMap.setTarget(null);
    gameMap = null;
    gameMapBaseLayer = null;
    gameMapFallbackLayer = null;
    gameMapFeatureLayer = null;
    gameMapFeatureSource = null;
  }
  
  // Clear map container with i18n-safe placeholder
  const mapContainer = document.getElementById("mapContainer");
  if (mapContainer) {
    mapContainer.classList.remove("has-map");
    // Create placeholder element with i18n data attribute
    const placeholder = document.createElement("div");
    placeholder.id = "mapPlaceholder";
    placeholder.className = "map-placeholder";
    placeholder.setAttribute("data-i18n", "mapPlaceholder");
    placeholder.textContent = t("mapPlaceholder") || "Map will load with next question.";
    mapContainer.innerHTML = "";
    mapContainer.appendChild(placeholder);
  }
  
  // Clear messages
  const messagesDiv = document.getElementById("messages");
  if (messagesDiv) {
    messagesDiv.innerHTML = "";
  }
  
  // Clear game-specific state
  currentPlayers = [];
  currentGameStatus = "waiting";
  currentRoundNumber = null;
  currentMaxRounds = null;
  
  // Reset all answer-related state
  resetAnswerSubmissionState();
  
  // Cancel any pending timeouts
  if (pendingMapPreparationTimeoutId) {
    clearTimeout(pendingMapPreparationTimeoutId);
    pendingMapPreparationTimeoutId = null;
  }
  pendingQuestionCoordinates = null;

  // Clear countdown timer
  clearCountdownTimer();
}

function updateHostControls() {
  const warmupBtn = document.getElementById("warmupBtn");
  const lockBtn = document.getElementById("lockSettingsBtn");
  const hostSettingsEditor = document.getElementById("hostSettingsEditor");
  const saveSettingsBtn = document.getElementById("saveSettingsBtn");
  if (!warmupBtn || !lockBtn) return;

  const showHostControls = currentIsHost && currentGameStatus === "waiting";
  const canEditSettings = showHostControls && !currentSettingsLocked;
  warmupBtn.style.display = showHostControls ? "inline-block" : "none";
  lockBtn.style.display = showHostControls ? "inline-block" : "none";
  lockBtn.textContent = currentSettingsLocked
    ? t("messages.unlockSettings")
    : t("messages.lockSettings");

  if (hostSettingsEditor) {
    hostSettingsEditor.classList.toggle("visible", showHostControls);
  }

  [
    document.getElementById("settingMaxRounds"),
    document.getElementById("settingCountdown"),
    document.getElementById("settingAnswerTime"),
    document.getElementById("settingPauseTime"),
    document.getElementById("settingAutoAdvanceAllAnswered"),
    document.getElementById("settingFirstAnswerEndsRound"),
    document.getElementById("settingWrongAnswerPointsOthers"),
  ].forEach((inputEl) => {
    if (inputEl) {
      inputEl.disabled = !canEditSettings;
    }
  });

  if (saveSettingsBtn) {
    saveSettingsBtn.disabled = !canEditSettings;
  }
}

function saveGameSettings() {
  if (!currentIsHost || currentGameStatus !== "waiting" || currentSettingsLocked) {
    return;
  }

  const maxRounds = parseInt(document.getElementById("settingMaxRounds")?.value || "", 10);
  const countdownSeconds = parseInt(document.getElementById("settingCountdown")?.value || "", 10);
  const answerTimeSeconds = parseInt(document.getElementById("settingAnswerTime")?.value || "", 10);
  const pauseBetweenRoundsSeconds = parseInt(document.getElementById("settingPauseTime")?.value || "", 10);
  const autoAdvanceOnAllAnswers = !!document.getElementById("settingAutoAdvanceAllAnswered")?.checked;
  const firstAnswerEndsRound = !!document.getElementById("settingFirstAnswerEndsRound")?.checked;
  const wrongAnswerPointsOthers = !!document.getElementById("settingWrongAnswerPointsOthers")?.checked;

  const values = [maxRounds, countdownSeconds, answerTimeSeconds, pauseBetweenRoundsSeconds];
  if (values.some((v) => Number.isNaN(v))) {
    alert(t("messages.invalidSettingsInput"));
    return;
  }

  sendMessage({
    type: "update_settings",
    data: {
      max_rounds: maxRounds,
      countdown_seconds: countdownSeconds,
      answer_time_seconds: answerTimeSeconds,
      pause_between_rounds_seconds: pauseBetweenRoundsSeconds,
      auto_advance_on_all_answers: autoAdvanceOnAllAnswers,
      first_answer_ends_round: firstAnswerEndsRound,
      wrong_answer_points_others: wrongAnswerPointsOthers,
    },
  });
  appendMessage(t("messages.settingsUpdateSent"));
}

function kickPlayer(targetPlayerId) {
  if (!targetPlayerId) return;
  sendMessage({ type: "kick_player", data: { target_player_id: targetPlayerId } });
}

function toggleLockSettings() {
  sendMessage({ type: "lock_settings", data: { locked: !currentSettingsLocked } });
}

function startWarmup() {
  sendMessage({ type: "start_warmup", data: {} });
}

function restoreSessionFromStorage() {
  const storedName = localStorage.getItem(STORAGE_KEYS.PLAYER_NAME) || "";
  const storedGameId = localStorage.getItem(STORAGE_KEYS.GAME_ID) || "";

  if (!storedName) return;

  playerName = storedName;
  document.getElementById("playerName").value = playerName;
  document.getElementById("setupPhase").style.display = "none";
  document.getElementById("gamePhase").style.display = "block";
  document.getElementById("currentPlayerName").textContent = playerName;

  sendMessage({ type: "set_name", data: { name: playerName } });
  if (storedGameId) {
    restorePendingJoinGameId = storedGameId;
  }
}

function renderLobbyGames(activeGames) {
  const list = document.getElementById("lobbyGamesList");
  if (!list) return;

  list.innerHTML = "";
  const waitingGames = (activeGames || []).filter((g) => g.status === "waiting");

  if (waitingGames.length === 0) {
    const empty = document.createElement("li");
    empty.textContent = t("messages.noOpenGames");
    list.appendChild(empty);
    return;
  }

  waitingGames.forEach((game) => {
    const item = document.createElement("li");
    const link = document.createElement("a");
    link.href = "#";
    link.textContent = `${game.id} (${game.player_count} players)`;
    link.onclick = (event) => {
      event.preventDefault();
      // Pre-fill the game ID and show the join form
      document.getElementById("gameIdInput").value = game.id;
      document.getElementById("gamePinInput").value = "";
      showJoinGame();
    };
    item.appendChild(link);
    list.appendChild(item);
  });
}

function joinGameById(gameId, pin = "") {
  if (!gameId) return;
  document.getElementById("gameIdInput").value = gameId;
  const payload = { game_id: gameId };
  if (pin) {
    payload.pin = pin;
  }
  sendMessage({ type: "join_game", data: payload });
  appendMessage(t("messages.joiningGame", { gameId }));
}

function notifyTabLeaving() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    try {
      ws.send(JSON.stringify({ type: "tab_leaving", data: {} }));
    } catch (error) {
      console.error("Could not send tab_leaving", error);
    }
  }
}

function notifyTabActive() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    sendMessage({ type: "tab_active", data: {} });
  }
}

function registerKeyboardUX() {
  const playerNameInput = document.getElementById("playerName");
  const gameIdInput = document.getElementById("gameIdInput");
  const guessInput = document.getElementById("guessInput");

  if (playerNameInput) {
    playerNameInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        setPlayerName();
      }
    });
  }

  if (gameIdInput) {
    gameIdInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        joinGame();
      }
    });
  }

  if (guessInput) {
    guessInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        sendGuess();
      }
      if (event.key === "Escape") {
        guessInput.value = "";
      }
    });

    guessInput.addEventListener("focus", () => {
      guessInput.select();
    });
  }

  document.addEventListener("keydown", (event) => {
    const gameFinishedModal = document.getElementById("gameFinishedModal");
    const isGameFinishedModalVisible = !!(
      gameFinishedModal
      && window.getComputedStyle(gameFinishedModal).display !== "none"
    );

    if (event.key === "Escape" && isGameFinishedModalVisible) {
      event.preventDefault();
      backToLobby();
      return;
    }

    if (shouldIgnoreGlobalShortcut(event)) return;

    const key = event.key.toLowerCase();
    if (key === "n") {
      event.preventDefault();
      focusAndSelect("playerName");
    } else if (key === "j") {
      event.preventDefault();
      if (document.getElementById("gamePhase")?.style.display !== "none") {
        showJoinGame();
      }
    } else if (key === "g") {
      event.preventDefault();
      if (currentGameId) {
        focusAndSelect("guessInput");
      }
    }
  });
}

function setPlayerName() {
  const nameInput = document.getElementById("playerName").value.trim();
  if (!nameInput) return alert(t("messages.nameCannotBeEmpty"));
  playerName = nameInput;
  localStorage.setItem(STORAGE_KEYS.PLAYER_NAME, playerName);

  if (!isConnected) {
    connect();
    setTimeout(() => {
      sendMessage({ type: "set_name", data: { name: playerName } });
    }, 500);
  } else {
    sendMessage({ type: "set_name", data: { name: playerName } });
  }

  // Show game phase UI
  document.getElementById("setupPhase").style.display = "none";
  document.getElementById("gamePhase").style.display = "block";
  document.getElementById("currentPlayerName").textContent = playerName;
  updateUILayout();
}

function createGame() {
  const message = {
    type: "create_game",
    data: {},
  };
  sendMessage(message);
  appendMessage(t("messages.creatingGame"));
}

function showJoinGame() {
  document.getElementById("joinGameForm").style.display = "block";
  // If Game ID is already filled, focus on PIN input; otherwise focus on Game ID input
  const gameIdInput = document.getElementById("gameIdInput");
  if (gameIdInput.value.trim()) {
    setTimeout(() => focusAndSelect("gamePinInput"), 0);
  } else {
    setTimeout(() => focusAndSelect("gameIdInput"), 0);
  }
}

function hideJoinGame() {
  document.getElementById("joinGameForm").style.display = "none";
  document.getElementById("gameIdInput").value = "";
  document.getElementById("gamePinInput").value = "";
}

function joinGame() {
  const gameId = document.getElementById("gameIdInput").value.trim();
  const pin = document.getElementById("gamePinInput").value.trim();
  if (!gameId) return alert(t("messages.enterGameId"));

  joinGameById(gameId, pin);
  hideJoinGame();
}

function setReady() {
  const message = { type: "set_ready", data: { ready: true } };
  sendMessage(message);
  // Update local state immediately for better UX
  const playerIndex = currentPlayers.findIndex((p) => p.id === currentPlayerId);
  if (playerIndex !== -1) {
    currentPlayers[playerIndex].ready = true;
    updateGameList(currentGameId, currentPlayers);
  }
  appendMessage(t("messages.youAreReady"));
}

function changeLanguage(langCode) {
  localStorage.setItem("entfernungsspiel.language", langCode);
  setLanguage(langCode);
  
  // Update language button states
  document.getElementById("langDE").classList.toggle("lang-btn-active", langCode === "de");
  document.getElementById("langEN").classList.toggle("lang-btn-active", langCode === "en");
}

function leaveGame() {
  // Cleanup game resources first
  cleanupGameResources();
  const message = { type: "leave_game", data: {} };
  sendMessage(message);
  clearStoredGame();
  document.getElementById("inGameButtons").style.display = "none";
  document.getElementById("gameInfo").style.display = "none";
  updateHostControls();
  updateUILayout();
  resetCountdownDisplay();
  appendMessage(t("messages.youLeftGame"));
}

function playAgain() {
  // Cleanup old game resources first
  cleanupGameResources();
  // Close modal
  document.getElementById("gameFinishedModal").style.display = "none";
  // Create new game
  createGame();
}

function backToLobby() {
  // Cleanup old game resources first
  cleanupGameResources();
  // Close modal
  document.getElementById("gameFinishedModal").style.display = "none";
  // Reset UI to show setup phase
  document.getElementById("setupPhase").style.display = "none";
  document.getElementById("gamePhase").style.display = "block";
  document.getElementById("inGameButtons").style.display = "none";
  document.getElementById("gameInfo").style.display = "none";
  clearStoredGame();
  updateUILayout();
  resetCountdownDisplay();
  appendMessage(t("messages.backToLobbyReady"));
}

function sendGuess() {
  const guess = document.getElementById("guessInput").value.trim();
  if (!guess) return alert(t("messages.enterDistance"));

  const guessNum = parseInt(guess);
  if (isNaN(guessNum) || guessNum < 0)
    return alert(t("messages.enterValidNumber"));

  if (guessSubmissionPending || guessLockedForRound) {
    return;
  }

  const message = { type: "submit_answer", data: { guess: guessNum } };
  guessSubmissionPending = true;
  setGuessControlsDisabled(true);
  showAnswerSubmissionHint(t("messages.answerSending", { guess: guessNum }), "pending");
  sendMessage(message);
}

function updateAnswer() {
  resetAnswerSubmissionState();
  document.getElementById("guessInput").value = "";
  document.getElementById("guessInput").focus();
  appendMessage(t("messages.canUpdateAnswer"));
}

function keepAnswer() {
  resetAnswerSubmissionState();
  document.getElementById("guessInput").value = "";
  appendMessage(t("messages.answerLockedWaiting"));
}

function sendMessage(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg));
  } else {
    appendMessage(`❌ ${t("messages.notConnected")}`);
  }
}

window.onload = () => {
  const startedGamesCounter = document.getElementById("startedGamesCounter");
  if (startedGamesCounter) {
    startedGamesCounter.textContent = "0";
  }
  const storedName = localStorage.getItem(STORAGE_KEYS.PLAYER_NAME) || "";
  if (storedName) {
    playerName = storedName;
    document.getElementById("playerName").value = storedName;
    document.getElementById("setupPhase").style.display = "none";
    document.getElementById("gamePhase").style.display = "block";
    document.getElementById("currentPlayerName").textContent = storedName;
  }
  resetAnswerSubmissionState();
  resetCountdownDisplay();
  updateUILayout();
  registerKeyboardUX();
  connect();
};

window.addEventListener("beforeunload", notifyTabLeaving);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") {
    notifyTabLeaving();
  } else {
    notifyTabActive();
  }
});
window.addEventListener("focus", notifyTabActive);
