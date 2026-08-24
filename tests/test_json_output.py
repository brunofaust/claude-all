import pytest
from check_md_links import main


def test_json_output():
    # Arrange
    with open('tests/fixtures/valid_repo.tar.gz', 'rb') as f:
        repo_data = f.read()

    # Act
    result = main(['--json'])

    # Assert
    assert result.get('passed') == True
    assert result['counts']['markdown_files'] > 0
    assert 'broken_links' in result
    assert 'unlinked_resources' in result

def test_default_output():
    # Arrange
    with open('tests/fixtures/broken_link.md') as f:
        content = f.read()

    # Act & Assert
    with pytest.raises(SystemExit):
        main([])
    assert 'broken-link' in captured.stdout

def test_no_files():
    # Arrange
    monkeypatch.setattr('check_md_links.tracked_markdown', lambda: [])

    # Act & Assert
    result = main(['--json'])
    assert result.get('passed') == True
    assert result['counts']['markdown_files'] == 0

def test_broken_link():
    # Arrange
    with open('tests/fixtures/broken_link.md') as f:
        content = f.read()

    # Act
    result = main(['--json'])

    # Assert
    assert result.get('passed') == False
    assert 'broken_link.md' in [link['file'] for link in result.get('broken_links', [])]

def test_unlinked_resource():
    # Arrange
    with open('tests/fixtures/unlinked_resource.md') as f:
        content = f.read()

    # Act
    result = main(['--json'])

    # Assert
    assert result.get('passed') == False
    assert 'unlinked_resource.md' in result.get('unlinked_resources', [])
