from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from grant_app.constants import Decision
from grant_app.extensions import db
from grant_app.models import Application


@pytest.fixture(autouse=True)
def history_records(app):
    names = [
        "Student 00",
        "Student 01",
        "Student 02",
        "Student 03",
        "Maria Student",
        "Omar Student",
        "MARlow Student",
        "Student 07",
        "Student 08",
        "Student 09",
        "Student 10",
        "Student 11",
        "Student 12",
        "Student 13",
        "Student 14",
        "Student 15",
        "Student 16",
        "Student 17",
        "Student 18",
        "Student 19",
        "Student 20",
        "Older Student",
        "Newest Student",
    ]
    first_submission = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)

    with app.app_context():
        db.session.add_all(
            [
                Application(
                    name=name,
                    annual_income_cad=Decimal("42000.00") + index,
                    address=f"{index + 1} Test Street",
                    age=24,
                    education_level="BACHELORS_DEGREE",
                    marital_status="SINGLE",
                    dependents=0,
                    province="BC",
                    approval_probability=Decimal("0.75"),
                    decision=(
                        Decision.APPROVED.value
                        if index % 2 == 0
                        else Decision.NOT_APPROVED.value
                    ),
                    approval_engine="test-v1",
                    submitted_at=first_submission + timedelta(hours=index),
                )
                for index, name in enumerate(names)
            ]
        )
        db.session.commit()


def test_history_defaults_to_twenty_newest_applications(client):
    response = client.get("/applications")

    assert response.status_code == 200
    assert response.data.count(b'class="history-row"') == 20
    assert response.data.index(b"Newest Student") < response.data.index(
        b"Older Student"
    )
    for column in (
        b"Application ID",
        b"Name",
        b"Age",
        b"Province / Territory",
        b"Annual income",
        b"Submitted",
        b"Decision",
        b"Approval probability",
        b"Details",
    ):
        assert column in response.data
    assert b"Edit application" not in response.data
    assert b"Delete application" not in response.data


def test_history_searches_names_by_case_insensitive_partial_match(client):
    response = client.get("/applications?q=mar")

    assert response.status_code == 200
    assert response.data.count(b'class="history-row"') == 3
    assert b"Maria Student" in response.data
    assert b"Omar Student" in response.data
    assert b"MARlow Student" in response.data
    assert b"Newest Student" not in response.data


def test_history_filters_by_decision(client):
    response = client.get("/applications?decision=APPROVED")

    assert response.status_code == 200
    assert response.data.count(b'class="history-row"') == 12
    assert response.data.count(b"<td>Approved</td>") == 12
    assert b"<td>Not Approved</td>" not in response.data


def test_history_page_two_contains_only_the_three_oldest_applications(client):
    response = client.get("/applications?page=2")

    assert response.status_code == 200
    assert response.data.count(b'class="history-row"') == 3
    assert b"Student 00" in response.data
    assert b"Student 01" in response.data
    assert b"Student 02" in response.data
    assert b"Newest Student" not in response.data
    assert b">Previous<" in response.data
    assert b">Next<" not in response.data


def test_history_combines_name_and_decision_filters(client):
    response = client.get("/applications?q=MAR&decision=APPROVED")

    assert response.status_code == 200
    assert response.data.count(b'class="history-row"') == 2
    assert b"Maria Student" in response.data
    assert b"MARlow Student" in response.data
    assert b"Omar Student" not in response.data


def test_history_pagination_link_preserves_filter_query_state(client):
    response = client.get("/applications?q=student")

    assert response.status_code == 200
    assert b'href="/applications?q=student&amp;decision=&amp;page=2"' in response.data
    assert b">Next<" in response.data


@pytest.mark.parametrize(
    "query_string",
    [
        "page=abc",
        "page=-2",
        "page=99",
        f"page={'9' * 100}",
        "decision=PENDING",
    ],
)
def test_history_invalid_query_values_safely_default_to_page_one_and_all(
    client, query_string
):
    response = client.get(f"/applications?{query_string}")

    assert response.status_code == 200
    assert response.data.count(b'class="history-row"') == 20
    assert b"Newest Student" in response.data
    assert b"Student 00" not in response.data
    assert b'<option value="" selected>All</option>' in response.data
