import http from 'k6/http';
import { sleep } from 'k6';

export let options = {
  vus: 20,
  duration: '3m',
  rps: 200,
};

export default function () {
  http.get('http://localhost:8000/predict');
  sleep(0.01);
}
