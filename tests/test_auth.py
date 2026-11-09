import json
import sqlite3
from datetime import datetime

from fastapi.testclient import TestClient

from backend import database
from backend.config import get_settings
from backend import main
from backend.main import app


def test_authentication_and_case_ownership_are_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB', tmp_path / 'medibridge-test.db')
    monkeypatch.setitem(main.settings, 'clinical_data_approved', True)
    database.init_db()

    with TestClient(app) as coder, TestClient(app) as other_coder:
        assert coder.get('/api/auth/me').json() == {'user': None}
        assert coder.get('/api/dashboard').status_code == 401
        assert coder.get('/api/cases').status_code == 401
        assert coder.get('/api/codes?q=I10').status_code == 401
        assert coder.post(
            '/api/auth/signup',
            headers={'Origin': 'https://untrusted.example'},
            json={
                'full_name': 'Cross Site Coder',
                'email': 'external@example.org',
                'password': 'correct-horse-battery-9',
            },
        ).status_code == 403

        signup = coder.post('/api/auth/signup', json={
            'full_name': 'Coder One',
            'email': 'coder@example.org',
            'password': 'correct-horse-battery-1',
        })
        assert signup.status_code == 200
        assert signup.json()['user']['email'] == 'coder@example.org'
        assert signup.cookies.get('medibridge_session')
        assert 'httponly' in signup.headers['set-cookie'].lower()
        assert 'samesite=strict' in signup.headers['set-cookie'].lower()
        assert signup.headers['content-security-policy'].startswith("default-src 'self'")
        assert signup.headers['cache-control'] == 'no-store'

        created = coder.post('/api/analyze/text', json={
            'text': 'Patient has hypertension and type 2 diabetes.',
        })
        assert created.status_code == 200
        case_id = created.json()['case']['id']
        assert created.json()['case']['assigned_at']
        assert created.json()['case']['deadline_at']
        own_notifications = coder.get('/api/notifications').json()
        assert own_notifications['summary']['assigned_today'] == 1
        assert own_notifications['summary']['open_cases'] == 1
        assert own_notifications['notifications'][0]['case_id'] == case_id
        connection = database.conn()
        deadline = datetime.now().astimezone().replace(
            hour=23, minute=59, second=59, microsecond=0
        ).isoformat()
        connection.execute(
            'UPDATE cases SET deadline_at=? WHERE id=?', (deadline, case_id)
        )
        connection.commit()
        connection.close()
        due_notifications = coder.get('/api/notifications').json()
        assert due_notifications['summary']['due_today'] == 1
        assert due_notifications['notifications'][0]['category'] == 'due_today'
        assert len(coder.get('/api/cases').json()) == 1
        assert coder.get(f'/api/cases/{case_id}').json()['gaps'] == created.json()['case']['gaps']
        assert coder.post(
            f'/api/cases/{case_id}/decision',
            json={'decision': 'Validated', 'note': 'Reviewed against the applicable reference.'},
        ).status_code == 200
        assert coder.get(f'/api/cases/{case_id}').json()['status'] == 'Validated'
        assert coder.get('/api/notifications').json()['summary']['open_cases'] == 0

        second_signup = other_coder.post('/api/auth/signup', json={
            'full_name': 'Coder Two',
            'email': 'coder2@example.org',
            'password': 'correct-horse-battery-2',
        })
        assert second_signup.status_code == 200
        assert other_coder.get('/api/cases').json() == []
        assert other_coder.get(f'/api/cases/{case_id}').status_code == 404
        assert other_coder.post(
            f'/api/cases/{case_id}/decision',
            json={'decision': 'Validated'},
        ).status_code == 404
        assert other_coder.get('/api/dashboard').json()['metrics']['documents_analyzed'] == 0
        assert other_coder.get('/api/notifications').json()['summary']['open_cases'] == 0
        assert other_coder.get('/api/catalogs').status_code == 200

        assert coder.post('/api/auth/logout').status_code == 200
        assert coder.get('/api/dashboard').status_code == 401


def test_signup_rejects_duplicate_accounts_and_weak_passwords(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB', tmp_path / 'medibridge-test.db')
    database.init_db()

    with TestClient(app) as client:
        account = {
            'full_name': 'Coder One',
            'email': 'coder@example.org',
            'password': 'correct-horse-battery-1',
        }
        assert client.post('/api/auth/signup', json=account).status_code == 200
        assert client.post('/api/auth/signup', json=account).status_code == 409
        account['email'] = 'another@example.org'
        account['password'] = 'short'
        assert client.post('/api/auth/signup', json=account).status_code == 422


def test_login_logout_and_expired_sessions_are_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB', tmp_path / 'auth-lifecycle.sqlite')
    database.init_db()
    account = {
        'full_name': 'Session Test Coder',
        'email': 'session-coder@example.org',
        'password': 'correct-horse-battery-7',
    }

    with TestClient(app) as client:
        assert client.post('/api/auth/signup', json=account).status_code == 200
        assert client.post('/api/auth/logout').status_code == 200
        assert client.get('/api/dashboard').status_code == 401
        assert client.post('/api/auth/login', json={
            'email': account['email'],
            'password': 'incorrect-password',
        }).status_code == 401

        login = client.post('/api/auth/login', json=account)
        assert login.status_code == 200
        assert client.get('/api/dashboard').status_code == 200
        token = client.cookies.get('medibridge_session')
        assert token

        connection = database.conn()
        connection.execute(
            'UPDATE auth_sessions SET expires_at=0 WHERE user_id=('
            'SELECT id FROM users WHERE email=?)',
            (account['email'],),
        )
        connection.commit()
        connection.close()

        assert client.get('/api/dashboard').status_code == 401
        assert client.get('/api/auth/me').json() == {'user': None}
        assert client.post('/api/auth/logout').status_code == 200
        assert client.cookies.get('medibridge_session') is None


def test_txt_and_pdf_uploads_are_processed_as_authenticated_cases(tmp_path, monkeypatch):
    from io import BytesIO
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    monkeypatch.setattr(database, 'DB', tmp_path / 'document-uploads.sqlite')
    monkeypatch.setitem(main.settings, 'clinical_data_approved', True)
    database.init_db()

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({
        NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'),
        NameObject('/BaseFont'): NameObject('/Helvetica'),
    })
    page[NameObject('/Resources')] = DictionaryObject({
        NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})
    })
    content = DecodedStreamObject()
    content.set_data(
        b'BT /F1 12 Tf 72 720 Td (Patient has hypertension.) Tj ET'
    )
    page[NameObject('/Contents')] = writer._add_object(content)
    pdf_content = BytesIO()
    writer.write(pdf_content)

    with TestClient(app) as client:
        assert client.post('/api/auth/signup', json={
            'full_name': 'Upload Test Coder',
            'email': 'upload-coder@example.org',
            'password': 'correct-horse-battery-8',
        }).status_code == 200
        text_response = client.post(
            '/api/analyze/file',
            files={'file': ('synthetic.txt', b'Patient has hypertension.')},
        )
        pdf_response = client.post(
            '/api/analyze/file',
            files={'file': ('synthetic.pdf', pdf_content.getvalue(), 'application/pdf')},
        )

    assert text_response.status_code == 200
    assert text_response.json()['case']['document_name'] == 'synthetic.txt'
    assert pdf_response.status_code == 200
    assert pdf_response.json()['case']['document_name'] == 'synthetic.pdf'
    assert pdf_response.json()['case']['source_locations'][0]['page'] == 1
    connection = database.conn()
    persisted = connection.execute(
        'SELECT source,document_name,text FROM cases ORDER BY created_at'
    ).fetchall()
    connection.close()
    assert [(row['source'], row['document_name']) for row in persisted] == [
        ('upload', 'synthetic.txt'),
        ('upload', 'synthetic.pdf'),
    ]
    assert all('hypertension' in row['text'].casefold() for row in persisted)


def test_clinical_analysis_is_disabled_without_explicit_approval(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB', tmp_path / 'medibridge-test.db')
    monkeypatch.setitem(main.settings, 'clinical_data_approved', False)
    database.init_db()

    with TestClient(app) as client:
        assert client.get('/api/health').json()['clinical_data_enabled'] is False
        assert client.post('/api/auth/signup', json={
            'full_name': 'Coder One',
            'email': 'coder@example.org',
            'password': 'correct-horse-battery-1',
        }).status_code == 200
        blocked = client.post('/api/analyze/text', json={
            'text': 'Synthetic patient has hypertension.',
        })
        assert blocked.status_code == 503
        assert 'organizational governance' in blocked.json()['detail']


def test_production_health_reports_safe_gates_and_https_headers(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB', tmp_path / 'production-health.sqlite')
    monkeypatch.setitem(main.settings, 'app_env', 'production')
    monkeypatch.setitem(main.settings, 'clinical_data_approved', False)
    monkeypatch.setitem(main.settings, 'synthetic_demo_enabled', True)
    database.init_db()

    with TestClient(app) as client:
        response = client.get('/api/health')

    assert response.status_code == 200
    assert response.json()['environment'] == 'production'
    assert response.json()['clinical_data_enabled'] is False
    assert response.json()['synthetic_demo_enabled'] is True
    assert response.headers['strict-transport-security'].startswith('max-age=')
    assert response.headers['cache-control'] == 'no-store'


def test_complete_release_evidence_still_cannot_bypass_missing_org_approval(
    tmp_path, monkeypatch
):
    approvals = {
        key: {'approved': True, 'reference': f'review-{key}'}
        for key in (
            'clinical_governance',
            'privacy_security_review',
            'clinician_signoff',
            'local_model_verified',
            'evaluation_passed',
            'retention_backup_review',
        )
    }
    approvals_path = tmp_path / 'complete-approvals.json'
    approvals_path.write_text(json.dumps(approvals), encoding='utf-8')
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('CLINICAL_DATA_APPROVED', 'true')
    monkeypatch.setenv('SYNTHETIC_DEMO_ENABLED', 'false')
    monkeypatch.setenv('RELEASE_APPROVALS_PATH', str(approvals_path))
    monkeypatch.setattr(database, 'DB', tmp_path / 'app.sqlite')
    runtime_settings = get_settings()
    monkeypatch.setitem(
        main.settings, 'clinical_data_approved',
        runtime_settings['clinical_data_approved'],
    )
    database.init_db()

    assert runtime_settings['clinical_data_approved'] is False
    assert any(
        'Organization-scoped clinical approval is not implemented.' in reason
        for reason in runtime_settings['analysis_gate_reasons']
    )

    with TestClient(app) as client:
        assert client.post('/api/auth/signup', json={
            'full_name': 'Test Coder',
            'email': 'test-coder@example.org',
            'password': 'correct-horse-battery-1',
        }).status_code == 200
        blocked = client.post('/api/analyze/text', json={
            'text': 'Synthetic test note with hypertension.',
        })

    assert blocked.status_code == 503
    connection = database.conn()
    assert connection.execute('SELECT COUNT(*) FROM cases').fetchone()[0] == 0
    connection.close()


def test_synthetic_production_mode_overrides_clinical_approval(tmp_path, monkeypatch):
    approvals = {
        key: {'approved': True, 'reference': f'review-{key}'}
        for key in (
            'clinical_governance',
            'privacy_security_review',
            'clinician_signoff',
            'local_model_verified',
            'evaluation_passed',
            'retention_backup_review',
        )
    }
    approvals_path = tmp_path / 'approvals.json'
    approvals_path.write_text(json.dumps(approvals), encoding='utf-8')
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('CLINICAL_DATA_APPROVED', 'true')
    monkeypatch.setenv('SYNTHETIC_DEMO_ENABLED', 'true')
    monkeypatch.setenv('RELEASE_APPROVALS_PATH', str(approvals_path))

    settings = get_settings()

    assert settings['synthetic_demo_enabled'] is True
    assert settings['clinical_data_approved'] is False
    assert 'Synthetic-only demo mode disables clinical document analysis.' in (
        settings['analysis_gate_reasons']
    )


def test_builtin_synthetic_examples_are_removed():
    with TestClient(app) as client:
        response = client.get('/api/demo/analyze')
        assert response.status_code == 404
        assert response.json()['detail'] == 'API endpoint not found.'
        assert client.post('/api/demo/analyze', json={
            'example_id': 'history-and-negation',
        }).status_code == 405


def test_public_synthetic_inputs_are_ephemeral_and_require_confirmation(tmp_path, monkeypatch):
    from io import BytesIO
    from docx import Document

    monkeypatch.setattr(database, 'DB', tmp_path / 'public-demo.db')
    monkeypatch.setitem(main.settings, 'synthetic_demo_enabled', True)
    monkeypatch.setitem(main.settings, 'clinical_data_approved', False)
    database.init_db()
    document = Document()
    document.add_paragraph('Synthetic example: hypertension is documented.')
    content = BytesIO()
    document.save(content)

    with TestClient(app) as client:
        synthetic_note = (
            'Synthetic note: patient has hypertension. Routine venipuncture for '
            'collection of specimen(s), single home bound, nursing home, or '
            'skilled nursing facility patient.'
        )
        text_response = client.post('/api/demo/analyze/text', json={
            'text': synthetic_note,
            'synthetic_only': True,
        })
        assert text_response.status_code == 200
        assert text_response.json()['case']['source'] == 'synthetic_demo'
        assert text_response.json()['case']['text'].startswith('Synthetic note:')
        assert {'ICD-10-CM', 'HCPCS'} <= {
            recommendation['type']
            for recommendation in text_response.json()['case']['recommendations']
        }
        workflow = text_response.json()['case']['workflow']
        assert workflow['engine'] == 'LangGraph'
        assert [node['id'] for node in workflow['nodes']] == [
            'parse', 'retrieve', 'reason', 'validate',
        ]
        assert workflow['human_review_required'] is True
        assert client.post('/api/demo/analyze/text', json={
            'text': 'Synthetic note: patient has hypertension.',
        }).status_code == 422
        assert client.post('/api/demo/analyze/file', files={
            'file': ('synthetic.docx', content.getvalue()),
        }).status_code == 400
        uploaded = client.post('/api/demo/analyze/file', data={
            'synthetic_only': 'true',
        }, files={'file': (
            'synthetic.docx',
            content.getvalue(),
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )})
        assert uploaded.status_code == 200
        assert uploaded.json()['case']['source_locations'][0]['paragraph'] == 1
        assert client.get('/api/health').json()['clinical_data_enabled'] is False
        assert client.post('/api/analyze/text', json={
            'text': 'Synthetic note: patient has hypertension.',
        }).status_code == 401

    connection = database.conn()
    assert connection.execute('SELECT COUNT(*) FROM cases').fetchone()[0] == 0
    assert connection.execute('SELECT COUNT(*) FROM activity').fetchone()[0] == 0
    connection.close()


def test_docx_upload_persists_extracted_source_locations(tmp_path, monkeypatch):
    from io import BytesIO
    from docx import Document

    monkeypatch.setattr(database, 'DB', tmp_path / 'medibridge-test.db')
    monkeypatch.setitem(main.settings, 'clinical_data_approved', True)
    database.init_db()
    document = Document()
    document.add_paragraph('Patient has hypertension and diabetes.')
    content = BytesIO()
    document.save(content)

    with TestClient(app) as client:
        assert client.post('/api/auth/signup', json={
            'full_name': 'Coder One',
            'email': 'coder@example.org',
            'password': 'correct-horse-battery-1',
        }).status_code == 200
        response = client.post(
            '/api/analyze/file',
            files={'file': (
                'note.docx',
                content.getvalue(),
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            )},
        )
        if response.status_code == 200:
            stored = client.get(f"/api/cases/{response.json()['case']['id']}")

    assert response.status_code == 200
    assert response.json()['case']['source_locations'] == [
        {'paragraph': 1, 'start': 0, 'end': len('Patient has hypertension and diabetes.')}
    ]
    assert response.json()['case']['workflow']['model_status'] == 'unconfigured'
    assert stored.status_code == 200
    assert stored.json()['workflow']['name'] == 'LangGraph analysis workflow'
    assert stored.json()['workflow']['engine'] == 'LangGraph'


def test_legacy_database_migration_preserves_cases_and_global_settings(tmp_path, monkeypatch):
    legacy_db = tmp_path / 'legacy.db'
    connection = sqlite3.connect(legacy_db)
    connection.executescript('''
        CREATE TABLE cases(
            id TEXT PRIMARY KEY, created_at TEXT NOT NULL, document_name TEXT,
            source TEXT, text TEXT NOT NULL, status TEXT NOT NULL,
            overall_confidence REAL NOT NULL, extracted_json TEXT NOT NULL,
            recommendations_json TEXT NOT NULL
        );
        CREATE TABLE activity(
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
            kind TEXT NOT NULL, title TEXT NOT NULL, detail TEXT NOT NULL
        );
        CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO cases VALUES(
            'OLD-1','2025-01-01','Old case','text','Legacy clinical note',
            'Review',60,'{}','[]'
        );
        INSERT INTO settings VALUES('review_threshold','80');
    ''')
    connection.commit()
    connection.close()

    monkeypatch.setattr(database, 'DB', legacy_db)
    database.init_db()

    migrated = database.conn()
    case = migrated.execute('SELECT * FROM cases WHERE id=?', ('OLD-1',)).fetchone()
    legacy_setting = migrated.execute(
        'SELECT value FROM legacy_settings WHERE key=?', ('review_threshold',)
    ).fetchone()
    migrated.close()

    assert case['user_id'] is None
    assert case['gaps_json'] == '[]'
    assert case['workflow_json'] == '{}'
    assert legacy_setting['value'] == '80'
