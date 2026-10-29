/*
 * Свайп влево/вправо — соседняя вкладка (порядок — как в меню вкладок, nav.tabs).
 * Не мешаем: прокрутке по вертикали, полям ввода, жесту «назад» у края экрана в iOS.
 */
(function () {
  var tabs = Array.prototype.slice.call(document.querySelectorAll("nav.tabs a"));
  var current = tabs.findIndex(function (a) { return a.classList.contains("on"); });
  var main = document.querySelector("main");
  if (tabs.length < 2 || current < 0 || !main) return;

  var EDGE = 24;      // px от края экрана — там жест браузера «назад»
  var MIN = 70;       // px по горизонтали, чтобы считать свайпом
  var start = null;

  // слушаем весь экран (на короткой странице под main пусто), кроме шапки и меню вкладок — оно само листается
  document.addEventListener("touchstart", function (e) {
    var t = e.touches[0];
    var busy = e.touches.length > 1 || e.target.closest("input, textarea, select, button, form, header, nav");
    start = busy || t.clientX < EDGE || t.clientX > window.innerWidth - EDGE ? null : {x: t.clientX, y: t.clientY};
  }, {passive: true});

  document.addEventListener("touchend", function (e) {
    if (!start) return;
    var t = e.changedTouches[0];
    var dx = t.clientX - start.x, dy = t.clientY - start.y;
    start = null;
    if (Math.abs(dx) < MIN || Math.abs(dx) < Math.abs(dy) * 2) return;  // в основном вертикально — это прокрутка
    var next = tabs[current + (dx < 0 ? 1 : -1)];
    if (!next) return;
    main.classList.add(dx < 0 ? "leave-left" : "leave-right");
    window.location.href = next.href;
  }, {passive: true});

  // вернулись кнопкой «назад» — страница из кэша браузера не должна остаться сдвинутой
  window.addEventListener("pageshow", function () { main.classList.remove("leave-left", "leave-right"); });
})();
