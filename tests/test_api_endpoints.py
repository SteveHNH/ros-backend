import datetime
from dateutil import parser
import json
from base64 import b64encode

import pytest

from ros.api.main import app
from ros.lib.models import db, PerformanceProfile, System
from tests.helpers.db_helper import db_get_host, db_get_record


@pytest.fixture(scope="session")
def auth_token():
    identity = {
        "identity": {
            "account_number": "12345",
            "type": "User",
            "user": {
                "username": "tuser@redhat.com",
                "email": "tuser@redhat.com",
                "first_name": "test",
                "last_name": "user",
                "is_active": True,
                "is_org_admin": False,
                "is_internal": True,
                "locale": "en_US"
            },
            "org_id": "000001",
            "internal": {
                "org_id": "000001"
            }
        }
    }
    auth_token = b64encode(json.dumps(identity).encode('utf-8'))
    return auth_token


def assert_report_date_with_current_date(report_date):
    date_format = "%m/%d/%Y"
    report_date = parser.parse(report_date).strftime(date_format)
    utcnow_date = str(datetime.datetime.utcnow().strftime(date_format))
    assert report_date == utcnow_date


def test_status():
    with app.test_client() as client:
        response = client.get('/api/ros/v1/status')
        assert response.status_code == 200
        assert response.json["status"] == "Application is running!"


def test_is_configured(auth_token, db_setup, db_create_account, db_create_system, db_create_performance_profile):
    with app.test_client() as client:
        response = client.get('/api/ros/v1/is_configured', headers={"x-rh-identity": auth_token})
        sys_response = client.get('/api/ros/v1/systems', headers={"x-rh-identity": auth_token})
        assert response.status_code == 200
        assert response.json["count"] == 1
        assert response.json["systems_stats"]["with_suggestions"] == 1
        assert response.json["systems_stats"]["waiting_for_data"] == 0
        assert response.json["count"] == sys_response.json["meta"]["count"]


def test_systems(auth_token, db_setup, db_create_account, db_create_system, db_create_performance_profile):
    with app.test_client() as client:
        response = client.get('/api/ros/v1/systems', headers={"x-rh-identity": auth_token})
        assert response.status_code == 200
        assert response.json["meta"]["count"] == 1
        assert response.json["data"][0]["os"] == "RHEL 8.4"
        assert response.json["data"][0]["groups"] == []


def test_system_detail(auth_token, db_setup, db_create_account, db_create_system, db_create_performance_profile):
    with app.test_client() as client:
        response = client.get(
            '/api/ros/v1/systems/ee0b9978-fe1b-4191-8408-cbadbd47f7a3',  # inventory_id from db_create_system
            headers={"x-rh-identity": auth_token}
        )
        assert response.status_code == 200
        assert response.json["inventory_id"] == 'ee0b9978-fe1b-4191-8408-cbadbd47f7a3'
        assert response.json["os"] == "RHEL 8.4"  # from db fixture
        assert_report_date_with_current_date(response.json["report_date"])


def test_system_history(auth_token, db_setup, db_create_account,
                        db_create_system, db_create_performance_profile_history):
    with app.test_client() as client:
        response = client.get(
            '/api/ros/v1/systems/ee0b9978-fe1b-4191-8408-cbadbd47f7a3/history',
            headers={"x-rh-identity": auth_token}
        )
        assert response.status_code == 200
        assert response.json["meta"]["count"] == 1
        assert_report_date_with_current_date(
            response.json["data"][0]["report_date"]
        )
        assert response.json["inventory_id"] == 'ee0b9978-fe1b-4191-8408-cbadbd47f7a3'


def test_system_no_os(auth_token, db_setup, db_create_account, db_create_system, db_create_performance_profile):

    # Setting db_record.operating_system to None/null
    system_record = db_get_host('ee0b9978-fe1b-4191-8408-cbadbd47f7a3')
    system_record.operating_system = None
    db.session.commit()

    with app.test_client() as client:
        response_individual_system = client.get(
            '/api/ros/v1/systems/ee0b9978-fe1b-4191-8408-cbadbd47f7a3',
            headers={"x-rh-identity": auth_token}
        )

        assert response_individual_system.status_code == 200
        assert response_individual_system.json["os"] is None

        response_all_systems = client.get(
            '/api/ros/v1/systems',
            headers={"x-rh-identity": auth_token}
        )

        assert response_all_systems.status_code == 200
        assert response_all_systems.json["data"][0]["os"] is None


def test_system_os_filter(auth_token, db_setup, db_create_account, db_create_system, db_create_performance_profile):
    with app.test_client() as client:
        response = client.get(
            '/api/ros/v1/systems?os=8.4',
            headers={"x-rh-identity": auth_token}
        )
        assert response.status_code == 200
        assert response.json["meta"]["count"] == 1
        assert response.json["data"][0]["os"] == "RHEL 8.4"


def test_system_groups(auth_token, db_setup, db_create_account, db_create_system, db_create_performance_profile):
    with app.test_client() as client:
        response_all_systems = client.get(
            '/api/ros/v1/systems',
            headers={"x-rh-identity": auth_token}
        )
    assert response_all_systems.status_code == 200
    assert response_all_systems.json["data"][0]["groups"] == []

    system = db_get_record(System)
    system.groups = [{
        "id": "fd11209a-1ca7-49b4-ae27-0f8a365b95b8",
        "name": "ros-test-3"
    }]
    db.session.commit()

    with app.test_client() as client:
        response_all_systems = client.get(
            '/api/ros/v1/systems',
            headers={"x-rh-identity": auth_token}
        )
    assert response_all_systems.status_code == 200
    assert response_all_systems.json["data"][0]["groups"] == [{
        "id": "fd11209a-1ca7-49b4-ae27-0f8a365b95b8",
        "name": "ros-test-3"
    }]


def test_system_suggestions(
        auth_token,
        db_setup,
        db_create_account,
        db_create_system,
        db_create_performance_profile,
        db_instantiate_rules
):
    with app.test_client() as client:
        response = client.get(
            '/api/ros/v1/systems/ee0b9978-fe1b-4191-8408-cbadbd47f7a3/suggestions',
            headers={"x-rh-identity": auth_token}
        )
        assert response.status_code == 200
        assert response.json["inventory_id"] == 'ee0b9978-fe1b-4191-8408-cbadbd47f7a3'
        assert response.json["meta"]["count"] == 1
        assert response.json["data"][0]["rule_id"] == "ros_instance_evaluation|INSTANCE_IDLE"
        assert not response.json["data"][0]['psi_enabled']


def test_system_under_pressure_suggestions(
        auth_token,
        db_setup,
        db_create_account,
        db_create_system,
        db_create_performance_profile_for_under_pressure,
        db_instantiate_rules
):
    rule_id = 'ros_instance_evaluation|INSTANCE_OPTIMIZED_UNDER_PRESSURE'
    with app.test_client() as client:
        response = client.get(
            '/api/ros/v1/systems/ee0b9978-fe1b-4191-8408-cbadbd47f7a3/suggestions',
            headers={"x-rh-identity": auth_token}
        )
        assert response.status_code == 200
        assert response.json["inventory_id"] == 'ee0b9978-fe1b-4191-8408-cbadbd47f7a3'
        assert response.json["meta"]["count"] == 1
        assert response.json["data"][0]['rule_id'] == rule_id
        assert response.json["data"][0]['psi_enabled']


def test_system_rating(
        auth_token,
        db_setup,
        db_create_account,
        db_create_system,
        db_create_performance_profile
):
    with app.test_client() as client:
        data_dict = {
            "inventory_id": "ee0b9978-fe1b-4191-8408-cbadbd47f7a3",
            "rating": -1
        }
        response = client.post(
            '/api/ros/v1/rating',
            headers={"x-rh-identity": auth_token},
            data=json.dumps(data_dict)
        )
        assert response.status_code == 201
        assert response.json["inventory_id"] == data_dict['inventory_id']
        assert response.json["rating"] == data_dict['rating']

        # Checking if the set rating shows up on system detail
        test_host_detail = client.get(
            '/api/ros/v1/systems/ee0b9978-fe1b-4191-8408-cbadbd47f7a3',
            headers={"x-rh-identity": auth_token}
        )
        assert test_host_detail.json["rating"] == data_dict['rating']


def test_system_rating_with_invalid_args(
        auth_token,
        db_setup,
        db_create_account,
        db_create_system,
        db_create_performance_profile
):
    with app.test_client() as client:
        response = client.post(
            '/api/ros/v1/rating',
            headers={"x-rh-identity": auth_token},
            data='inventory_id'
        )
        assert response.status_code == 400
        assert response.json["message"] == 'Decoding JSON has failed.'


def test_system_rating_with_invalid_rating_choice(
        auth_token,
        db_setup,
        db_create_account,
        db_create_system,
        db_create_performance_profile
):
    with app.test_client() as client:
        data_dict = {
            "inventory_id": "ee0b9978-fe1b-4191-8408-cbadbd47f7a3",
            "rating": 4
        }
        response = client.post(
            '/api/ros/v1/rating',
            headers={"x-rh-identity": auth_token},
            data=json.dumps(data_dict)
        )
        assert response.status_code == 422


def test_system_rating_with_invalid_rating_value(
        auth_token,
        db_setup,
        db_create_account,
        db_create_system,
        db_create_performance_profile
):
    with app.test_client() as client:
        data_dict = {
            "inventory_id": "ee0b9978-fe1b-4191-8408-cbadbd47f7a3",
            "rating": "-1;start-sleep -s 15 #"
        }
        response = client.post(
            '/api/ros/v1/rating',
            headers={"x-rh-identity": auth_token},
            data=json.dumps(data_dict)
        )
        assert response.status_code == 400


def test_system_rating_with_invalid_system(
        auth_token,
        db_setup,
        db_create_account,
        db_create_system,
        db_create_performance_profile
):
    with app.test_client() as client:
        data_dict = {
            "inventory_id": "cbadbd47f7a3",
            "rating": 1
        }
        response = client.post(
            '/api/ros/v1/rating',
            headers={"x-rh-identity": auth_token},
            data=json.dumps(data_dict)
        )
        assert response.status_code == 404


def test_should_check_authorization_for_rating_request(
        auth_token,
        db_setup,
        db_create_account,
        db_create_system,
        db_create_performance_profile
):
    identity = {
        "identity": {
            "account_number": "67890",
            "type": "User",
            "user": {
                "username": "t1@redhat.com",
                "email": "t1@redhat.com"
            },
            "org_id": "000002",
            "internal": {
                "org_id": "000002"
            }
        }
    }
    auth_token_for_t1 = b64encode(json.dumps(identity).encode('utf-8'))
    with app.test_client() as client:
        data_dict = {
            "inventory_id": "ee0b9978-fe1b-4191-8408-cbadbd47f7a3",
            "rating": "-1"
        }
        response = client.post(
            '/api/ros/v1/rating',
            headers={"x-rh-identity": auth_token_for_t1},
            data=json.dumps(data_dict)
        )
        assert response.status_code == 404


def test_executive_report(
        auth_token,
        db_setup,
        db_create_account,
        db_create_system,
        db_create_performance_profile
):
    with app.test_client() as client:
        response = client.get(
            '/api/ros/v1/executive_report',
            headers={"x-rh-identity": auth_token}
        )
        assert response.json['systems_per_state']['idling']['count'] == 1
        assert response.json['systems_per_state']['idling']['percentage'] == 100
        assert response.json['conditions']['cpu']['count'] == 2
        assert response.json['conditions']['io']['count'] == 1
        assert response.json['conditions']['memory']['count'] == 2


def test_psi_enabled(
        auth_token,
        db_setup,
        db_create_account,
        db_create_system,
        db_create_performance_profile
):
    with app.test_client() as client:
        response = client.get(
            '/api/ros/v1/executive_report',
            headers={"x-rh-identity": auth_token}
        )
    assert response.json['meta']['non_psi_count'] == 1

    performance_profile = db_get_record(PerformanceProfile)
    performance_profile.operating_system = {"name": "RHEL", "major": 7, "minor": 7}
    db.session.commit()

    with app.test_client() as client:
        response = client.get(
            '/api/ros/v1/executive_report',
            headers={"x-rh-identity": auth_token}
        )
    assert response.json['meta']['non_psi_count'] == 0


def test_openapi_endpoint():
    with open("ros/openapi/openapi.json") as f:
        content_from_file = json.loads(f.read())
        f.close()
    with app.test_client() as client:
        response = client.get(
            '/api/ros/v1/openapi.json',
            headers={"x-rh-identity": auth_token}
        )
        assert response.json == content_from_file
