// Contador de downloads (Supabase) + destaque do sistema do visitante.
// Se o Supabase falhar, o site continua funcionando igual.
const SUPABASE_URL = "https://fibouroriwtsdedvcvnr.supabase.co";
const SUPABASE_KEY = "sb_publishable_DNNOxPtt7AYQXz6Y8-qBeQ_AbyHTMdc";

const cabecalhos = {
  apikey: SUPABASE_KEY,
  Authorization: "Bearer " + SUPABASE_KEY,
  "Content-Type": "application/json",
};

/* ------------------------------------------------------------------ */
/* Contador                                                            */
/* ------------------------------------------------------------------ */
function mostrarContador(total) {
  const caixa = document.getElementById("contador");
  const num = document.getElementById("contador-num");
  const rotulo = document.getElementById("contador-rotulo");
  if (!caixa || !num || !rotulo) return;
  const n = Number(total);
  if (!Number.isFinite(n) || n <= 0) return;
  num.textContent = n.toLocaleString("pt-BR");
  rotulo.textContent = n === 1 ? "download registrado" : "downloads registrados";
  caixa.hidden = false;
}

async function contar() {
  try {
    const r = await fetch(`${SUPABASE_URL}/rest/v1/rpc/contar_downloads`, {
      method: "POST",
      headers: cabecalhos,
      body: "{}",
    });
    if (r.ok) mostrarContador(await r.json());
  } catch (_) {
    /* offline ou bloqueado: sem contador */
  }
}

async function registrar(app, plataforma) {
  try {
    const r = await fetch(`${SUPABASE_URL}/rest/v1/rpc/registrar_download`, {
      method: "POST",
      headers: cabecalhos,
      body: JSON.stringify({ p_app: app, p_plataforma: plataforma }),
      keepalive: true,
    });
    if (r.ok) mostrarContador(await r.json());
  } catch (_) {
    /* o download segue normalmente */
  }
}

document.querySelectorAll("a[data-app]").forEach((link) => {
  link.addEventListener("click", () => {
    registrar(link.dataset.app, link.dataset.plataforma || "fonte");
  });
});

/* ------------------------------------------------------------------ */
/* Sistema do visitante                                                */
/* ------------------------------------------------------------------ */
function sistemaDoVisitante() {
  const ua = navigator.userAgent;
  const plataforma = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "";
  if (/Win/i.test(plataforma) || /Windows/i.test(ua)) return "windows";
  if (/Linux|X11/i.test(plataforma) || /Linux/i.test(ua)) return "linux";
  if (/Mac/i.test(plataforma) || /Mac OS X/i.test(ua)) return "macos";
  return "";
}

function destacarSistema() {
  const sistema = sistemaDoVisitante();
  if (!sistema) return;

  document.querySelectorAll("a[data-app]").forEach((link) => {
    const alvo = link.dataset.plataforma === sistema;
    link.classList.toggle("primario", alvo);
    link.classList.toggle("fantasma", !alvo && link.dataset.plataforma === "fonte");
    if (alvo) link.setAttribute("aria-current", "true");
  });

  const nota = document.getElementById("aviso-sistema");
  if (nota && sistema === "macos") {
    nota.hidden = false;
    nota.textContent = "macOS: ainda não tem instalador pronto — use o código e rode com Python + GTK4, ou o Linux via Homebrew.";
  }
}

destacarSistema();
contar();
