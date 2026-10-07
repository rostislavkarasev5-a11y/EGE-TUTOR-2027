// Поле для программы: клавиша Tab вставляет 4 пробела, а не уходит на следующую кнопку.
(function () {
  var areas = document.querySelectorAll("textarea.code");
  areas.forEach(function (area) {
    area.addEventListener("keydown", function (e) {
      if (e.key !== "Tab" || e.shiftKey || e.ctrlKey || e.altKey || e.metaKey) return;
      e.preventDefault();
      var start = area.selectionStart;
      var end = area.selectionEnd;
      area.value = area.value.slice(0, start) + "    " + area.value.slice(end);
      area.selectionStart = area.selectionEnd = start + 4;
    });
  });
})();
