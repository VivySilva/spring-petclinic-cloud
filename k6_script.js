import http from 'k6/http';

// Configurações passadas por variáveis de ambiente pelo run_experiment.sh
const API_URL = __ENV.API_URL || 'http://localhost:80';
const RPS = parseInt(__ENV.RPS || '10');
const DURATION = __ENV.DURATION || '5m';

export const options = {
  scenarios: {
    constant_request_rate: {
      executor: 'constant-arrival-rate',
      rate: RPS,
      timeUnit: '1s',
      duration: DURATION,
      preAllocatedVUs: Math.max(10, Math.floor(RPS / 2)), // VUs virtuais pré-alocadas
      maxVUs: Math.max(100, RPS * 10), // VUs máximas: suporta picos de latência (RPS × timeout_max)
    },
  },
  discardResponseBodies: true, // Mais eficiente: não consome memória salvando os HTMLs/JSONs das respostas
};

const ENDPOINTS = [
  '/api/customer/owners',
  '/api/customer/owners/1',
  '/api/vet/vets',
  '/api/visit/owners/1/pets/1/visits',
];

export default function () {
  // Sorteia um endpoint para acessar
  const idx = Math.floor(Math.random() * ENDPOINTS.length);
  const url = `${API_URL}${ENDPOINTS[idx]}`;

  http.get(url, {
    timeout: '5s', // Timeout de 5 segundos para a requisição
  });
}
