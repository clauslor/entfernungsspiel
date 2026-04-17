let ws;
let playerName = "";
let currentGameId = "";
let currentPlayerId = "";
let currentPlayers = [];
let totalTime;
let isConnected = false;
let restorePendingJoinGameId = "";

const STORAGE_KEYS = {
  PLAYER_NAME: "entfernungsspiel.playerName",
  PLAYER_ID: "entfernungsspiel.playerId",
  GAME_ID: "entfernungsspiel.gameId",
};

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
    appendMessage(`✅ Connected to server: wss://${window.location.host}${base}/ws`);
    sendMessage({ type: "tab_active", data: {} });
    restoreSessionFromStorage();
  };

  ws.onclose = () => {
    isConnected = false;
    appendMessage("❌ Disconnected from server");
    setTimeout(connect, 2000); // Reconnect after 2 seconds
  };

  ws.onerror = (error) => {
    appendMessage("❌ Connection error");
    console.error("WebSocket error:", error);
  };
}

function handleJsonMessage(msg) {
  console.log("Message received:", msg);

  if (msg.type === "lobby_info") {
    appendMessage(
      `📋 Lobby info received. Active games: ${msg.active_games.length}`,
    );
    if (msg.active_games.length > 0) {
      appendMessage("Available games:\n");
      msg.active_games.forEach((game) => {
        appendMessage(`  - Game ${game.id} (${game.player_count} players)`);
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
    document.getElementById("inGameButtons").style.display = "block";
    document.getElementById("inGamePlayerList").innerHTML =
      `<li>⏳ ${playerName} (you)</li>`;
    document.getElementById("playerCount").textContent = "1";
    appendMessage(`✅ Game created! Game ID: ${msg.game_id}`);
  } else if (msg.type === "game_joined") {
    currentGameId = msg.game_id;
    saveSessionToStorage();
    document.getElementById("gameIdDisplay").textContent = msg.game_id;
    document.getElementById("gameInfo").style.display = "block";
    appendMessage(`✅ Joined game ${msg.game_id}`);
    document.getElementById("inGameButtons").style.display = "block";
  } else if (msg.type === "game_info") {
    currentGameId = msg.game_id;
    saveSessionToStorage();
    currentPlayers = msg.players;
    document.getElementById("gameIdDisplay").textContent = msg.game_id;
    document.getElementById("gameInfo").style.display = "block";
    appendMessage(
      `📊 Game info - Status: ${msg.game_id}, Players: ${msg.players.length}`,
    );
    updateGameList(msg.game_id, msg.players);
    updateGameSettings(msg.game_id, msg.config);
    document.getElementById("inGameButtons").style.display = "block";
  } else if (msg.type === "game_starting") {
    appendMessage(`⏳ Game starting in ${msg.countdown} seconds...`);
  } else if (msg.type === "game_started") {
    appendMessage(`🎮 Game started!`);
    if (msg.config) {
      document.getElementById("rulesText").textContent =
        `Max Rounds: ${msg.config.max_rounds}, Answer Time: ${msg.config.answer_time_seconds}s, Pause: ${msg.config.pause_between_rounds_seconds}s`;
    }
  } else if (msg.type === "new_question") {
    appendMessage(`🟡 Round ${msg.round}/${msg.max_rounds}: ${msg.question}`);
    document.getElementById("city1").textContent = `${msg.cities[0]}`;
    document.getElementById("city2").textContent = `${msg.cities[1]}`;
    document.getElementById("guessInput").value = "";
    document.getElementById("guessInput").focus();
    // Update map
    if (msg.map_svg) {
      document.getElementById("mapContainer").innerHTML = msg.map_svg;
    }
    set_countdown(msg.time_limit);
  } else if (msg.type === "game_status") {
    appendMessage(`📈 Status: ${msg.status}`);
  } else if (msg.type === "answer_received") {
    // const guess = msg.guess;
    // const correct = msg.correct_distance;
    // const diff = msg.difference;
    // const accuracy = msg.accuracy_percent;

    // // Display feedback
    // document.getElementById("feedbackGuess").textContent = guess;
    // document.getElementById("feedbackCorrect").textContent = correct;
    // document.getElementById("feedbackDiff").textContent = diff;
    // document.getElementById("feedbackAccuracy").textContent = accuracy;
    // document.getElementById("answerFeedback").style.display = "block";

    // // Disable submit button momentarily
    // document.getElementById("guessInput").disabled = true;
    // const originalText = document.querySelector('.answer-card .btn-primary').textContent;
    // document.querySelector('.answer-card .btn-primary').disabled = true;

    appendMessage(`✅ Your answer received: ${msg.guess} km`);
  } else if (msg.type === "countdown") {
    const val = msg.value || "...";
    document.getElementById("countdownText").textContent = `Countdown: ${val}`;
  } else if (msg.type === "player_joined") {
    // Note: Player joined message doesn't include full player data, so we'll wait for game_info update
    appendMessage(`👋 ${msg.player} joined the game`);
  } else if (msg.type === "player_left") {
    // Remove player from local state
    currentPlayers = currentPlayers.filter((p) => p.id !== msg.player_id);
    // Re-render player lists
    updateGameList(currentGameId, currentPlayers);
    appendMessage(`👋 Player left the game`);
  } else if (msg.type === "player_ready_changed") {
    // Update local player state
    const playerIndex = currentPlayers.findIndex((p) => p.id === msg.player_id);
    if (playerIndex !== -1) {
      currentPlayers[playerIndex].ready = msg.ready;
      // Re-render player lists
      updateGameList(currentGameId, currentPlayers);
    }
    appendMessage(
      `${msg.ready ? "✓" : "✕"} Player is ${msg.ready ? "ready" : "not ready"}`,
    );
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
    appendMessage(`❗ ${msg.name || "A player"} left the browser tab`);
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
  } else if (msg.type === "error") {
    appendMessage(`❌ Error: ${msg.message}`);
    if (msg.message && msg.message.includes("Cannot join game")) {
      clearStoredGame();
    }
  } else if (msg.type === "game_finished") {
    // Show game finished modal with results
    document.getElementById("winnerName").textContent = msg.winner || "Unknown";

    const scoresTableBody = document.getElementById("scoresTableBody");
    scoresTableBody.innerHTML = "";

    if (msg.final_scores && Object.keys(msg.final_scores).length > 0) {
      let scoreIndex = 1;
      const sortedScores = Object.entries(msg.final_scores).sort(
        (a, b) => b[1].score - a[1].score,
      );

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

    // Show the modal
    const modal = document.getElementById("gameFinishedModal");
    modal.style.display = "flex";

    // Still log to messages for reference
    appendMessage(`🎉 Game finished! Winner: ${msg.winner}`);
    document.getElementById("inGameButtons").style.display = "none";
    document.getElementById("gameInfo").style.display = "none";
    clearStoredGame();
  } else if (msg.type === "name_set") {
    currentPlayerId = msg.player_id;
    localStorage.setItem(STORAGE_KEYS.PLAYER_ID, currentPlayerId);
    localStorage.setItem(STORAGE_KEYS.PLAYER_NAME, msg.name);
    if (restorePendingJoinGameId && !currentGameId) {
      joinGameById(restorePendingJoinGameId);
    }
    restorePendingJoinGameId = "";
    appendMessage(`✅ Your name set to: ${msg.name}`);
  }
}
function set_countdown(countdownLimitSeconds) {
  // Calculate the target end time
  const endTime = Date.now() + countdownLimitSeconds * 1000;

  // Function to update the countdown display
  function updateCountdown() {
    const now = Date.now();
    let remaining = Math.floor((endTime - now) / 1000);

    // If time is up
    if (remaining <= 0) {
      document.getElementById("countdown").textContent = "Time's up!";
      clearInterval(timerInterval);
      return;
    }

    // Calculate minutes and seconds
    const minutes = Math.floor(remaining / 60);
    const seconds = remaining % 60;

    // Display with leading zeros
    document.getElementById("countdown").textContent =
      `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }

  // Initial call to display immediately
  updateCountdown();

  // Update every second
  const timerInterval = setInterval(updateCountdown, 1000);
}
function updateGameSettings(game_id, config) {
  if (config) {
    document.getElementById("rulesText").textContent =
      `Max Rounds: ${config.max_rounds}, Answer Time: ${config.answer_time_seconds}s, Pause: ${config.pause_between_rounds_seconds}s`;
  }
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
  localStorage.removeItem(STORAGE_KEYS.GAME_ID);
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
    empty.textContent = "No open games right now.";
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
      joinGameById(game.id);
    };
    item.appendChild(link);
    list.appendChild(item);
  });
}

function joinGameById(gameId) {
  if (!gameId) return;
  document.getElementById("gameIdInput").value = gameId;
  sendMessage({ type: "join_game", data: { game_id: gameId } });
  appendMessage(`Joining game ${gameId}...`);
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

function setPlayerName() {
  const nameInput = document.getElementById("playerName").value.trim();
  if (!nameInput) return alert("Name cannot be empty.");
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
}

function createGame() {
  const message = {
    type: "create_game",
    data: {
      config: {
        max_rounds: 5,
        countdown_seconds: 3,
        answer_time_seconds: 15,
        pause_between_rounds_seconds: 3,
      },
    },
  };
  sendMessage(message);
  appendMessage("Creating new game...");
}

function showJoinGame() {
  document.getElementById("joinGameForm").style.display = "block";
}

function hideJoinGame() {
  document.getElementById("joinGameForm").style.display = "none";
  document.getElementById("gameIdInput").value = "";
}

function joinGame() {
  const gameId = document.getElementById("gameIdInput").value.trim();
  if (!gameId) return alert("Please enter a game ID.");

  joinGameById(gameId);
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
  appendMessage("You are now ready!");
}

function leaveGame() {
  const message = { type: "leave_game", data: {} };
  sendMessage(message);
  clearStoredGame();
  document.getElementById("inGameButtons").style.display = "none";
  document.getElementById("gameInfo").style.display = "none";
  appendMessage("You left the game.");
}

function playAgain() {
  // Close modal
  document.getElementById("gameFinishedModal").style.display = "none";
  // Create new game
  createGame();
}

function backToLobby() {
  // Close modal
  document.getElementById("gameFinishedModal").style.display = "none";
  // Reset UI to show setup phase
  document.getElementById("setupPhase").style.display = "none";
  document.getElementById("gamePhase").style.display = "block";
  document.getElementById("inGameButtons").style.display = "none";
  document.getElementById("gameInfo").style.display = "none";
  currentGameId = "";
  appendMessage("Back to lobby. Ready to create or join a new game!");
}

function sendGuess() {
  const guess = document.getElementById("guessInput").value.trim();
  if (!guess) return alert("Please enter a distance.");

  const guessNum = parseInt(guess);
  if (isNaN(guessNum) || guessNum < 0)
    return alert("Please enter a valid number.");

  const message = { type: "submit_answer", data: { guess: guessNum } };
  sendMessage(message);
  // TODO: fade in out feedback card
}

function updateAnswer() {
  // Show the input field again and clear feedback
  document.getElementById("answerFeedback").style.display = "none";
  document.getElementById("guessInput").disabled = false;
  document.getElementById("guessInput").value = "";
  document.getElementById("guessInput").focus();
  document.querySelector(".answer-card .btn-primary").disabled = false;
  appendMessage("📝 You can now update your answer");
}

function keepAnswer() {
  // Hide feedback, move to next round
  document.getElementById("answerFeedback").style.display = "none";
  document.getElementById("guessInput").disabled = false;
  document.getElementById("guessInput").value = "";
  document.querySelector(".answer-card .btn-primary").disabled = false;
  appendMessage("✅ Answer locked in! Waiting for other players...");
}

function sendMessage(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg));
  } else {
    appendMessage("❌ Not connected to server");
  }
}

window.onload = () => {
  const storedName = localStorage.getItem(STORAGE_KEYS.PLAYER_NAME) || "";
  if (storedName) {
    playerName = storedName;
    document.getElementById("playerName").value = storedName;
    document.getElementById("setupPhase").style.display = "none";
    document.getElementById("gamePhase").style.display = "block";
    document.getElementById("currentPlayerName").textContent = storedName;
  }
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
