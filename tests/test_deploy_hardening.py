from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ansible_git_pull_does_not_ignore_errors():
    playbook = (ROOT / "deploy" / "ansible-playbook.yml").read_text(encoding="utf-8")
    pull_task = playbook.split("- name: Pull latest source from origin", 1)[1].split("- name:", 1)[0]
    assert "ignore_errors" not in pull_task


def test_dockerignore_excludes_git_directory():
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert ".git/" in lines


def test_dockerignore_excludes_deploy_secrets_and_local_env_files():
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    required_patterns = {
        ".env.*",
        ".vault_pass*",
        "deploy/",
        "tests/",
        ".github/",
        "logs/",
        "*.pem",
        "*.key",
    }
    assert required_patterns.issubset(set(lines))


def test_dockerfile_runs_as_non_root_user():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "useradd" in dockerfile
    assert "--uid 10001" in dockerfile
    assert "USER inebotten" in dockerfile
    assert "/home/inebotten/.hermes" in dockerfile


def test_ansible_ensures_data_dir_is_writable_by_runtime_uid():
    playbook = (ROOT / "deploy" / "ansible-playbook.yml").read_text(encoding="utf-8")
    assert "{{ compose_dir }}/data" in playbook
    assert 'owner: "10001"' in playbook
    assert 'group: "10001"' in playbook
    assert "recurse: true" in playbook


def test_ansible_passes_checked_out_commit_to_compose_build():
    playbook = (ROOT / "deploy" / "ansible-playbook.yml").read_text(encoding="utf-8")
    assert "git rev-parse --short HEAD" in playbook
    assert "SOURCE_COMMIT={{ source_commit.stdout }}" in playbook
    assert "COMMIT_SHA={{ source_commit.stdout }}" in playbook


def test_ansible_fails_if_running_container_commit_is_stale():
    playbook = (ROOT / "deploy" / "ansible-playbook.yml").read_text(encoding="utf-8")
    assert "docker exec inebotten-bot cat /app/commit_hash.txt" in playbook
    assert "Fail if running container is stale" in playbook
    assert "running_commit.stdout | default('') != source_commit.stdout" in playbook


def test_compose_mounts_non_root_home_and_caddy_is_opt_in():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "./data:/home/inebotten/.hermes" in compose
    assert 'user: "10001:10001"' in compose
    assert "data-permissions:" in compose
    assert "chown -R 10001:10001 /data" in compose
    inebotten_block = compose.split("  inebotten:", 1)[1].split("  caddy:", 1)[0]
    assert "condition: service_completed_successfully" in inebotten_block
    caddy_block = compose.split("  caddy:", 1)[1]
    assert "profiles:" in caddy_block
    assert "bundled-caddy" in caddy_block
