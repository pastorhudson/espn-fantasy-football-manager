from unittest.mock import patch

import pytest
from django.db import DatabaseError
from django.urls import reverse


@pytest.mark.django_db
def test_health(client):
    response = client.get(reverse("health"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "espn_writes_enabled": False}


@pytest.mark.django_db
def test_health_hides_database_error(client):
    with patch(
        "config.health.connection.cursor", side_effect=DatabaseError("private-database-info")
    ):
        response = client.get(reverse("health"))
    assert response.status_code == 503
    assert "private" not in response.content.decode()
