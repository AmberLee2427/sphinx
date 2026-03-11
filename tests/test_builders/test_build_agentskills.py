"""Test the agentskills builder."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from sphinx.testing.util import SphinxTestApp


@pytest.mark.sphinx('agentskills', testroot='ext-agentskills')
def test_basic_output_exists(app: SphinxTestApp) -> None:
    app.build()
    skill_file = app.outdir / 'SKILL.md'
    assert skill_file.exists()


@pytest.mark.sphinx('agentskills', testroot='ext-agentskills')
def test_front_matter(app: SphinxTestApp) -> None:
    app.build()
    content = (app.outdir / 'SKILL.md').read_text(encoding='utf-8')
    assert content.startswith('---')
    assert 'name: TestProject' in content
    assert 'version: 1.2.3' in content
    assert 'kind: package-doc-skill' in content
    assert 'generated-by: sphinx' in content


@pytest.mark.sphinx('agentskills', testroot='ext-agentskills')
def test_toc_section(app: SphinxTestApp) -> None:
    app.build()
    content = (app.outdir / 'SKILL.md').read_text(encoding='utf-8')
    assert '## Table of contents' in content
    assert 'api' in content
    assert 'configuration' in content
    assert 'changes' in content


@pytest.mark.sphinx('agentskills', testroot='ext-agentskills')
def test_page_classification_api(app: SphinxTestApp) -> None:
    app.build()
    content = (app.outdir / 'SKILL.md').read_text(encoding='utf-8')
    # api.rst should appear under ## API reference
    lines = content.splitlines()
    api_ref_idx = next(
        (i for i, line in enumerate(lines) if line == '## API reference'), None
    )
    assert api_ref_idx is not None, 'No ## API reference section found'
    # Find the next section heading after api_ref_idx
    next_section = next(
        (i for i, line in enumerate(lines) if i > api_ref_idx and line.startswith('## ')),
        len(lines),
    )
    section_content = '\n'.join(lines[api_ref_idx:next_section])
    assert 'api' in section_content


@pytest.mark.sphinx('agentskills', testroot='ext-agentskills')
def test_page_classification_config(app: SphinxTestApp) -> None:
    app.build()
    content = (app.outdir / 'SKILL.md').read_text(encoding='utf-8')
    lines = content.splitlines()
    config_ref_idx = next(
        (i for i, line in enumerate(lines) if line == '## Configuration reference'), None
    )
    assert config_ref_idx is not None, 'No ## Configuration reference section found'
    next_section = next(
        (i for i, line in enumerate(lines) if i > config_ref_idx and line.startswith('## ')),
        len(lines),
    )
    section_content = '\n'.join(lines[config_ref_idx:next_section])
    assert 'configuration' in section_content


@pytest.mark.sphinx('agentskills', testroot='ext-agentskills')
def test_page_classification_release_notes(app: SphinxTestApp) -> None:
    app.build()
    content = (app.outdir / 'SKILL.md').read_text(encoding='utf-8')
    lines = content.splitlines()
    rn_idx = next(
        (i for i, line in enumerate(lines) if line == '## Release notes'), None
    )
    assert rn_idx is not None, 'No ## Release notes section found'
    next_section = next(
        (i for i, line in enumerate(lines) if i > rn_idx and line.startswith('## ')),
        len(lines),
    )
    section_content = '\n'.join(lines[rn_idx:next_section])
    assert 'changes' in section_content


@pytest.mark.sphinx('agentskills', testroot='ext-agentskills')
def test_documented_modules(app: SphinxTestApp) -> None:
    app.build()
    content = (app.outdir / 'SKILL.md').read_text(encoding='utf-8')
    assert '## Documented modules' in content
    assert 'testproject.core' in content


@pytest.mark.sphinx('agentskills', testroot='ext-agentskills')
def test_no_split_by_default(app: SphinxTestApp) -> None:
    app.build()
    assert not (app.outdir / 'modules').exists()


@pytest.mark.sphinx(
    'agentskills',
    testroot='ext-agentskills',
    confoverrides={'agentskills_split_modules': True, 'agentskills_split_threshold': 0},
)
def test_split_modules(app: SphinxTestApp) -> None:
    app.build()
    assert (app.outdir / 'modules' / 'testproject' / 'SKILL.md').exists()


@pytest.mark.sphinx(
    'agentskills',
    testroot='ext-agentskills',
    confoverrides={'agentskills_split_modules': True, 'agentskills_split_threshold': 0},
)
def test_module_skill_front_matter(app: SphinxTestApp) -> None:
    app.build()
    content = (app.outdir / 'modules' / 'testproject' / 'SKILL.md').read_text(encoding='utf-8')
    assert 'kind: module-doc-skill' in content
    assert 'parent: ../SKILL.md' in content


@pytest.mark.sphinx(
    'agentskills',
    testroot='ext-agentskills',
    confoverrides={'agentskills_exclude_pages': ['changes']},
)
def test_exclude_pages(app: SphinxTestApp) -> None:
    app.build()
    content = (app.outdir / 'SKILL.md').read_text(encoding='utf-8')
    assert 'changes' not in content


@pytest.mark.sphinx(
    'agentskills',
    testroot='ext-agentskills',
    confoverrides={'agentskills_page_hints': {'api': 'tutorial'}},
)
def test_page_hints(app: SphinxTestApp) -> None:
    app.build()
    content = (app.outdir / 'SKILL.md').read_text(encoding='utf-8')
    # api page should be under Tutorials and guides, not API reference
    assert '## Tutorials and guides' in content
    lines = content.splitlines()
    tutorial_idx = next(
        (i for i, line in enumerate(lines) if line == '## Tutorials and guides'), None
    )
    assert tutorial_idx is not None
    next_section = next(
        (i for i, line in enumerate(lines) if i > tutorial_idx and line.startswith('## ')),
        len(lines),
    )
    section_content = '\n'.join(lines[tutorial_idx:next_section])
    assert 'api' in section_content
    # Should NOT appear under ## API reference
    api_ref_idx = next(
        (i for i, line in enumerate(lines) if line == '## API reference'), None
    )
    assert api_ref_idx is None, 'api page should not appear under ## API reference when hinted as tutorial'


@pytest.mark.sphinx('agentskills', testroot='ext-agentskills')
def test_notes_section(app: SphinxTestApp) -> None:
    app.build()
    content = (app.outdir / 'SKILL.md').read_text(encoding='utf-8')
    assert '## Notes for agents' in content
    assert '1.2.3' in content


@pytest.mark.sphinx('agentskills', testroot='ext-agentskills-nopy')
def test_no_py_domain(app: SphinxTestApp) -> None:
    app.build()
    skill_file = app.outdir / 'SKILL.md'
    assert skill_file.exists()
    content = skill_file.read_text(encoding='utf-8')
    assert 'name: NoPI' in content
