/* Offline site search (S-6.2.1). The index is a script (search-index.js
 * sets window.SITE_INDEX) rather than JSON, because browsers refuse to load JSON
 * on pages opened from disk. Every term must appear; title hits rank first. */
(function () {
  var index = window.SITE_INDEX || [];
  var params = new URLSearchParams(window.location.search);
  var query = (params.get("q") || "").trim();
  var input = document.getElementById("q");
  var status = document.getElementById("search-status");
  var list = document.getElementById("search-results");
  if (input) input.value = query;
  if (!query || !list) return;
  var fold = function (s) { return s.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase(); };
  var terms = fold(query).split(/\s+/).filter(Boolean);
  var hits = [];
  index.forEach(function (page) {
    var title = fold(page.t), text = fold(page.x);
    var score = 0;
    for (var i = 0; i < terms.length; i++) {
      var inTitle = title.indexOf(terms[i]) !== -1, inText = text.indexOf(terms[i]) !== -1;
      if (!inTitle && !inText) return;
      score += inTitle ? 10 : 1;
    }
    hits.push({ page: page, score: score });
  });
  hits.sort(function (a, b) { return b.score - a.score || a.page.t.localeCompare(b.page.t); });
  status.textContent = hits.length + (hits.length === 1 ? " page matches " : " pages match ") + "“" + query + "”.";
  hits.forEach(function (hit) {
    var li = document.createElement("li");
    var a = document.createElement("a");
    a.href = hit.page.u;
    a.textContent = hit.page.t;
    var kind = document.createElement("span");
    kind.className = "meta";
    kind.textContent = " " + hit.page.k;
    li.appendChild(a);
    li.appendChild(kind);
    list.appendChild(li);
  });
})();
