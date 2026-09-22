// A leitura continua manual. O script vence a observação e orienta os retornos locais.
const observation = document.querySelector("[data-expires-in-ms]");

if (observation) {
  const remaining = Number(observation.dataset.expiresInMs);
  const monotonicDeadline = performance.now() + remaining;
  const wallDeadline = Date.now() + remaining;

  function expireObservation() {
    if (performance.now() < monotonicDeadline && Date.now() < wallDeadline) return;
    observation.querySelector("[data-observation-title]").textContent = "Resultado desatualizado";
    observation.querySelector("[data-observation-description]").textContent =
      "O resultado do probe venceu. Atualize a leitura.";
    observation.querySelector(".status-dot").className = "status-dot warn";
  }

  if (Number.isFinite(remaining) && remaining >= 0) {
    setTimeout(expireObservation, remaining + 1);
    document.addEventListener("visibilitychange", expireObservation);
    window.addEventListener("pageshow", expireObservation);
  }
}

function revealLocation() {
  if (window.location.hash === "#observacao") {
    const target = document.getElementById("observacao");
    target.open = true;
    target.querySelector("summary").focus();
  } else if (/^#incidente-\d+$/.test(window.location.hash)) {
    // The incident may have changed state or expired since the detail was opened.
    const target = document.getElementById(window.location.hash.slice(1)) || document.getElementById("conteudo");
    target.focus();
  }
}
window.addEventListener("hashchange", revealLocation);
// A new document applies its native fragment after deferred scripts have run.
window.addEventListener("pageshow", revealLocation);
revealLocation();
