from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_ansible_source_sync_precedes_shared_deployer_and_never_removes_other_containers():
    playbook = yaml.safe_load((ROOT/'deploy/ansible-playbook.yml').read_text())
    tasks = playbook[0]['tasks']
    pull = next(i for i,t in enumerate(tasks) if 'ansible.builtin.git' in t)
    apply = next(i for i,t in enumerate(tasks) if 'apply with full' in t['name'])
    assert pull < apply
    assert tasks[pull]['ansible.builtin.git']['force'] is False
    assert 'ignore_errors' not in tasks[pull]
    assert all('community.docker.docker_container' not in t for t in tasks)
    assert 'git rev-parse HEAD' in (ROOT/'deploy/ansible-playbook.yml').read_text()
    assert 'inebotten_deploy.py' in tasks[apply]['ansible.builtin.command']['argv']


def test_docker_context_excludes_secrets_and_owned_scratch_but_keeps_public_school_asset():
    lines = (ROOT/'.dockerignore').read_text().splitlines()
    assert {'.git/', '.env.*', '.vault_pass*', 'deploy/', 'tests/', '.github/', 'logs/',
            '*.pem', '*.key', '.superpowers/', '.venv*/', '.deployment/', '.artifacts/'}.issubset(lines)
    assert lines.index('!features/data/school_calendars.json') > lines.index('*.json')


def test_container_bakes_strict_full_revision_schema_labels_and_real_readiness_probe():
    dockerfile = (ROOT/'Dockerfile').read_text()
    assert '--uid 10001' in dockerfile and 'USER inebotten' in dockerfile
    assert 'scripts/write_version.py --require-full' in dockerfile
    assert '|| echo' not in dockerfile
    assert 'org.opencontainers.image.revision=$SOURCE_COMMIT' in dockerfile
    assert all(label in dockerfile for label in ['config-schema', 'data-schema-min', 'data-schema-max'])
    assert 'HEALTHCHECK' in dockerfile and 'scripts/deployment_health.py' in dockerfile


def test_compose_never_recursively_reowns_existing_private_data():
    compose = yaml.safe_load((ROOT/'docker-compose.yml').read_text())
    bot = compose['services']['inebotten']
    assert bot['user'] == '10001:10001'
    assert './data:/home/inebotten/.hermes' in bot['volumes']
    assert 'data-permissions' not in compose['services']
    assert 'bundled-caddy' in compose['services']['caddy']['profiles']
    assert 'recurse: true' not in (ROOT/'deploy/ansible-playbook.yml').read_text()
