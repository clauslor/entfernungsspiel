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
let restorePendingJoinPin = "";
let gameMap = null;
let gameMapBaseLayer = null;
let gameMapFallbackLayer = null;
let gameMapFeatureLayer = null;
let gameMapFeatureSource = null;
let gameMapResizeObserver = null;
let gameMapOverlays = [];
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
let currentQuestionVariant = "air";
let currentSortingOrder = "asc";
let currentSortingPool = [];
let currentSortingSelection = [];

const DEFAULT_MAP_VIEW = {
  center: [51.1657, 10.4515],
  zoom: 4,
};

const STORAGE_KEYS = {
  PLAYER_NAME: "entfernungsspiel.playerName",
  PLAYER_ID: "entfernungsspiel.playerId",
  GAME_ID: "entfernungsspiel.gameId",
  CREATOR_SETTINGS: "entfernungsspiel.creatorSettings",
};

// Initialize i18n system on page load
document.addEventListener("DOMContentLoaded", async () => {
  await initializeI18n();
  updateUILanguage();

  // Initialize CAPTCHA system
  initializeCaptcha();

  // Wire "Kein Zeitlimit" toggle visibility based on firstAnswerEndsRound checkbox
  const firstAnswerEl = document.getElementById("settingFirstAnswerEndsRound");
  const noTimeLimitRowEl = document.getElementById("noTimeLimitRow");
  const noTimeLimitInputEl = document.getElementById("settingNoTimeLimit");
  const answerTimeInputEl = document.getElementById("settingAnswerTime");
  const enableRoadQuestionsEl = document.getElementById("settingEnableRoadQuestions");

  if (firstAnswerEl && noTimeLimitRowEl) {
    firstAnswerEl.addEventListener("change", () => {
      applyNoTimeLimitVisibility(firstAnswerEl.checked);
      if (!firstAnswerEl.checked && noTimeLimitInputEl) {
        noTimeLimitInputEl.checked = false;
        if (answerTimeInputEl) answerTimeInputEl.disabled = false;
      }
    });
  }
  if (noTimeLimitInputEl && answerTimeInputEl) {
    noTimeLimitInputEl.addEventListener("change", () => {
      answerTimeInputEl.disabled = noTimeLimitInputEl.checked;
    });
  }
  if (enableRoadQuestionsEl) {
    enableRoadQuestionsEl.addEventListener("change", () => {
      applyRoadQuestionControls(enableRoadQuestionsEl.checked);
    });
  }

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
  const wsProtocol = window.location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${wsProtocol}://${window.location.host}/ws${playerParam}`);
  window.ws = ws;
  console.log('WebSocket created and stored globally:', { ws_exists: !!ws, window_ws_exists: !!window.ws });

  ws.onmessage = (event) => {
    const data = event.data;
    try {
      const msg = JSON.parse(data);
      try {
        handleJsonMessage(msg);
      } catch (err) {
        console.error("Error in handleJsonMessage:", err, "payload:", msg);
        appendMessage(`❌ ${t("messages.connectionError")}`);
      }
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
    window.ws = null;
    appendMessage(`❌ ${t("messages.disconnected")}`);
    setTimeout(connect, 2000); // Reconnect after 2 seconds
  };

  ws.onerror = (error) => {
    appendMessage(`❌ ${t("messages.connectionError")}`);
    console.error("WebSocket error:", error);
  };
}

function parseJoinIntentFromUrl() {
  const params = new URLSearchParams(window.location.search || "");
  const gameId = (params.get("game") || "").trim();
  if (!gameId) return null;
  const pin = (params.get("pin") || "").trim();
  return { gameId, pin };
}

function captureJoinIntentFromUrl() {
  const intent = parseJoinIntentFromUrl();
  if (!intent) return;

  restorePendingJoinGameId = intent.gameId;
  restorePendingJoinPin = intent.pin;
  localStorage.setItem(STORAGE_KEYS.GAME_ID, intent.gameId);

  const gameIdInput = document.getElementById("gameIdInput");
  if (gameIdInput) {
    gameIdInput.value = intent.gameId;
  }

  if (window.history && typeof window.history.replaceState === "function") {
    const cleanUrl = `${window.location.origin}${window.location.pathname}`;
    window.history.replaceState({}, document.title, cleanUrl);
  }
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
  const editNameBtn = document.getElementById("editPlayerNameBtn");
  const editNameControls = document.getElementById("playerNameEditControls");

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

  if (editNameBtn) {
    editNameBtn.style.display = inGame ? "none" : "inline-flex";
  }
  if (editNameControls) {
    if (inGame) {
      editNameControls.classList.remove("is-open");
    }
    editNameControls.style.display = inGame ? "none" : "";
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

function isCompactHudMode() {
  return window.matchMedia("(max-width: 560px)").matches;
}

function getCompactPhaseCode() {
  const status = (currentGameStatus || "waiting").toLowerCase();
  if (!currentGameId) return "L";
  if (["active", "playing", "warmup"].includes(status)) return "A";
  if (status === "countdown") return "CD";
  if (status === "finished") return "F";
  return "W";
}

function getCurrentPlayerScore() {
  if (!Array.isArray(currentPlayers) || currentPlayers.length === 0) return null;
  const byId = currentPlayers.find((p) => p.id === currentPlayerId);
  if (byId && Number.isFinite(Number(byId.score))) {
    return Number(byId.score);
  }
  const byName = currentPlayers.find((p) => p.name === playerName);
  if (byName && Number.isFinite(Number(byName.score))) {
    return Number(byName.score);
  }
  return null;
}

function updateMatchHud() {
  const hud = document.getElementById("matchHud");
  if (!hud) return;

  const phaseEl = document.getElementById("hudPhase");
  const gameEl = document.getElementById("hudGame");
  const roundEl = document.getElementById("hudRound");
  const pointsEl = document.getElementById("hudPoints");
  const countdownEl = document.getElementById("hudCountdown");
  const compactHud = isCompactHudMode();

  let countdownValue = "--:--";
  const countdownDisplay = document.getElementById("countdown");
  if (countdownDisplay && countdownDisplay.textContent && countdownDisplay.textContent.trim()) {
    countdownValue = countdownDisplay.textContent.trim();
  }

  if (phaseEl) {
    phaseEl.textContent = compactHud ? getCompactPhaseCode() : getLocalizedPhaseLabel();
  }
  if (gameEl) {
    if (!currentGameId) {
      gameEl.textContent = "-";
    } else if (compactHud) {
      gameEl.textContent = `#${String(currentGameId).slice(0, 6)}`;
    } else {
      gameEl.textContent = currentGameId;
    }
  }
  if (roundEl) {
    roundEl.textContent = currentRoundNumber && currentMaxRounds
      ? `${currentRoundNumber}/${currentMaxRounds}`
      : "-";
  }
  if (pointsEl) {
    const score = getCurrentPlayerScore();
    pointsEl.textContent = currentGameId && score !== null ? String(score) : "-";
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
    "At least one question type must be enabled": "serverErrors.atLeastOneQuestionType",
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
  const submitSortingButton = document.getElementById("submitSortingBtn");
  const resetSortingButton = document.getElementById("resetSortingBtn");
  if (guessInput) {
    guessInput.disabled = disabled;
  }
  if (submitButton) {
    submitButton.disabled = disabled;
  }
  if (submitSortingButton) {
    submitSortingButton.disabled = disabled;
  }
  if (resetSortingButton) {
    resetSortingButton.disabled = disabled;
  }
}

function getSortingChipColorIndex(value) {
  const text = String(value || "");
  let hash = 0;
  for (let i = 0; i < text.length; i += 1) {
    hash = ((hash << 5) - hash) + text.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash) % 4;
}

function renderSortingUI() {
  const poolEl = document.getElementById("sortingNumberPool");
  const selectionEl = document.getElementById("sortingSelection");
  if (!poolEl || !selectionEl) return;

  poolEl.innerHTML = "";
  currentSortingPool.forEach((value, index) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `sorting-chip sorting-chip-color-${getSortingChipColorIndex(value)}`;
    btn.textContent = String(value);
    btn.onclick = () => {
      currentSortingSelection.push(value);
      currentSortingPool.splice(index, 1);
      renderSortingUI();
    };
    poolEl.appendChild(btn);
  });

  selectionEl.innerHTML = "";
  currentSortingSelection.forEach((value, index) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `sorting-chip sorting-chip-color-${getSortingChipColorIndex(value)} sorting-chip-selected`;
    btn.textContent = String(value);
    btn.onclick = () => {
      currentSortingPool.push(value);
      currentSortingSelection.splice(index, 1);
      renderSortingUI();
    };
    selectionEl.appendChild(btn);
  });
}

function initializeSortingQuestion(numbers, sortingOrder) {
  currentSortingOrder = sortingOrder || "asc";
  currentSortingPool = Array.isArray(numbers) ? numbers.slice() : [];
  currentSortingSelection = [];
  renderSortingUI();
}

function resetSortingSelection() {
  currentSortingPool = currentSortingPool.concat(currentSortingSelection);
  currentSortingSelection = [];
  renderSortingUI();
}

function applyQuestionVariantUI(questionVariant) {
  const distanceControls = document.getElementById("distanceAnswerControls");
  const sortingControls = document.getElementById("sortingAnswerControls");
  const sortingPromptBanner = document.getElementById("sortingPromptBanner");
  const ortsschildContainer = document.getElementById("ortsschildContainer");
  const mapContainer = document.getElementById("mapContainer");

  const isSorting = questionVariant === "sorting";
  if (distanceControls) distanceControls.style.display = isSorting ? "none" : "flex";
  if (sortingControls) sortingControls.style.display = isSorting ? "block" : "none";
  if (sortingPromptBanner) sortingPromptBanner.hidden = !isSorting;
  if (ortsschildContainer) ortsschildContainer.style.display = isSorting ? "none" : "block";
  if (mapContainer) mapContainer.style.display = isSorting ? "none" : "block";
}

function submitSortingAnswer() {
  if (currentQuestionVariant !== "sorting") return;
  if (currentSortingSelection.length === 0) return;

  const expectedLength = currentSortingSelection.length + currentSortingPool.length;
  if (currentSortingSelection.length !== expectedLength) {
    return alert("Bitte ordne zuerst alle Zahlen ein.");
  }

  if (guessSubmissionPending || guessLockedForRound) {
    return;
  }

  guessSubmissionPending = true;
  setGuessControlsDisabled(true);
  showAnswerSubmissionHint(
    `Sortierung wird gesendet: ${currentSortingSelection.join(" > ")}`,
    "pending",
  );
  sendMessage({
    type: "submit_answer",
    data: { sorted_numbers: currentSortingSelection.slice() },
  });
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
    if (round.question_type === "sorting") {
      solution.innerHTML = `✅ <strong>Richtige Reihenfolge: ${(round.correct_order || []).join(" > ")}</strong> | 🏆 Gewinner: ${round.winner}`;
    } else {
      solution.innerHTML = `✅ <strong>Richtige Antwort: ${round.correct_distance} km</strong> | 🏆 Gewinner: ${round.winner}`;
    }

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
        const finalGuessText = Array.isArray(submission.final_guess)
          ? submission.final_guess.join(" > ")
          : String(submission.final_guess);
        finalEntry.textContent = round.question_type === "sorting"
          ? `Gewertet wurde: ${finalGuessText} um ${formatSubmissionTime(submission.final_submitted_at)}`
          : `Gewertet wurde: ${finalGuessText} km um ${formatSubmissionTime(submission.final_submitted_at)}`;
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
          item.textContent = round.question_type === "sorting"
            ? `${prefix}: ${answer.guess} um ${formatSubmissionTime(answer.submitted_at)}`
            : `${prefix}: ${answer.guess} km um ${formatSubmissionTime(answer.submitted_at)}`;
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

function clearMapOverlays() {
  if (gameMap && gameMapOverlays.length) {
    gameMapOverlays.forEach((overlay) => {
      gameMap.removeOverlay(overlay);
    });
  }
  gameMapOverlays = [];
  const ortsschildContainer = document.getElementById("ortsschildContainer");
  if (ortsschildContainer) ortsschildContainer.innerHTML = "";
}

function getOrtsschildLayout(cityName) {
  const label = String(cityName || "").trim();
  const labelLength = Math.max(1, label.length);
  const useLargeTemplate = labelLength > 14;
  const refContainer = document.getElementById("ortsschildContainer") || document.getElementById("mapContainer");
  const containerWidth = refContainer ? refContainer.clientWidth : 0;
  const isMobile = window.matchMedia("(max-width: 768px)").matches;

  // Keep strict 3:2 proportions based on requested templates: 900x600 / 1260x840.
  const templateWidth = useLargeTemplate ? 1260 : 900;
  const templateHeight = useLargeTemplate ? 840 : 600;
  const displayScale = useLargeTemplate ? 0.22 : 0.24;
  let displayWidth = Math.round(templateWidth * displayScale);

  // Mobile fine-tuning: keep both labels readable without overwhelming the container.
  // Two plates sit side by side so each can use at most ~44% of total width.
  if (containerWidth > 0) {
    const maxByContainer = Math.floor(containerWidth * (isMobile ? 0.44 : 0.44));
    displayWidth = Math.min(displayWidth, maxByContainer);
  }
  displayWidth = Math.max(isMobile ? 116 : 148, displayWidth);
  const displayHeight = Math.round(displayWidth * (2 / 3));

  const horizontalPadding = Math.round(displayWidth * 0.1);
  const maxByHeight = Math.floor(displayHeight * (isMobile ? 0.38 : 0.43));
  const maxByWidth = Math.floor((displayWidth - 2 * horizontalPadding) / (labelLength * 0.64));
  const minFont = isMobile ? 11 : 13;
  const fontSize = Math.max(minFont, Math.min(maxByHeight, maxByWidth));
  const letterSpacing = labelLength > 16 ? "0" : (isMobile ? "0.01em" : "0.03em");

  return {
    displayWidth,
    displayHeight,
    fontSize,
    letterSpacing,
  };
}

function createOrtsschildOverlay(cityName, variant) {
  const container = document.getElementById("ortsschildContainer");
  if (!container) return null;

  const layout = getOrtsschildLayout(cityName);

  const wrapper = document.createElement("div");
  wrapper.className = `ortsschild-overlay ortsschild-${variant}`;

  const plate = document.createElement("div");
  plate.className = "ortsschild-plate";
  plate.style.setProperty("--ortsschild-width", `${layout.displayWidth}px`);
  plate.style.setProperty("--ortsschild-height", `${layout.displayHeight}px`);
  plate.style.setProperty("--ortsschild-font-size", `${layout.fontSize}px`);
  plate.style.setProperty("--ortsschild-letter-spacing", layout.letterSpacing);

  const text = document.createElement("div");
  text.className = "ortsschild-text";
  text.textContent = String(cityName || "").trim().toUpperCase();

  plate.appendChild(text);
  wrapper.appendChild(plate);
  container.appendChild(wrapper);

  return wrapper;
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
    let projection25832;
    try {
      proj4.defs("EPSG:25832", "+proj=utm +zone=32 +ellps=GRS80 +units=m +no_defs");
      const registerProj4 =
        typeof window.olRegisterProj4 === "function"
          ? window.olRegisterProj4
          : (ol.proj.proj4 && typeof ol.proj.proj4.register === "function"
            ? ol.proj.proj4.register
            : null);
      if (typeof registerProj4 === "function") {
        registerProj4(proj4);
      } else {
        console.error("[Map] proj4 register helper is unavailable");
        return null;
      }

      projection25832 = ol.proj.get("EPSG:25832");
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

    const defaultControls =
      typeof ol.control.defaults === "function"
        ? ol.control.defaults()
        : (ol.control.defaults && typeof ol.control.defaults.defaults === "function"
          ? ol.control.defaults.defaults()
          : ol.control.defaults === undefined
            ? null
            : null);
    if (!defaultControls) {
      console.error("[Map] OpenLayers default controls factory is unavailable");
      return null;
    }

    gameMap = new ol.Map({
      target: container,
      layers: [gameMapBaseLayer, gameMapFallbackLayer, gameMapFeatureLayer],
      controls: defaultControls.extend([
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

function formatCityLabel(cityName, maxLength = 18) {
  const safeName = String(cityName || "").trim();
  if (safeName.length <= maxLength) {
    return safeName;
  }
  return `${safeName.slice(0, maxLength - 1)}…`;
}

function createQuestionPointStyle(variant = "from") {
  const fillColor = variant === "to" ? "#f97316" : "#2563eb";
  return new ol.style.Style({
    image: new ol.style.Circle({
      radius: 11,
      fill: new ol.style.Fill({
        color: fillColor,
      }),
      stroke: new ol.style.Stroke({
        color: "#ffffff",
        width: 3,
      }),
    }),
  });
}

function renderQuestionMap(coordinates) {
  const container = document.getElementById("mapContainer");

  if (!coordinates || !coordinates.from || !coordinates.to) {
    pendingQuestionCoordinates = null;
    clearMapOverlays();
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
  clearMapOverlays();

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
    fromFeature.setStyle(createQuestionPointStyle("from"));

    const toFeature = new ol.Feature({ geometry: new ol.geom.Point(toPoint) });
    toFeature.setStyle(createQuestionPointStyle("to"));

    let lineCoordinates = [fromPoint, toPoint];
    const routePoints = Array.isArray(coordinates.route_points) ? coordinates.route_points : [];
    if (routePoints.length >= 2) {
      const transformedRoute = routePoints
        .map((pt) => {
          if (!pt || !Number.isFinite(Number(pt.lon)) || !Number.isFinite(Number(pt.lat))) {
            return null;
          }
          return ol.proj.transform([Number(pt.lon), Number(pt.lat)], "EPSG:4326", "EPSG:25832");
        })
        .filter(Boolean);
      if (transformedRoute.length >= 2) {
        lineCoordinates = transformedRoute;
      }
    }

    const lineFeature = new ol.Feature({ geometry: new ol.geom.LineString(lineCoordinates) });
    lineFeature.setStyle(
      new ol.style.Style({
        stroke: new ol.style.Stroke({
          color: "#16a34a",
          width: 4,
        }),
      }),
    );

    gameMapFeatureSource.addFeatures([lineFeature, fromFeature, toFeature]);
    createOrtsschildOverlay(coordinates.from.name, "from");
    createOrtsschildOverlay(coordinates.to.name, "to");

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

function clearRoundHighlights() {
  const panel = document.getElementById("roundHighlights");
  const list = document.getElementById("roundHighlightsList");
  if (list) {
    list.innerHTML = "";
  }
  if (panel) {
    panel.classList.remove("is-visible");
  }
}

function renderRoundHighlights(msg) {
  const panel = document.getElementById("roundHighlights");
  const list = document.getElementById("roundHighlightsList");
  if (!panel || !list) return;

  const standings = Array.isArray(msg.standings) ? msg.standings : [];
  const multiPlayer = standings.length > 1;

  const items = [];
  if (msg.closest_result?.player_name) {
    if (typeof msg.closest_result.difference_km === "number") {
      items.push({
        label: "Nächster dran",
        value: `${msg.closest_result.player_name}: ${msg.closest_result.guess} km, nur ${msg.closest_result.difference_km} km daneben`,
      });
    } else if (typeof msg.closest_result.difference_positions === "number") {
      items.push({
        label: "Nächster dran",
        value: `${msg.closest_result.player_name}: ${msg.closest_result.difference_positions} Positionsfehler`,
      });
    }
  }

  if (multiPlayer && msg.biggest_miss?.player_name) {
    if (typeof msg.biggest_miss.difference_km === "number") {
      items.push({
        label: "Größter Fehlschuss",
        value: `${msg.biggest_miss.player_name}: ${msg.biggest_miss.guess} km, ${msg.biggest_miss.difference_km} km daneben`,
      });
    } else if (typeof msg.biggest_miss.difference_positions === "number") {
      items.push({
        label: "Größter Fehlschuss",
        value: `${msg.biggest_miss.player_name}: ${msg.biggest_miss.difference_positions} Positionsfehler`,
      });
    }
  }

  if (msg.precision_bonus?.player_name) {
    items.push({
      label: "Perfekttreffer",
      value: `${msg.precision_bonus.player_name}: +${msg.precision_bonus.points} bei nur ${msg.precision_bonus.distance_error_km} km Fehler`,
    });
  }

  if (msg.comeback_highlight?.player_name) {
    items.push({
      label: "Comeback des Spiels",
      value: `${msg.comeback_highlight.player_name}: Platz ${msg.comeback_highlight.from_rank} auf ${msg.comeback_highlight.to_rank}`,
    });
  }

  if (multiPlayer) {
    items.push({
      label: "Platzierung nach Runde",
      type: "standings",
      standings,
    });
  }

  list.innerHTML = "";
  items.forEach((item) => {
    const article = document.createElement("article");
    article.className = "round-highlight-item";

    const label = document.createElement("span");
    label.className = "round-highlight-label";
    label.textContent = item.label;

    const value = document.createElement("strong");
    value.className = "round-highlight-value";
    if (item.type === "standings") {
      const ol = document.createElement("ol");
      ol.className = "round-standings-list";
      item.standings.forEach((entry, index) => {
        const li = document.createElement("li");
        li.className = "round-standings-item";
        const delta = Number(entry.delta || 0);
        const deltaText = delta === 0 ? "" : ` (${delta > 0 ? "+" : ""}${delta})`;
        li.textContent = `${index + 1}. ${entry.player_name}: ${entry.score}${deltaText}`;
        ol.appendChild(li);
      });
      value.appendChild(ol);
    } else {
      value.textContent = item.value;
    }

    article.appendChild(label);
    article.appendChild(value);
    list.appendChild(article);
  });

  panel.classList.toggle("is-visible", items.length > 0);
}

function handleJsonMessage(msg) {
  console.log("Message received:", msg);

  if (msg.type === "captcha_validated") {
    // CAPTCHA was successfully validated
    handleCaptchaValidated();
    appendMessage(t("captcha.success") || "CAPTCHA validated!");
  } else if (msg.type === "error") {
    // Check if it's a captcha error
    if (msg.message && msg.message.includes("CAPTCHA")) {
      showCaptchaError(msg.message);
      if (typeof clearCaptchaValidation === "function") {
        clearCaptchaValidation();
      } else {
        showCaptchaModal();
      }
    } else {
      appendMessage(`❌ ${msg.message || t("messages.connectionError")}`);
    }
  } else if (msg.type === "lobby_info") {
    if (typeof syncCaptchaRequirement === "function") {
      syncCaptchaRequirement(!!msg.captcha_required);
    }
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
    clearRoundHighlights();
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
    const questionVariant = msg.question_variant === "sorting"
      ? "sorting"
      : (msg.question_variant === "road" ? "road" : "air");
    currentQuestionVariant = questionVariant;
    const routePoints = Array.isArray(msg.route_points)
      ? msg.route_points
        .filter((pt) => pt && Number.isFinite(Number(pt.lat)) && Number.isFinite(Number(pt.lon)))
        .map((pt) => ({ lat: Number(pt.lat), lon: Number(pt.lon) }))
      : [];
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
        route_points: routePoints,
      }
      : null;
    
    // Update UI layout
    updateUILayout();

    // Store coordinates FIRST before starting map preparation
    if (coordinates && questionVariant !== "sorting") {
      pendingQuestionCoordinates = coordinates;
      // START MAP PREPARATION IMMEDIATELY (do not wait for updateUILayout)
      queueMapPreparation();
      // Fast path: try rendering immediately; queueMapPreparation remains fallback.
      renderQuestionMap(coordinates);
    } else if (questionVariant === "sorting") {
      pendingQuestionCoordinates = null;
    }

    applyQuestionVariantUI(questionVariant);

    const localizedQuestion = questionVariant === "sorting"
      ? (msg.sorting_prompt || `Sortiere die Zahlen ${msg.sorting_order === "desc" ? "absteigend" : "aufsteigend"}: ${(msg.sorting_numbers || []).join(", ")}`)
      : t(
        questionVariant === "road" ? "question.roadDistanceTemplate" : "question.distanceTemplate",
        {
          city1: cityFrom,
          city2: cityTo,
        },
      );
    appendMessage(`🟡 ${t("messages.roundUpdate")} ${msg.round}/${msg.max_rounds}: ${localizedQuestion}`);
    const city1El = document.getElementById("city1");
    const city2El = document.getElementById("city2");
    const guessInputEl = document.getElementById("guessInput");
    const countdownTextEl = document.getElementById("countdownText");
    const sortingPromptBannerEl = document.getElementById("sortingPromptBanner");

    if (city1El) city1El.textContent = questionVariant === "sorting" ? "-" : cityFrom;
    if (city2El) city2El.textContent = questionVariant === "sorting" ? "-" : cityTo;
    const questionTextEl = document.querySelector("#questionCard .question-text");
    if (questionTextEl) {
      questionTextEl.textContent = questionVariant === "sorting"
        ? (msg.sorting_prompt || `Sortiere die Zahlen ${msg.sorting_order === "desc" ? "von groß nach klein" : "von klein nach groß"}`)
        : t(
          questionVariant === "road" ? "question.askRoadDistance" : "question.askDistance",
        );
    }

    if (sortingPromptBannerEl) {
      sortingPromptBannerEl.textContent = msg.sorting_prompt
        || `Sortiere die Zahlen ${msg.sorting_order === "desc" ? "von groß nach klein" : "von klein nach groß"}`;
    }

    if (questionVariant === "sorting") {
      initializeSortingQuestion(msg.sorting_numbers || [], msg.sorting_order || "asc");
    }

    if (guessInputEl) guessInputEl.value = "";
    resetAnswerSubmissionState();
    if (questionVariant !== "sorting" && guessInputEl) guessInputEl.focus();
    
    if (countdownTextEl) {
      countdownTextEl.textContent = t("countdown.answerTimeRemaining");
    }

    // Speed Round indicator
    const speedBanner = document.getElementById("speedRoundBanner");
    const countdownCard = document.getElementById("countdownCard");
    const isSpeedRound = msg.speed_round === true;
    if (speedBanner) speedBanner.hidden = !isSpeedRound;
    if (countdownCard) countdownCard.classList.toggle("speed-round-active", isSpeedRound);

    startManagedCountdown(msg.time_limit);
  } else if (msg.type === "game_status") {
    appendMessage(t("messages.statusValue", { status: msg.status }));
  } else if (msg.type === "answer_received") {
    guessSubmissionPending = false;
    guessLockedForRound = false;
    setGuessControlsDisabled(false);
    const answerText = Array.isArray(msg.sorted_numbers)
      ? msg.sorted_numbers.join(" > ")
      : String(msg.guess ?? msg.answer ?? "-");
    showAnswerSubmissionHint(
      msg.updated
        ? `Antwort aktualisiert: ${answerText} (${formatSubmissionTime(msg.submitted_at)})`
        : `Antwort gespeichert: ${answerText} (${formatSubmissionTime(msg.submitted_at)})`,
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
    renderRoundHighlights(msg);
    const hasMultiplePlayers = Array.isArray(msg.standings) && msg.standings.length > 1;
    const summary = msg.standings
      .map((s) => `${s.player_name}: ${s.score} (${s.delta >= 0 ? "+" : ""}${s.delta})`)
      .join(" | ");
    if (msg.question_variant === "sorting") {
      appendMessage(
        `🧩 Runde ${msg.round}: ${msg.winner} gewinnt. Korrekte Reihenfolge: ${(msg.correct_order || []).join(" > ")} | ${summary}`,
      );
    } else {
      appendMessage(
        t("messages.roundResult", {
          round: msg.round,
          winner: msg.winner,
          distance: msg.correct_distance,
          summary,
        }),
      );
    }

    if (Array.isArray(msg.bonus_events)) {
      msg.bonus_events.forEach((bonus) => {
        if (bonus.type === "perfect_hit_bonus") {
          appendMessage(
            `🎯 Bonus: ${bonus.player_name} +${bonus.points} (Perfekttreffer, nur ${bonus.distance_error_km} km daneben)`,
          );
        } else if (bonus.type === "streak_bonus") {
          appendMessage(
            `🔥 Bonus: ${bonus.player_name} +${bonus.points} (${bonus.streak} Siege in Folge)`,
          );
        }
      });
    }

    if (msg.closest_result && msg.closest_result.player_name) {
      if (typeof msg.closest_result.difference_km === "number") {
        appendMessage(
          `📍 Nächster dran: ${msg.closest_result.player_name} (${msg.closest_result.guess} km, ${msg.closest_result.difference_km} km daneben)`,
        );
      } else if (typeof msg.closest_result.difference_positions === "number") {
        appendMessage(
          `📍 Nächster dran: ${msg.closest_result.player_name} (${msg.closest_result.difference_positions} Positionsfehler)`,
        );
      }
    }

    if (hasMultiplePlayers && msg.biggest_miss && msg.biggest_miss.player_name) {
      if (typeof msg.biggest_miss.difference_km === "number") {
        appendMessage(
          `💥 Größter Fehlschuss: ${msg.biggest_miss.player_name} (${msg.biggest_miss.guess} km, ${msg.biggest_miss.difference_km} km daneben)`,
        );
      } else if (typeof msg.biggest_miss.difference_positions === "number") {
        appendMessage(
          `💥 Größter Fehlschuss: ${msg.biggest_miss.player_name} (${msg.biggest_miss.difference_positions} Positionsfehler)`,
        );
      }
    }

    if (msg.precision_bonus && msg.precision_bonus.player_name) {
      appendMessage(
        `✨ Präzisions-Bonus: ${msg.precision_bonus.player_name} +${msg.precision_bonus.points}`,
      );
    }

    if (msg.comeback_highlight && msg.comeback_highlight.player_name) {
      appendMessage(
        `🚀 Comeback des Spiels: ${msg.comeback_highlight.player_name} von Platz ${msg.comeback_highlight.from_rank} auf ${msg.comeback_highlight.to_rank}`,
      );
    }
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
      syncPlayerNameUI(playerName);
      document.getElementById("setupPhase").style.display = "none";
      document.getElementById("gamePhase").style.display = "block";
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
    playerName = msg.name || playerName;
    localStorage.setItem(STORAGE_KEYS.PLAYER_ID, currentPlayerId);
    localStorage.setItem(STORAGE_KEYS.PLAYER_NAME, playerName);
    syncPlayerNameUI(playerName);
    if (restorePendingJoinGameId && !currentGameId) {
      joinGameById(restorePendingJoinGameId, restorePendingJoinPin);
    }
    restorePendingJoinGameId = "";
    restorePendingJoinPin = "";
    appendMessage(t("messages.nameSet", { name: playerName }));
  }

  updateMatchHud();
}
function set_countdown(countdownLimitSeconds) {
  startManagedCountdown(countdownLimitSeconds);
}

function syncQuestionTypeTiles() {
  const mappings = [
    { inputId: "settingEnableAirQuestions", tileId: "tileAirQuestions" },
    { inputId: "settingEnableRoadQuestions", tileId: "tileRoadQuestions" },
    { inputId: "settingEnableSortingQuestions", tileId: "tileSortingQuestions" },
    { inputId: "settingEnableSpeedRounds", tileId: "tileSpeedRounds" },
  ];

  mappings.forEach(({ inputId, tileId }) => {
    const inputEl = document.getElementById(inputId);
    const tileEl = document.getElementById(tileId);
    if (!inputEl || !tileEl) return;
    const active = !!inputEl.checked;
    tileEl.classList.toggle("is-active", active);
    tileEl.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

function toggleQuestionTypeTile(kind) {
  const tileMap = {
    air: "settingEnableAirQuestions",
    road: "settingEnableRoadQuestions",
    sorting: "settingEnableSortingQuestions",
    speed: "settingEnableSpeedRounds",
  };
  const inputId = tileMap[kind];
  if (!inputId) return;
  const inputEl = document.getElementById(inputId);
  if (!inputEl || inputEl.disabled) return;

  const isPrimaryType = kind === "air" || kind === "road" || kind === "sorting";
  if (isPrimaryType && inputEl.checked) {
    const enabledPrimaryCount = ["settingEnableAirQuestions", "settingEnableRoadQuestions", "settingEnableSortingQuestions"]
      .map((id) => document.getElementById(id))
      .filter((el) => el && el.checked)
      .length;
    if (enabledPrimaryCount <= 1) {
      appendMessage(`❌ ${t("serverErrors.atLeastOneQuestionType")}`);
      return;
    }
  }

  inputEl.checked = !inputEl.checked;
  syncQuestionTypeTiles();
  if (kind === "road") {
    applyRoadQuestionControls(inputEl.checked);
  }
  debouncedSaveSettings();
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
    const enableAirQuestionsInput = document.getElementById("settingEnableAirQuestions");
    const enableRoadQuestionsInput = document.getElementById("settingEnableRoadQuestions");
    const enableSortingQuestionsInput = document.getElementById("settingEnableSortingQuestions");
    const enableSpeedRoundsInput = document.getElementById("settingEnableSpeedRounds");
    const roadQuestionRatioInput = document.getElementById("settingRoadQuestionRatio");
    if (maxRoundsInput) maxRoundsInput.value = config.max_rounds;
    if (countdownInput) countdownInput.value = config.countdown_seconds;
    if (pauseTimeInput) pauseTimeInput.value = config.pause_between_rounds_seconds;
    if (autoAdvanceAllAnsweredInput) autoAdvanceAllAnsweredInput.checked = !!config.auto_advance_on_all_answers;
    if (firstAnswerEndsRoundInput) firstAnswerEndsRoundInput.checked = !!config.first_answer_ends_round;
    if (wrongAnswerPointsOthersInput) wrongAnswerPointsOthersInput.checked = !!config.wrong_answer_points_others;
    if (enableAirQuestionsInput && typeof config.enable_air_questions === "boolean") {
      enableAirQuestionsInput.checked = config.enable_air_questions;
    }
    const roadQuestionsEnabled = config.enable_road_questions !== false;
    if (enableRoadQuestionsInput) enableRoadQuestionsInput.checked = roadQuestionsEnabled;
    if (enableSortingQuestionsInput) enableSortingQuestionsInput.checked = config.enable_sorting_questions !== false;
    if (enableSpeedRoundsInput) enableSpeedRoundsInput.checked = config.enable_speed_rounds !== false;
    if (roadQuestionRatioInput) {
      const parsedRatio = Number.parseInt(config.road_question_ratio_percent, 10);
      roadQuestionRatioInput.value = Number.isNaN(parsedRatio) ? "50" : String(Math.max(0, Math.min(100, parsedRatio)));
    }
    // Handle no-time-limit flag (answer_time_seconds == 0)
    const noTimeLimit = config.answer_time_seconds === 0;
    const noTimeLimitInput = document.getElementById("settingNoTimeLimit");
    if (noTimeLimitInput) noTimeLimitInput.checked = noTimeLimit;
    if (answerTimeInput) {
      answerTimeInput.value = noTimeLimit ? "" : config.answer_time_seconds;
      answerTimeInput.disabled = noTimeLimit;
    }
    applyNoTimeLimitVisibility(!!config.first_answer_ends_round);
    applyRoadQuestionControls(roadQuestionsEnabled);
    syncQuestionTypeTiles();
    if (currentIsHost) {
      localStorage.setItem(STORAGE_KEYS.CREATOR_SETTINGS, JSON.stringify(config));
    }
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

  clearMapOverlays();

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
    document.getElementById("settingPauseTime"),
    document.getElementById("settingAutoAdvanceAllAnswered"),
    document.getElementById("settingFirstAnswerEndsRound"),
    document.getElementById("settingWrongAnswerPointsOthers"),
    document.getElementById("settingNoTimeLimit"),
    document.getElementById("settingEnableAirQuestions"),
    document.getElementById("settingEnableRoadQuestions"),
    document.getElementById("settingEnableSortingQuestions"),
    document.getElementById("settingEnableSpeedRounds"),
  ].forEach((inputEl) => {
    if (inputEl) {
      inputEl.disabled = !canEditSettings;
    }
  });
  // answerTime is conditionally disabled by noTimeLimit; only re-enable when canEdit AND not noTimeLimit
  const answerTimeEl = document.getElementById("settingAnswerTime");
  const noTimeLimitEl = document.getElementById("settingNoTimeLimit");
  const roadRatioEl = document.getElementById("settingRoadQuestionRatio");
  const enableRoadQuestionsEl = document.getElementById("settingEnableRoadQuestions");
  if (answerTimeEl) answerTimeEl.disabled = !canEditSettings || !!(noTimeLimitEl?.checked);
  if (roadRatioEl) roadRatioEl.disabled = !canEditSettings || !(enableRoadQuestionsEl?.checked);

  [
    document.getElementById("tileAirQuestions"),
    document.getElementById("tileRoadQuestions"),
    document.getElementById("tileSortingQuestions"),
    document.getElementById("tileSpeedRounds"),
  ].forEach((tileEl) => {
    if (tileEl) {
      tileEl.disabled = !canEditSettings;
    }
  });

  syncQuestionTypeTiles();

  if (saveSettingsBtn) {
    saveSettingsBtn.disabled = !canEditSettings;
  }
}

function applyNoTimeLimitVisibility(firstAnswerEndsRound) {
  const row = document.getElementById("noTimeLimitRow");
  if (row) row.style.display = firstAnswerEndsRound ? "" : "none";
}

function applyRoadQuestionControls(enabled) {
  const ratioField = document.getElementById("roadRatioField");
  const ratioInput = document.getElementById("settingRoadQuestionRatio");
  if (ratioField) ratioField.style.opacity = enabled ? "1" : "0.6";
  if (ratioInput) ratioInput.disabled = !enabled;
}

let _saveSettingsTimer = null;
function debouncedSaveSettings() {
  clearTimeout(_saveSettingsTimer);
  _saveSettingsTimer = setTimeout(saveGameSettings, 400);
}

function saveGameSettings() {
  if (!currentIsHost || currentGameStatus !== "waiting" || currentSettingsLocked) {
    return;
  }

  const maxRounds = parseInt(document.getElementById("settingMaxRounds")?.value || "", 10);
  const countdownSeconds = parseInt(document.getElementById("settingCountdown")?.value || "", 10);
  const noTimeLimit = !!document.getElementById("settingNoTimeLimit")?.checked;
  const firstAnswerEndsRound = !!document.getElementById("settingFirstAnswerEndsRound")?.checked;
  const answerTimeSeconds = noTimeLimit ? 0 : parseInt(document.getElementById("settingAnswerTime")?.value || "", 10);
  const pauseBetweenRoundsSeconds = parseInt(document.getElementById("settingPauseTime")?.value || "", 10);
  const autoAdvanceOnAllAnswers = !!document.getElementById("settingAutoAdvanceAllAnswered")?.checked;
  const wrongAnswerPointsOthers = !!document.getElementById("settingWrongAnswerPointsOthers")?.checked;
  const enableAirQuestions = !!document.getElementById("settingEnableAirQuestions")?.checked;
  const enableRoadQuestions = !!document.getElementById("settingEnableRoadQuestions")?.checked;
  const enableSortingQuestions = !!document.getElementById("settingEnableSortingQuestions")?.checked;
  const enableSpeedRounds = !!document.getElementById("settingEnableSpeedRounds")?.checked;
  const roadQuestionRatioPercent = parseInt(document.getElementById("settingRoadQuestionRatio")?.value || "", 10);

  const ranges = [
    { value: maxRounds,               min: 1,  max: 20,  label: "Max. Runden" },
    { value: countdownSeconds,         min: 1,  max: 30,  label: "Countdown" },
    { value: pauseBetweenRoundsSeconds,min: 1,  max: 30,  label: "Pause" },
  ];
  if (!noTimeLimit) {
    ranges.push({ value: answerTimeSeconds, min: 5, max: 180, label: "Antwortzeit" });
  }
  ranges.push({ value: roadQuestionRatioPercent, min: 0, max: 100, label: "Straßenanteil" });
  const invalid = ranges.filter((r) => Number.isNaN(r.value) || r.value < r.min || r.value > r.max);
  if (invalid.length > 0) {
    const details = invalid.map((r) => `${r.label}: ${r.min}–${r.max}`).join(", ");
    alert(`Ungültige Einstellungswerte.\nErlaubte Bereiche: ${details}`);
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
      enable_air_questions: enableAirQuestions,
      enable_road_questions: enableRoadQuestions,
      road_question_ratio_percent: roadQuestionRatioPercent,
      enable_sorting_questions: enableSortingQuestions,
      enable_speed_rounds: enableSpeedRounds,
    },
  });

  localStorage.setItem(
    STORAGE_KEYS.CREATOR_SETTINGS,
    JSON.stringify({
      max_rounds: maxRounds,
      countdown_seconds: countdownSeconds,
      answer_time_seconds: answerTimeSeconds,
      pause_between_rounds_seconds: pauseBetweenRoundsSeconds,
      auto_advance_on_all_answers: autoAdvanceOnAllAnswers,
      first_answer_ends_round: firstAnswerEndsRound,
      wrong_answer_points_others: wrongAnswerPointsOthers,
      enable_air_questions: enableAirQuestions,
      enable_road_questions: enableRoadQuestions,
      road_question_ratio_percent: roadQuestionRatioPercent,
      enable_sorting_questions: enableSortingQuestions,
      enable_speed_rounds: enableSpeedRounds,
    }),
  );

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
  syncPlayerNameUI(playerName);
  document.getElementById("setupPhase").style.display = "none";
  document.getElementById("gamePhase").style.display = "block";

  sendMessage({ type: "set_name", data: { name: playerName } });
  if (!restorePendingJoinGameId && storedGameId) {
    restorePendingJoinGameId = storedGameId;
  }
}

async function copyRejoinLink() {
  if (!currentGameId) {
    alert("Es gibt aktuell keinen Spielcode zum Teilen.");
    return;
  }

  const baseUrl = `${window.location.origin}${window.location.pathname}`;
  const rejoinUrl = `${baseUrl}?game=${encodeURIComponent(currentGameId)}`;

  try {
    if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
      await navigator.clipboard.writeText(rejoinUrl);
    } else {
      const helper = document.createElement("textarea");
      helper.value = rejoinUrl;
      helper.setAttribute("readonly", "true");
      helper.style.position = "absolute";
      helper.style.left = "-9999px";
      document.body.appendChild(helper);
      helper.select();
      document.execCommand("copy");
      document.body.removeChild(helper);
    }
    appendMessage(`🔗 Rejoin-Link kopiert: ${rejoinUrl}`);
  } catch (error) {
    console.error("Could not copy rejoin link:", error);
    appendMessage("❌ Rejoin-Link konnte nicht kopiert werden.");
  }
}

function getStoredCreatorSettings() {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.CREATOR_SETTINGS);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch (err) {
    console.warn("Could not parse stored creator settings:", err);
    return null;
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

function syncPlayerNameUI(name) {
  const normalizedName = (name || "").trim();
  const setupInput = document.getElementById("playerName");
  const editInput = document.getElementById("playerNameEdit");
  const currentNameLabel = document.getElementById("currentPlayerName");

  if (setupInput) setupInput.value = normalizedName;
  if (editInput) editInput.value = normalizedName;
  if (currentNameLabel) currentNameLabel.textContent = normalizedName;
}

function toggleNameEditMode(open) {
  if (currentGameId) return;
  const controls = document.getElementById("playerNameEditControls");
  if (!controls) return;

  const shouldOpen = typeof open === "boolean" ? open : !controls.classList.contains("is-open");
  controls.classList.toggle("is-open", shouldOpen);

  if (shouldOpen) {
    focusAndSelect("playerNameEdit");
  }
}

function registerKeyboardUX() {
  const playerNameInput = document.getElementById("playerName");
  const playerNameEditInput = document.getElementById("playerNameEdit");
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

  if (playerNameEditInput) {
    playerNameEditInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        setPlayerName("playerNameEdit");
      } else if (event.key === "Escape") {
        event.preventDefault();
        toggleNameEditMode(false);
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
      const setupPhaseVisible = document.getElementById("setupPhase")?.style.display !== "none";
      if (setupPhaseVisible) {
        focusAndSelect("playerName");
      } else if (!currentGameId) {
        toggleNameEditMode(true);
      }
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

function setPlayerName(inputId = "playerName") {
  const nameInputElement = document.getElementById(inputId);
  const newName = nameInputElement ? nameInputElement.value.trim() : "";
  if (!newName) return alert(t("messages.nameCannotBeEmpty"));
  playerName = newName;
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
  if (inputId === "playerNameEdit") {
    toggleNameEditMode(false);
  }
  syncPlayerNameUI(playerName);
  updateUILayout();
}

function createGame() {
  const storedSettings = getStoredCreatorSettings();
  const sanitizedSettings = storedSettings && typeof storedSettings === "object"
    ? { ...storedSettings }
    : null;
  const message = {
    type: "create_game",
    data: sanitizedSettings ? { config: sanitizedSettings } : {},
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
  if (currentQuestionVariant === "sorting") {
    submitSortingAnswer();
    return;
  }

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
  applyQuestionVariantUI(currentQuestionVariant);
  resetAnswerSubmissionState();
  resetCountdownDisplay();
  captureJoinIntentFromUrl();
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
