// Service worker do DentaAgenda — versão mínima e segura.
//
// Importante: como é um app multi-clínica com dados sensíveis (pacientes,
// financeiro), este service worker NUNCA guarda em cache páginas
// autenticadas nem respostas de API. Ele só cuida de:
//   1) deixar o app "instalável" (requisito pro Chrome/Android oferecer
//      "Adicionar à tela inicial")
//   2) mostrar uma tela amigável de "sem internet" quando cair a conexão,
//      em vez do erro feio padrão do navegador
//
// Sempre que precisar mudar esse arquivo, troca o número da versão abaixo
// pra forçar os celulares a baixarem a versão nova.
const CACHE_VERSION = 'dentaagenda-v1';
const ASSETS_ESTATICOS = [
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/offline.html'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) => cache.addAll(ASSETS_ESTATICOS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((nomes) =>
      Promise.all(
        nomes.filter((n) => n !== CACHE_VERSION).map((n) => caches.delete(n))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const req = event.request;

  // só entra na lógica de cache pra navegação de página (não pra POST,
  // não pra chamadas de API/dados dinâmicos)
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // arquivos estáticos: cache-first (rápido e não muda com frequência)
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(req).then((cached) => cached || fetch(req))
    );
    return;
  }

  // navegação de página (abrir uma tela do app): sempre busca da rede
  // pra garantir dado atualizado; só usa a tela offline se a rede falhar
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req).catch(() => caches.match('/static/offline.html'))
    );
  }
  // qualquer outra coisa (API, POST, etc.) passa direto, sem cache
});
