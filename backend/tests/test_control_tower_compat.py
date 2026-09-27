from app.main import control_tower_compat_summary


def test_control_tower_compatibility_shape(db):
    payload = control_tower_compat_summary(db)
    assert set(payload) == {"associates", "tasks", "recoveryRequired"}
    assert "WAITING" in payload["associates"]
    assert isinstance(payload["tasks"], dict)
    assert isinstance(payload["recoveryRequired"], list)
