// Só vence o resultado exibido; os dados continuam com atualização manual.
const observation = document.querySelector("[data-expires-in-ms]");

if (observation) {
  const remaining = Number(observation.dataset.expiresInMs);
  const monotonicDeadline = performance.now() + remaining;
  const wallDeadline = Date.now() + remaining;

  function expireObservation() {
    // Os dois relógios cobrem suspensão do dispositivo e ajuste do horário.
    if (performance.now() < monotonicDeadline && Date.now() < wallDeadline) return;
    observation.querySelector("[data-observation-title]").textContent = "Leitura desatualizada";
    observation.querySelector("[data-observation-description]").textContent =
      "Resultado vencido. Atualize a página.";
    observation.querySelector(".status-dot").className = "status-dot warn";
  }

  if (Number.isFinite(remaining) && remaining >= 0) {
    setTimeout(expireObservation, remaining + 1);
    document.addEventListener("visibilitychange", expireObservation);
    window.addEventListener("pageshow", expireObservation);
  }
}
