// A leitura continua manual. Este script só vence a observação e abre seus detalhes.
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

function revealObservation() {
  if (window.location.hash === "#observacao") {
    document.getElementById("observacao").open = true;
  }
}
window.addEventListener("hashchange", revealObservation);
revealObservation();
