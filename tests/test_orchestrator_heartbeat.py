import threading

from blackbox.core import Store
from blackbox.orchestrator import Orchestrator


def test_invoke_renews_lease_while_observability_agent_runs():
    store = Store()
    incident_id = 'BBX-HEARTBEAT'
    store.create_incident(incident_id, 'heartbeat', 'test incident', 'ops')
    evidence_id = store.add_evidence(
        incident_id, 'log', 'deployment produced 5xx latency measurements', {'source': 'test'}
    )
    evidence = [dict(store.db.execute(
        'SELECT * FROM evidence WHERE evidence_id=?', (evidence_id,)
    ).fetchone())]

    orchestrator = Orchestrator(store, heartbeat_interval_seconds=0.05)
    worker = orchestrator.worker
    original_heartbeat = worker.heartbeat
    original_run = orchestrator.agents['observability'].run
    run_started = threading.Event()
    two_renewals = threading.Event()
    lock = threading.Lock()
    background_renewals = 0

    def heartbeat(task_id, fence_token):
        nonlocal background_renewals
        result = original_heartbeat(task_id, fence_token)
        if run_started.is_set():
            with lock:
                background_renewals += 1
                if background_renewals >= 2:
                    two_renewals.set()
        return result

    def blocked_run(incident, task, agent_evidence, revision):
        run_started.set()
        if not two_renewals.wait(timeout=5):
            raise AssertionError('background heartbeat renewals did not complete')
        return original_run(incident, task, agent_evidence, revision)

    worker.heartbeat = heartbeat
    orchestrator.agents['observability'].run = blocked_run
    try:
        message = orchestrator.invoke(
            incident_id, 'observability', 'analyze_logs', evidence, revision=0
        )
    finally:
        worker.heartbeat = original_heartbeat
        orchestrator.agents['observability'].run = original_run

    with lock:
        renewals = background_renewals
    assert renewals >= 2
    assert message['agent'] == 'observability'

    task = store.db.execute(
        "SELECT status, output FROM tasks WHERE incident_id=? AND agent=? AND task=?",
        (incident_id, 'observability', 'analyze_logs'),
    ).fetchone()
    assert task['status'] == 'completed'

    persisted = orchestrator.messages.get(message['message_id'], message['revision'])
    assert orchestrator.messages.verify(persisted)
