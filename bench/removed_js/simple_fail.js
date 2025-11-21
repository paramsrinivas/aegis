import http from "k6/http";
import { sleep } from "k6";
export default function () {
  http.get(__ENV.URL || "http://localhost:8102/fail");
  sleep(0.1);
}
