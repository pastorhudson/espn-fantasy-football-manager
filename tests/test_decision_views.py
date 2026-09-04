import pytest
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

from decisions.models import Decision
from leagues.models import FantasyTeam, League


@pytest.fixture
def decision(db):
    league = League.objects.create(espn_id=1, season=2026, name="Test league")
    team = FantasyTeam.objects.create(league=league, espn_id=1, name="Test team")
    return Decision.objects.create(
        team=team, kind="shadow_lineup", rationale="Review in ESPN.",
        recommendation={
            "status": "review", "projected_total": 12.5, "current_projected_total": 0,
            "improvement": 12.5, "warnings": ["Check injury status."],
            "assignments": [{"name": "<script>alert(1)</script>", "slot_id": 23,
                             "projected_points": 12.5}],
            "changes": [{"name": "Player", "from_slot": 20, "to_slot": 23}],
        },
    )


@pytest.mark.django_db
def test_access_and_readable_details(client, django_user_model, decision):
    detail_url = reverse("decision-detail", args=[decision.pk])
    for url in [reverse("decision-list"), detail_url]:
        assert client.get(url).status_code == 302
    user = django_user_model.objects.create_user(username="viewer", password="test-password")
    client.force_login(user)
    assert client.get(detail_url).status_code == 403
    assert client.get(reverse("decision-list")).status_code == 403
    user.user_permissions.add(Permission.objects.get(codename="view_decision"))
    response = client.get(detail_url)
    assert response.status_code == 200
    content = response.content.decode()
    for expected in ["12.50", "0.00", "Bench → Flex", "Check injury status.", "&lt;script&gt;"]:
        assert expected in content
    assert "<script>" not in content
    assert client.get(reverse("decision-list")).status_code == 200
    assert client.get(reverse("decision-detail", args=[999999])).status_code == 404


@pytest.mark.django_db
def test_login_logout_and_safe_redirect(client, django_user_model):
    django_user_model.objects.create_superuser("manager", password="test-password")
    assert client.get(reverse("login")).status_code == 200
    assert "didn’t match" in client.post(reverse("login"), {
        "username": "manager", "password": "wrong",
    }).content.decode()
    response = client.post(reverse("login"), {
        "username": "manager", "password": "test-password", "next": "https://evil.example/",
    })
    assert response.url == reverse("decision-list")
    assert client.get(reverse("logout")).status_code == 405
    assert client.post(reverse("logout")).url == reverse("login")
    assert client.get(reverse("decision-list")).status_code == 302
    assert Client(enforce_csrf_checks=True).post(reverse("login"), {}).status_code == 403


@pytest.mark.django_db
def test_empty_blocked_and_pagination(client, admin_user, decision):
    client.force_login(admin_user)
    decision.recommendation = {"status": "blocked", "warnings": ["Missing projection."]}
    decision.save()
    response = client.get(reverse("decision-detail", args=[decision.pk]))
    assert "Missing projection." in response.content.decode()
    assert "No lineup changes recommended" not in response.content.decode()
    Decision.objects.bulk_create([
        Decision(team=decision.team, kind="shadow_lineup", recommendation={}) for _ in range(20)
    ])
    assert len(client.get(reverse("decision-list")).context["decisions"]) == 20
    assert len(client.get(reverse("decision-list") + "?page=2").context["decisions"]) == 1
    Decision.objects.all().delete()
    assert "No decisions yet" in client.get(reverse("decision-list")).content.decode()
