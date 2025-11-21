# locustfile.py
from locust import HttpUser, task, between

class RouterUser(HttpUser):
    wait_time = between(0.01, 0.1)

    @task(1)
    def predict(self):
        self.client.get("/predict", timeout=10)

