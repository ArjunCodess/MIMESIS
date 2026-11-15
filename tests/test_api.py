"""Public API integration checks against the shipped research records."""
from fastapi.testclient import TestClient

from services.api.main import app, bundle
from src.ranking import rank

client = TestClient(app)


def test_catalogue_and_health_match_the_shipped_data():
    data = bundle()
    health = client.get('/v1/health')
    assert health.status_code == 200
    assert health.json()['candidate_count'] == len(data['candidates'])
    assert client.get('/v1/catalog').json()['targets'] == data['targets']


def test_ranking_matches_the_offline_calculation_and_export():
    data = bundle()
    target = next(row for row in data['targets'] if row['id'] == 'jezero')
    for support, field in [(500, 'rankings'), (1000, 'rankings_1000')]:
        response = client.post('/v1/rank', json={'target_id': 'jezero', 'support_m': support})
        assert response.status_code == 200
        assert response.json() == rank(data['candidates'], target, data['protocol'], support)
        assert response.json() == data[field]['jezero']


def test_invalid_inputs_and_unsupported_claims_are_rejected():
    assert client.post('/v1/rank', json={'target_id': 'missing'}).status_code == 404
    assert client.post('/v1/rank', json={'target_id': 'jezero', 'weights': [-1, 1, 1, 1]}).status_code == 422
    result = client.post('/v1/rank', json={'target_id': 'jezero', 'objective': 'base_suitability'})
    assert result.status_code == 200
    assert result.json()['state'] == 'unsupported_objective'
