// Голос репетитора (Phase 6.5, ADR-0018): «Слушать», автоозвучка и вопрос голосом.
// Озвучивает и распознаёт сервер (SpeechKit); здесь только кнопки, плеер и запись микрофона.
// Голос не хранится: запись уходит на сервер один раз, назад приходит текст,
// и ученик сам проверяет его и нажимает «Спросить».
(function () {
  var meta = document.querySelector('meta[name="csrf-token"]');
  if (!meta) return;
  var csrf = meta.content;
  var player = new Audio();
  var playingButton = null;
  var AUTOPLAY_KEY = "ege-autoplay";

  function post(url, extra) {
    var body = new FormData();
    body.append("csrf", csrf);
    if (extra) {
      Object.keys(extra).forEach(function (key) {
        var value = extra[key];
        if (value instanceof Blob) body.append(key, value, key + ".pcm");
        else body.append(key, value);
      });
    }
    return fetch(url, { method: "POST", body: body, credentials: "same-origin" }).then(
      function (response) {
        return response.json().then(
          function (data) {
            if (!response.ok || data.error) throw new Error(data.error || "ошибка сервера");
            return data;
          },
          function () {
            throw new Error("страница устарела, обнови её");
          }
        );
      }
    );
  }

  function setState(button, state, message) {
    if (!button) return;
    button.classList.remove("loading", "playing", "failed", "ready");
    if (state) button.classList.add(state);
    button.title = message || "";
  }

  player.addEventListener("ended", function () {
    setState(playingButton, null);
    playingButton = null;
  });

  // Озвучить: сервер готовит звук (или берёт из кэша) и отдаёт ссылку на файл.
  function speak(button, url, auto) {
    if (playingButton === button && !player.paused) {
      player.pause();
      setState(button, null);
      playingButton = null;
      return;
    }
    if (playingButton) setState(playingButton, null);
    playingButton = button;
    setState(button, "loading");
    post(url)
      .then(function (data) {
        player.src = data.url;
        return player.play();
      })
      .then(function () {
        setState(button, "playing");
      })
      .catch(function (error) {
        // браузер может запретить звук без нажатия: тогда кнопка просто подсвечивается
        if (auto && error && error.name === "NotAllowedError") {
          setState(button, "ready", "Нажми, чтобы послушать");
        } else {
          setState(button, "failed", error.message);
          var note = document.getElementById("mic-status");
          if (note && error.message) note.textContent = "Озвучка: " + error.message;
        }
        playingButton = null;
      });
  }

  document.querySelectorAll("button.listen").forEach(function (button) {
    button.addEventListener("click", function () {
      speak(button, button.dataset.speak, false);
    });
  });

  // Автоозвучка: выбор хранится только в этом браузере.
  var toggle = document.getElementById("autoplay");
  var autoplay = false;
  try {
    autoplay = window.localStorage.getItem(AUTOPLAY_KEY) === "1";
  } catch (e) {
    autoplay = false;
  }
  if (toggle) {
    toggle.checked = autoplay;
    toggle.addEventListener("change", function () {
      try {
        window.localStorage.setItem(AUTOPLAY_KEY, toggle.checked ? "1" : "0");
      } catch (e) {
        /* без памяти браузера переключатель работает до перезагрузки */
      }
    });
  }
  var next = document.querySelector("[data-autoplay]");
  if (next && autoplay) {
    var url = next.dataset.autoplay;
    var target = document.querySelector('button.listen[data-speak="' + url + '"]');
    speak(target, url, true);
  }

  // ── вопрос голосом ──
  var mic = document.getElementById("mic");
  var question = document.getElementById("question");
  var status = document.getElementById("mic-status");
  if (!mic || !question) return;
  var RATE = 16000;
  var maxSeconds = parseInt(mic.dataset.max || "30", 10);
  var recorder = null;
  var stopTimer = null;

  function say(text) {
    if (status) status.textContent = text;
  }

  if (!window.MediaRecorder || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    mic.disabled = true;
    say("Этот браузер не умеет записывать голос: напиши вопрос текстом.");
    return;
  }

  // Запись браузера (webm/ogg/mp4) → моно 16 кГц → 16-битный PCM, как ждёт SpeechKit.
  function toPcm(blob) {
    var Context = window.AudioContext || window.webkitAudioContext;
    var context = new Context();
    return blob
      .arrayBuffer()
      .then(function (buffer) {
        return context.decodeAudioData(buffer);
      })
      .then(function (decoded) {
        context.close();
        var length = Math.max(1, Math.ceil(decoded.duration * RATE));
        var offline = new OfflineAudioContext(1, length, RATE);
        var source = offline.createBufferSource();
        source.buffer = decoded;
        source.connect(offline.destination);
        source.start();
        return offline.startRendering();
      })
      .then(function (rendered) {
        var samples = rendered.getChannelData(0);
        var pcm = new DataView(new ArrayBuffer(samples.length * 2));
        for (var i = 0; i < samples.length; i++) {
          var s = Math.max(-1, Math.min(1, samples[i]));
          pcm.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
        }
        return new Blob([pcm.buffer], { type: "application/octet-stream" });
      });
  }

  function stop() {
    if (stopTimer) clearTimeout(stopTimer);
    stopTimer = null;
    if (recorder && recorder.state !== "inactive") recorder.stop();
  }

  function start() {
    navigator.mediaDevices
      .getUserMedia({ audio: true })
      .then(function (stream) {
        var chunks = [];
        recorder = new MediaRecorder(stream);
        recorder.addEventListener("dataavailable", function (e) {
          if (e.data && e.data.size) chunks.push(e.data);
        });
        recorder.addEventListener("stop", function () {
          stream.getTracks().forEach(function (track) {
            track.stop();
          });
          mic.classList.remove("recording");
          mic.textContent = "Сказать голосом";
          mic.disabled = true;
          say("Распознаю…");
          toPcm(new Blob(chunks, { type: recorder.mimeType }))
            .then(function (pcm) {
              return post(mic.dataset.listen, { audio: pcm, rate: String(RATE) });
            })
            .then(function (data) {
              question.value = (question.value ? question.value + " " : "") + data.text;
              question.focus();
              say("Проверь текст и нажми «Спросить».");
            })
            .catch(function (error) {
              say("Не получилось: " + error.message);
            })
            .then(function () {
              mic.disabled = false;
              recorder = null;
            });
        });
        recorder.start();
        mic.classList.add("recording");
        mic.textContent = "Остановить";
        say("Говори. Запись остановится сама через " + maxSeconds + " с.");
        stopTimer = setTimeout(stop, maxSeconds * 1000);
      })
      .catch(function () {
        say("Нет доступа к микрофону: разреши его в настройках браузера.");
      });
  }

  mic.addEventListener("click", function () {
    if (recorder && recorder.state === "recording") stop();
    else if (!recorder) start();
  });
})();
