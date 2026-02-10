/**
 * PhoneChess — этап 1: лобби, очередь, создание партии по WebSocket.
 */
(function () {
  const TIME_CONTROLS = ['3+0', '3+2', '5+0', '5+3', '10+0', '15+10'];

  const API_URL = (function () {
    const u = new URL(document.baseURI || window.location.href);
    const protocol = u.protocol === 'https:' ? 'wss:' : 'ws:';
    return protocol + '//' + u.host;
  })();

  let ws = null;
  let currentQueue = null;
  let reconnectTimer = null;

  const $ = (id) => document.getElementById(id);
  const lobbyButtons = $('lobby-buttons');
  const lobbyScreen = $('lobby-screen');
  const gameScreen = $('game-screen');
  const waitingScreen = $('waiting-screen');
  const wsStatus = $('ws-status');
  const gameMeta = $('game-meta');
  const btnCancelQueue = $('btn-cancel-queue');
  const btnBackGame = $('btn-back-game');

  function getInitData() {
    if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData) {
      return window.Telegram.WebApp.initData;
    }
    return '';
  }

  /** Для теста без Telegram: уникальный uid на вкладку (DEBUG=1 на бэкенде) */
  function getDebugUid() {
    if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData) return undefined;
    return Math.floor(Math.random() * 1e9);
  }

  function showScreen(id) {
    document.querySelectorAll('.screen').forEach(el => el.classList.remove('active'));
    const el = document.getElementById(id);
    if (el) el.classList.add('active');
  }

  function setWsStatus(text, className) {
    wsStatus.textContent = text;
    wsStatus.className = 'ws-status' + (className ? ' ' + className : '');
  }

  function renderLobbyButtons(counts) {
    counts = counts || {};
    lobbyButtons.innerHTML = TIME_CONTROLS.map(key => {
      const n = counts[key] != null ? counts[key] : 0;
      return `
        <button type="button" class="mode-btn" data-time="${key}">
          ${key}
          <span class="queue-count">${n} в очереди</span>
        </button>
      `;
    }).join('');

    lobbyButtons.querySelectorAll('.mode-btn').forEach(btn => {
      btn.addEventListener('click', () => onModeClick(btn.dataset.time));
    });
  }

  function onModeClick(timeControl) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    currentQueue = timeControl;
    ws.send(JSON.stringify({ type: 'join_queue', time_control: timeControl }));
    showScreen('waiting-screen');
  }

  function leaveCurrentQueue() {
    if (!currentQueue || !ws || ws.readyState !== WebSocket.OPEN) {
      showScreen('lobby-screen');
      currentQueue = null;
      return;
    }
    ws.send(JSON.stringify({ type: 'leave_queue', time_control: currentQueue }));
    currentQueue = null;
    showScreen('lobby-screen');
  }

  function connect() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
    setWsStatus('Подключение…');
    ws = new WebSocket(API_URL + '/ws');

    ws.onopen = function () {
      const initData = getInitData();
      const payload = { type: 'auth', init_data: initData };
      const debugUid = getDebugUid();
      if (debugUid != null) payload.debug_uid = debugUid;
      ws.send(JSON.stringify(payload));
    };

    ws.onmessage = function (event) {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'queue_counts') {
          renderLobbyButtons(msg.counts);
          setWsStatus('Подключено', 'connected');
        } else if (msg.type === 'matched') {
          currentQueue = null;
          showScreen('game-screen');
          const info = $('game-info');
          info.textContent = msg.white_username + ' vs ' + msg.black_username + ' (' + msg.time_control + ')';
          if (gameMeta) {
            gameMeta.textContent = 'Вы играете ' + (msg.color === 'white' ? 'белыми' : 'чёрными');
          }
        }
      } catch (e) {
        console.warn('ws message parse', e);
      }
    };

    ws.onclose = function () {
      ws = null;
      setWsStatus('Нет соединения', 'error');
      if (!reconnectTimer) {
        reconnectTimer = setInterval(function () {
          connect();
          if (ws && ws.readyState === WebSocket.OPEN) {
            clearInterval(reconnectTimer);
            reconnectTimer = null;
          }
        }, 3000);
      }
    };

    ws.onerror = function () {
      setWsStatus('Ошибка соединения', 'error');
    };
  }

  btnCancelQueue.addEventListener('click', leaveCurrentQueue);
  btnBackGame.addEventListener('click', function () {
    showScreen('lobby-screen');
  });

  if (window.Telegram && window.Telegram.WebApp) {
    window.Telegram.WebApp.ready();
    window.Telegram.WebApp.expand();
  }

  renderLobbyButtons({});
  connect();
})();
