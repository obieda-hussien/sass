import importlib
import os
from pathlib import Path


def test_end_to_end_api_smoke(tmp_path, monkeypatch):
    # main/database are already imported by unit tests, so this smoke test exercises services
    # through FastAPI against the test process' configured database rather than replacing globals.
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import Base, engine

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    from app.database import SessionLocal
    from app.seed import seed_demo
    seed_db = SessionLocal()
    with seed_db.begin():
        seed_demo(seed_db)
    seed_db.close()

    with TestClient(app) as c:
        login = c.post('/auth/login', json={
            'username': 'picker1', 'password': 'demo1234',
            'device_id': 'PDA-DEMO-001', 'app_version': '0.1.0',
        })
        assert login.status_code == 200
        auth = login.json()
        headers = {'Authorization': f"Bearer {auth['access_token']}"}

        inv = c.get('/inventory/product/DEMO-AMBIENT-001')
        assert inv.status_code == 200
        product_id = inv.json()['product']['id']

        order = c.post('/orders', headers=headers, json={
            'external_ref': 'api-smoke',
            'lines': [{'product_id': product_id, 'qty': 2}],
        })
        assert order.status_code == 200
        order_id = order.json()['order_id']

        alloc = c.post(f'/orders/{order_id}/allocate', headers=headers)
        assert alloc.status_code == 200
        task_id = alloc.json()['task_id']

        offer = c.post(f'/tasks/{task_id}/offer', headers=headers, json={
            'user_id': auth['user_id'], 'device_id': auth['device_id'],
        })
        assert offer.status_code == 200
        accept = c.post(f'/tasks/{task_id}/accept', headers=headers)
        assert accept.status_code == 200
        item = accept.json()['items'][0]

        payload = {
            'event_id': 'api-scan-1', 'client_seq': 1,
            'task_item_id': item['id'], 'location_id': item['source_location_id'],
            'product_id': item['product_id'], 'qty': 1,
        }
        first = c.post(f'/tasks/{task_id}/scan', headers=headers, json=payload)
        assert first.status_code == 200
        assert first.json()['snapshot']['picked_units'] == 1
        duplicate = c.post(f'/tasks/{task_id}/scan', headers=headers, json=payload)
        assert duplicate.status_code == 200
        assert duplicate.json()['duplicate'] is True
        assert duplicate.json()['snapshot']['picked_units'] == 1

        cancelled = c.post(f'/orders/{order_id}/cancel', headers=headers, json={'reason': 'TEST'})
        assert cancelled.status_code == 200
        assert cancelled.json()['task_status'] == 'RECOVERY_REQUIRED'
