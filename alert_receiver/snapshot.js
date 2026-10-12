// A leitura continua manual. O script vence a observação e orienta os retornos locais.
const observation = document.querySelector("[data-expires-in-ms]");

if (observation) {
  const remaining = Number(observation.dataset.expiresInMs);
  const wallDeadline = Number(observation.dataset.expiresAtMs);
  const recordedAt = Number(observation.dataset.observedAtMs);
  const navigation = performance.getEntriesByType?.("navigation")[0];
  // Count navigation, HTML transfer and deferred-script delays against the server's
  // remaining lifetime. Starting at script execution would revive an old result.
  const navigationStart = navigation?.startTime;
  const validClock = Number.isFinite(remaining) && remaining >= 0 &&
    Number.isFinite(wallDeadline) && Number.isFinite(recordedAt) && wallDeadline >= recordedAt &&
    Number.isFinite(navigationStart) && navigationStart >= 0 && navigationStart <= performance.now();
  const monotonicDeadline = validClock ? navigationStart + remaining : 0;

  function expireObservation() {
    if (validClock && performance.now() < monotonicDeadline && Date.now() < wallDeadline) return;
    observation.querySelector("[data-observation-title]").textContent = "Resultado desatualizado";
    observation.querySelector("[data-observation-description]").textContent =
      validClock ? "O resultado do probe venceu. Atualize a leitura." :
      "A validade desta leitura não pôde ser confirmada. Atualize a leitura.";
    observation.querySelector(".status-dot").className = "status-dot warn";
  }

  expireObservation();
  if (validClock) setTimeout(expireObservation, Math.max(0, monotonicDeadline - performance.now()) + 1);
  document.addEventListener("visibilitychange", expireObservation);
  window.addEventListener("pageshow", expireObservation);
}

function revealLocation() {
  if (window.location.hash === "#observacao") {
    const target = document.getElementById("observacao");
    if (!target) return;
    target.open = true;
    target.querySelector("summary").focus();
  } else if (window.location.hash === "#buscar-incidente") {
    document.getElementById("incident-id")?.focus();
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

const invalidLookup = document.querySelector(".incident-lookup [aria-invalid='true']");
if (invalidLookup) invalidLookup.focus();
