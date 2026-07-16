// Full Planet — channel renderer
// Reads ?c=<key> from the URL, loads the daily digest, and paints the feed.

(function () {
  const params = new URLSearchParams(window.location.search);
  const key = params.get("c") || "ai";

  const heroEl = document.getElementById("channel-hero");
  const metaEl = document.getElementById("channel-meta");
  const feedEl = document.getElementById("feed");

  function fmtDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return "";
    return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
  }

  function esc(s) {
    return (s || "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }

  fetch("data/digest.json", { cache: "no-store" })
    .then((r) => {
      if (!r.ok) throw new Error("digest not found");
      return r.json();
    })
    .then((digest) => {
      const channel = (digest.channels || []).find((c) => c.key === key);
      if (!channel) {
        feedEl.innerHTML =
          '<p class="empty"><strong>Channel not found.</strong>Try returning to the home page.</p>';
        return;
      }

      // theme
      const accent = channel.accent || "#5AA9E6";
      document.documentElement.style.setProperty("--accent", accent);
      document.title = "Full Planet — " + channel.name;

      // hero
      heroEl.innerHTML =
        '<p class="eyebrow">Channel</p>' +
        "<h1>" + esc(channel.name) + "</h1>" +
        "<p>" + esc(channel.tagline) + "</p>";

      // meta line
      const count = channel.items.length;
      metaEl.textContent =
        (count ? count + " recent " + (count === 1 ? "story" : "stories") : "No recent stories") +
        (digest.generated_human ? " · updated " + digest.generated_human : "");

      // feed
      if (!count) {
        feedEl.innerHTML =
          '<p class="empty"><strong>Nothing new just yet.</strong>The next daily update will fill this channel with fresh headlines.</p>';
        return;
      }

      feedEl.innerHTML = channel.items
        .map((it) => {
          const date = fmtDate(it.published);
          return (
            '<a class="entry" href="' + esc(it.link) + '" target="_blank" rel="noopener">' +
            (date ? '<div class="entry-top"><span class="date">' + date + "</span></div>" : "") +
            "<h2>" + esc(it.title) + '<span class="arrow">→</span></h2>' +
            (it.summary ? '<p class="summary">' + esc(it.summary) + "</p>" : "") +
            '<p class="src-line">Source: <span class="src-name">' + esc(it.source) + "</span></p>" +
            "</a>"
          );
        })
        .join("");
    })
    .catch(() => {
      feedEl.innerHTML =
        '<p class="empty"><strong>Couldn&rsquo;t load the digest.</strong>If you just published the site, wait for the first daily build to run.</p>';
    });
})();
