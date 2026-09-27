"""Executable API demonstration using FastAPI's in-process TestClient."""
from fastapi.testclient import TestClient
from backend.app.main import app


def main() -> None:
    with TestClient(app) as c:
        login = c.post('/auth/login', json={
            'username': 'picker1', 'password': 'demo1234',
            'device_id': 'PDA-DEMO-001', 'app_version': '0.1.0',
        }).json()
        h = {'Authorization': 'Bearer ' + login['access_token']}

        products = c.get('/inventory/product/DEMO-AMBIENT-001').json()
        product_id = products['product']['id']
        print('inventory:', products['total_on_hand'], products['product']['title'])

        unpack = c.post('/unpack/sessions', headers=h, json={'temperature_class': 'AMBIENT'}).json()
        c.post(f"/unpack/sessions/{unpack['session_id']}/scan", headers=h, json={
            'event_id': 'demo-unpack-1', 'product_id': product_id, 'qty': 2,
        }).raise_for_status()
        unpack_done = c.post(f"/unpack/sessions/{unpack['session_id']}/complete", headers=h).json()
        destination = next(x for x in unpack_done['items'][0]['compatible_destinations'] if x.startswith('P-1-A'))
        c.post('/boh/move', headers=h, json={
            'event_id': 'demo-boh-1', 'product_id': product_id, 'qty': 2,
            'source_location_id': 'TSCRET001', 'destination_location_id': destination,
        }).raise_for_status()
        print('unpack -> BOH:', destination)

        order = c.post('/orders', headers=h, json={
            'external_ref': 'demo-order-001', 'lines': [{'product_id': product_id, 'qty': 2}],
        }).json()
        task = c.post(f"/orders/{order['order_id']}/allocate", headers=h).json()
        c.post(f"/tasks/{task['task_id']}/offer", headers=h, json={
            'user_id': login['user_id'], 'device_id': login['device_id'],
        }).raise_for_status()
        task = c.post(f"/tasks/{task['task_id']}/accept", headers=h).json()
        item = task['items'][0]
        result = c.post(f"/tasks/{task['task_id']}/scan", headers=h, json={
            'event_id': 'demo-pick-1', 'client_seq': 1, 'task_item_id': item['id'],
            'location_id': item['source_location_id'], 'product_id': item['product_id'], 'qty': 1,
        }).json()
        print('pick confirmed:', result['snapshot']['picked_units'], '/', result['snapshot']['expected_units'])

        duplicate = c.post(f"/tasks/{task['task_id']}/scan", headers=h, json={
            'event_id': 'demo-pick-1', 'client_seq': 1, 'task_item_id': item['id'],
            'location_id': item['source_location_id'], 'product_id': item['product_id'], 'qty': 1,
        }).json()
        print('duplicate retry applied twice?', not duplicate['duplicate'])

        recovery = c.post(f"/orders/{order['order_id']}/cancel", headers=h, json={'reason': 'DEMO_CANCEL'}).json()
        print('cancel state:', recovery['task_status'], 'recovery_required=', recovery['recovery_required'])


if __name__ == '__main__':
    main()
