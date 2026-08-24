import time


DEFAULT_JOBS = [
    {"name": "patrol", "every_minutes": 60},
    {"name": "knowledge-refresh", "every_minutes": 60},
    {"name": "network-check", "every_minutes": 15},
    {"name": "metrics-snapshot", "every_minutes": 1440},
    {"name": "venus-drain", "every_minutes": 30},
]


def _jobs(state):
    jobs = state.load().get("scheduler_jobs")
    if jobs is None:
        jobs = [dict(j) for j in DEFAULT_JOBS]
        state.save(scheduler_jobs=jobs)
    return jobs


def _save_jobs(state, jobs):
    state.save(scheduler_jobs=jobs)


def list_jobs(state):
    return _jobs(state)


def add_job(state, name, every_minutes):
    jobs = [j for j in _jobs(state) if j["name"] != name]
    jobs.append({"name": name, "every_minutes": int(every_minutes),
                 "last_run": None})
    _save_jobs(state, jobs)
    return jobs


def remove_job(state, name):
    jobs = [j for j in _jobs(state) if j["name"] != name]
    _save_jobs(state, jobs)
    return jobs


def due_jobs(state, now=None):
    now = now or time.time()
    due = []
    for job in _jobs(state):
        last = job.get("last_run")
        if last is None or now - last >= job["every_minutes"] * 60:
            due.append(job["name"])
    return due


def mark_run(state, name, now=None):
    jobs = _jobs(state)
    for job in jobs:
        if job["name"] == name:
            job["last_run"] = now or time.time()
    _save_jobs(state, jobs)


def tick(state):
    """Returns names of jobs whose interval has elapsed."""
    due = due_jobs(state)
    for name in due:
        mark_run(state, name)
    return due
