"""A Knos worker: take paid jobs, do them with your own agent, get paid when the buyer accepts."""
from knos.jobs.api import serve


def my_agent(prompt: str) -> str:
    return "..."  # call any agent or model here, on your own key


serve(my_agent)
