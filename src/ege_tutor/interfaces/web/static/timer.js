// Таймер попытки: показывает, сколько прошло с начала. Время считает сервер,
// здесь только отображение.
(function () {
  var el = document.getElementById("timer");
  if (!el) return;
  var started = Date.parse(el.dataset.started);
  var norm = parseInt(el.dataset.norm || "0", 10);
  function tick() {
    var s = Math.max(0, Math.floor((Date.now() - started) / 1000));
    var m = Math.floor(s / 60);
    var r = s % 60;
    el.textContent = m + ":" + (r < 10 ? "0" : "") + r;
    el.className = norm && s > norm ? "over" : "";
  }
  tick();
  setInterval(tick, 1000);
})();
