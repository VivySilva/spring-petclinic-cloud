import http from 'k6/http';

export const options = {
  vus: 1,
  duration: '2s',
};

export default function () {
  const res = http.get('http://localhost:80/api/customer/owners');
  console.log(`Status: ${res.status}, Error code: ${res.error_code}, Error: ${res.error}`);
}
