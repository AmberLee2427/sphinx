# Detailed Implementation Spec: `sphinx.ext.agentskills`

> This spec is intended for a subagent implementing the feature, reviewed against the
> Sphinx codebase as of the date on this file. All implementation decisions are grounded
> in existing Sphinx conventions.

---

## Summary

Add `sphinx.ext.agentskills`, a first-party Sphinx extension that exposes a new builder
(`agentskills`) to generate compact, versioned `SKILL.md` artifacts from a documentation
build. The artifact is an agent-facing documentation map: a structured file that tells an
LLM agent what a package is, what its major modules are, where the authoritative docs
live, and what version applies. No LLM is involved at build time.

The implementation follows the exact pattern of `sphinx.ext.coverage` — a single
extension file that registers a builder, config values, and produces output files in a
dedicated directory. The builder does all its work from data already present in
`app.env` after the read phase.

---

## Decision log

**Extension vs builder vs hybrid**: Use the `sphinx.ext.coverage` pattern — a first-party
extension file in `sphinx/ext/` that registers a single builder. This is the most
Sphinx-idiomatic approach for artifact-only output, requires no new framework machinery,
and is easy for contributors to review. A dedicated builder cleanly separates concerns
and is invoked predictably with `-b agentskills` or `-M agentskills`.

**Single file vs package**: Single file (`sphinx/ext/agentskills.py`). The feature does
not need sub-modules; a single well-structured file matches coverage, duration, todo, and
most other `sphinx/ext/` extensions.

**Output format**: YAML front matter + Markdown sections, written to `SKILL.md`. YAML
front matter is the established convention for machine-readable skill files in tooling
that consumes them. Markdown renders well for human review. The file is self-describing
without a separate schema.

**No machine-readable sidecar in v1**: Keep scope small. A JSON sidecar can be added
later if specific tooling demands it. One output file per skill is easier to reason about
and test.

**Splitting**: Supported via `agentskills_split_modules = True`, which groups documented
Python objects by top-level package and emits one sub-file per group in addition to the
root `SKILL.md`. Controlled by `agentskills_split_threshold` (integer, default 50 total
documented objects). The root always exists; sub-files are additional.

---

## Files to create or modify

### Create

- `sphinx/ext/agentskills.py` — the extension and builder
- `tests/roots/test-ext-agentskills/conf.py`
- `tests/roots/test-ext-agentskills/index.rst`
- `tests/roots/test-ext-agentskills/api.rst`
- `tests/roots/test-ext-agentskills/configuration.rst`
- `tests/roots/test-ext-agentskills/changes.rst`
- `tests/test_builders/test_build_agentskills.py`
- `doc/usage/extensions/agentskills.rst`

### Modify

- `sphinx/application.py` — add `'sphinx.ext.agentskills'` to `builtin_extensions`
- `doc/usage/extensions/index.rst` — add `agentskills` entry to the built-in extensions
  toctree
- `CHANGES.rst` — add entry under the appropriate version section

---

## `sphinx/ext/agentskills.py` — full spec

### Module docstring

```python
"""Generate agent-facing documentation maps (SKILL.md) from a Sphinx build."""
```

### Imports

Follow the convention from `coverage.py` exactly: standard library first, then Sphinx
imports, then TYPE_CHECKING guard.

```python
from __future__ import annotations

import re
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

import sphinx
from sphinx.builders import Builder
from sphinx.locale import __
from sphinx.util import logging
from sphinx.util.osutil import ensuredir

if TYPE_CHECKING:
    from collections.abc import Set
    from typing import Any

    from sphinx.application import Sphinx
    from sphinx.util.typing import ExtensionMetadata
```

### Logger

```python
logger = logging.getLogger(__name__)
```

### Page classification helper

```python
# Keyword patterns used to classify pages by docname and title.
# Order matters: first match wins.
_PAGE_KIND_PATTERNS: tuple[tuple[str, list[str]], ...] = (
    ('release_notes', ['changelog', 'changes', 'history', 'release', 'news', 'whatsnew']),
    ('tutorial',      ['tutorial', 'guide', 'howto', 'example', 'quickstart', 'getting-started', 'getting_started']),
    ('install',       ['install', 'installation', 'setup', 'requirements']),
    ('config',        ['config', 'configuration', 'settings', 'options', 'reference']),
    ('api',           ['api', 'library', 'autodoc', 'automodule', 'modules']),
)


def _classify_page(docname: str, title: str, hints: dict[str, str]) -> str:
    """Return a page kind string for a docname.

    Uses explicit ``agentskills_page_hints`` first, then heuristics on the
    lowercased docname path components and title words.

    Returns one of: 'api', 'config', 'tutorial', 'install', 'release_notes',
    or 'other'.
    """
    if docname in hints:
        return hints[docname]

    text = f'{docname} {title}'.lower()
    for kind, keywords in _PAGE_KIND_PATTERNS:
        if any(kw in text for kw in keywords):
            return kind
    return 'other'
```

### Builder class

```python
class AgentSkillsBuilder(Builder):
    """Generates agent-facing SKILL.md documentation maps."""

    name = 'agentskills'
    epilog = __('The agent skill files are in %(outdir)s.')

    def get_outdated_docs(self) -> str:
        return 'agentskills overview'

    def get_target_uri(self, docname: str, typ: str | None = None) -> str:
        return ''

    def write_documents(self, _docnames: Set[str]) -> None:
        page_hints: dict[str, str] = self.config.agentskills_page_hints or {}
        pages = self._collect_pages(page_hints)
        py_objects = self._collect_py_objects()
        py_modules = self._collect_py_modules()

        should_split = (
            self.config.agentskills_split_modules
            and len(py_objects) > self.config.agentskills_split_threshold
        )

        ensuredir(self.outdir)

        self._write_package_skill(pages, py_objects, py_modules, should_split)

        if should_split:
            groups = self._group_objects_by_module(py_objects)
            for mod_prefix, objs in groups.items():
                self._write_module_skill(mod_prefix, objs)

    def _collect_pages(
        self, hints: dict[str, str]
    ) -> list[dict[str, Any]]:
        """Return a list of page descriptors from the environment's title map
        and toctree inclusion data.

        Each descriptor is a dict with keys:
            docname, title, kind, depth
        where depth is the toctree depth (0 = root).
        """
        exclude_patterns: list[str] = self.config.agentskills_exclude_pages or []
        compiled = [re.compile(p) for p in exclude_patterns]

        pages = []
        for docname, title_node in self.env.titles.items():
            if any(p.search(docname) for p in compiled):
                continue
            title = title_node.astext()
            kind = _classify_page(docname, title, hints)
            # Determine rough depth: count how many other docs include this one.
            # Pages included by the root document are depth 1; root itself is 0.
            depth = 0
            for parent, children in self.env.toctree_includes.items():
                if docname in children:
                    depth = 1
                    break
            if docname == self.env.config.root_doc:
                depth = 0
            pages.append({
                'docname': docname,
                'title': title,
                'kind': kind,
                'depth': depth,
            })

        # Sort: root first, then by docname for stable output.
        root = self.env.config.root_doc
        pages.sort(key=lambda p: (0 if p['docname'] == root else 1, p['docname']))
        return pages

    def _collect_py_objects(self) -> list[dict[str, Any]]:
        """Return documented Python objects from the py domain.

        Each entry is a dict: name, dispname, objtype, docname, anchor.
        Private names (starting with _) are excluded unless
        agentskills_include_private is True.
        """
        include_private: bool = self.config.agentskills_include_private
        objects = []
        try:
            py_domain = self.env.domains.python_domain
        except AttributeError:
            return objects

        for name, dispname, objtype, docname, anchor, priority in py_domain.get_objects():
            if priority < 0:
                continue
            if not include_private:
                parts = name.split('.')
                if any(part.startswith('_') for part in parts):
                    continue
            objects.append({
                'name': name,
                'dispname': dispname,
                'objtype': objtype,
                'docname': docname,
                'anchor': anchor,
            })

        objects.sort(key=lambda o: (o['objtype'], o['name']))
        return objects

    def _collect_py_modules(self) -> list[dict[str, Any]]:
        """Return documented Python modules from the py domain's module index."""
        modules = []
        try:
            module_data: dict[str, Any] = self.env.domaindata.get('py', {}).get('modules', {})
        except (AttributeError, KeyError):
            return modules

        for modname, data in module_data.items():
            # data is (docname, node_id, synopsis, platform, deprecated)
            if isinstance(data, (tuple, list)) and len(data) >= 1:
                docname = data[0]
                synopsis = data[2] if len(data) > 2 else ''
            else:
                continue
            modules.append({
                'name': modname,
                'docname': docname,
                'synopsis': synopsis or '',
            })

        modules.sort(key=lambda m: m['name'])
        return modules

    def _group_objects_by_module(
        self, objects: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        """Group objects by their top-level package prefix."""
        groups: dict[str, list[dict[str, Any]]] = {}
        for obj in objects:
            prefix = obj['name'].split('.')[0]
            groups.setdefault(prefix, []).append(obj)
        return dict(sorted(groups.items()))

    def _write_package_skill(
        self,
        pages: list[dict[str, Any]],
        py_objects: list[dict[str, Any]],
        py_modules: list[dict[str, Any]],
        has_splits: bool,
    ) -> None:
        output_path = Path(self.outdir) / 'SKILL.md'
        content = self._render_package_skill(pages, py_objects, py_modules, has_splits)
        try:
            output_path.write_text(content, encoding='utf-8')
        except OSError as err:
            logger.warning(__('error writing file %s: %s'), output_path, err)
        else:
            logger.info(__('writing %s... '), output_path)

    def _write_module_skill(
        self, mod_prefix: str, objects: list[dict[str, Any]]
    ) -> None:
        module_dir = Path(self.outdir) / 'modules' / mod_prefix
        ensuredir(module_dir)
        output_path = module_dir / 'SKILL.md'
        content = self._render_module_skill(mod_prefix, objects)
        try:
            output_path.write_text(content, encoding='utf-8')
        except OSError as err:
            logger.warning(__('error writing file %s: %s'), output_path, err)
        else:
            logger.info(__('writing %s... '), output_path)

    def _render_package_skill(
        self,
        pages: list[dict[str, Any]],
        py_objects: list[dict[str, Any]],
        py_modules: list[dict[str, Any]],
        has_splits: bool,
    ) -> str:
        """Render the package-level SKILL.md content."""
        cfg = self.config
        project = cfg.project or 'Unknown'
        version = cfg.version or ''
        release = cfg.release or version

        lines: list[str] = []

        # --- YAML front matter ---
        lines.append('---')
        lines.append(f'name: {project}')
        lines.append(f'description: Agent-facing documentation map for {project}.')
        lines.append(f'version: {release}')
        lines.append('kind: package-doc-skill')
        lines.append('generated-by: sphinx')
        if cfg.html_baseurl:
            lines.append(f'docs-url: {cfg.html_baseurl.rstrip("/")}/')
        lines.append('---')
        lines.append('')

        # --- Overview ---
        lines.append(f'# {project}')
        lines.append('')
        if version:
            lines.append(f'Version: {release}')
            lines.append('')

        # --- Table of contents ---
        toc_pages = [p for p in pages if p['depth'] <= 1 and p['docname'] != cfg.root_doc]
        if toc_pages:
            lines.append('## Table of contents')
            lines.append('')
            for page in toc_pages:
                lines.append(f'- [{page["title"]}]({page["docname"]}) — {page["kind"]}')
            lines.append('')

        # --- Expand for docs (by kind) ---
        kind_groups: dict[str, list[dict[str, Any]]] = {}
        for page in pages:
            kind_groups.setdefault(page['kind'], []).append(page)

        section_map = {
            'api':           ('## API reference',            'For object signatures, module layout, and documented symbols.'),
            'config':        ('## Configuration reference',  'For configuration options and settings.'),
            'tutorial':      ('## Tutorials and guides',     'For usage examples and getting started.'),
            'install':       ('## Installation',             'For installation and setup.'),
            'release_notes': ('## Release notes',            'For version-specific behavior and changes.'),
        }
        for kind, (heading, note) in section_map.items():
            kind_pages = kind_groups.get(kind, [])
            if not kind_pages:
                continue
            lines.append(heading)
            lines.append('')
            lines.append(note)
            lines.append('')
            for page in kind_pages:
                lines.append(f'- [{page["title"]}]({page["docname"]})')
            lines.append('')

        # --- Documented modules ---
        if py_modules:
            lines.append('## Documented modules')
            lines.append('')
            for mod in py_modules:
                entry = f'- `{mod["name"]}`'
                if mod['synopsis']:
                    synopsis = mod['synopsis'].rstrip('.')
                    entry += f' — {synopsis}'
                lines.append(entry)
            lines.append('')

        # --- Key objects ---
        max_objects: int = self.config.agentskills_max_objects
        if py_objects and not has_splits:
            shown = py_objects[:max_objects]
            lines.append('## Key documented objects')
            lines.append('')
            for obj in shown:
                lines.append(f'- `{obj["name"]}` ({obj["objtype"]})')
            if len(py_objects) > max_objects:
                lines.append(f'- … and {len(py_objects) - max_objects} more')
            lines.append('')
        elif py_objects and has_splits:
            # Reference the module sub-skills instead.
            lines.append('## Module skills')
            lines.append('')
            lines.append('This project is split into module-level skills.')
            lines.append('See the `modules/` directory for per-module SKILL.md files.')
            lines.append('')

        # --- Notes for agents ---
        lines.append('## Notes for agents')
        lines.append('')
        notes = [
            'Prefer the API reference section for object signatures and module layout.',
            'Prefer the configuration reference for option questions.',
            'Check the release notes for version-specific behavior.',
            f'All information applies to version {release}.',
        ]
        for note in notes:
            lines.append(f'- {note}')
        lines.append('')

        return '\n'.join(lines)

    def _render_module_skill(
        self, mod_prefix: str, objects: list[dict[str, Any]]
    ) -> str:
        """Render a module-level SKILL.md content."""
        cfg = self.config
        project = cfg.project or 'Unknown'
        release = cfg.release or cfg.version or ''

        lines: list[str] = []

        lines.append('---')
        lines.append(f'name: {mod_prefix}')
        lines.append(f'description: Agent-facing documentation map for {mod_prefix} ({project}).')
        lines.append(f'version: {release}')
        lines.append('kind: module-doc-skill')
        lines.append('generated-by: sphinx')
        lines.append(f'parent: ../SKILL.md')
        lines.append('---')
        lines.append('')
        lines.append(f'# {mod_prefix}')
        lines.append('')
        lines.append(f'Module group `{mod_prefix}` from `{project}` ({release}).')
        lines.append('')

        max_objects: int = self.config.agentskills_max_objects
        shown = objects[:max_objects]

        lines.append('## Documented objects')
        lines.append('')
        for obj in shown:
            lines.append(f'- `{obj["name"]}` ({obj["objtype"]})')
        if len(objects) > max_objects:
            lines.append(f'- … and {len(objects) - max_objects} more')
        lines.append('')

        return '\n'.join(lines)

    def finish(self) -> None:
        pass
```

### `setup()` function

```python
def setup(app: Sphinx) -> ExtensionMetadata:
    app.add_builder(AgentSkillsBuilder)

    app.add_config_value(
        'agentskills_split_modules',
        False,
        '',
        types=frozenset({bool}),
    )
    app.add_config_value(
        'agentskills_split_threshold',
        50,
        '',
        types=frozenset({int}),
    )
    app.add_config_value(
        'agentskills_max_objects',
        30,
        '',
        types=frozenset({int}),
    )
    app.add_config_value(
        'agentskills_include_private',
        False,
        '',
        types=frozenset({bool}),
    )
    app.add_config_value(
        'agentskills_exclude_pages',
        [],
        '',
        types=frozenset({list}),
    )
    app.add_config_value(
        'agentskills_page_hints',
        {},
        '',
        types=frozenset({dict}),
    )

    return {
        'version': sphinx.__display_version__,
        'parallel_read_safe': True,
        'parallel_write_safe': True,
    }
```

---

## `sphinx/application.py` modification

Add `'sphinx.ext.agentskills'` to the `builtin_extensions` tuple. Insert it
alphabetically relative to the other `sphinx.ext.*` entries. The tuple currently begins
with entries like `'sphinx.builders.changes'`, `'sphinx.builders.epub3'`, etc., followed
later by domain entries, then config, then extensions. Look for the `sphinx.ext.coverage`
entry and insert `sphinx.ext.agentskills` immediately before it.

```python
# Find this line in builtin_extensions:
'sphinx.ext.coverage',
# Insert above it:
'sphinx.ext.agentskills',
```

---

## Test root: `tests/roots/test-ext-agentskills/`

### `conf.py`

```python
extensions = ['sphinx.ext.agentskills']

project = 'TestProject'
version = '1.2'
release = '1.2.3'
```

### `index.rst`

```rst
TestProject
===========

.. toctree::

   api
   configuration
   changes
```

### `api.rst`

```rst
API Reference
=============

.. py:module:: testproject.core

   Core functionality.

.. py:function:: testproject.core.frobnicate(x)

   Frobnicate the input.

.. py:class:: testproject.core.Widget

   A widget.
```

### `configuration.rst`

```rst
Configuration
=============

Options for TestProject.
```

### `changes.rst`

```rst
Changelog
=========

Changes in this release.
```

---

## Test file: `tests/test_builders/test_build_agentskills.py`

Follow the exact conventions of `tests/test_builders/test_build_text.py`:

```python
"""Test the agentskills builder."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from sphinx.testing.util import SphinxTestApp
```

### Test fixtures

Use the `@pytest.mark.sphinx` decorator to set up test apps just as in `test_build_text.py`:

```python
@pytest.mark.sphinx('agentskills', testroot='ext-agentskills')
def test_basic_output_exists(app: SphinxTestApp) -> None:
    app.build()
    skill_file = app.outdir / 'SKILL.md'
    assert skill_file.exists()
```

### Required test cases

Implement the following tests (one function per test):

1. **`test_basic_output_exists`** — After build, `SKILL.md` exists in outdir.

2. **`test_front_matter`** — The output file starts with `---`, contains
   `name: TestProject`, `version: 1.2.3`, `kind: package-doc-skill`, and
   `generated-by: sphinx`.

3. **`test_toc_section`** — The output contains a `## Table of contents` section with
   entries for `api`, `configuration`, and `changes`.

4. **`test_page_classification_api`** — The `api.rst` page appears under `## API
   reference` (not under a different section heading). Check by reading the rendered
   output.

5. **`test_page_classification_config`** — `configuration.rst` appears under
   `## Configuration reference`.

6. **`test_page_classification_release_notes`** — `changes.rst` appears under
   `## Release notes`.

7. **`test_documented_modules`** — The output contains a `## Documented modules`
   section listing `testproject.core`.

8. **`test_no_split_by_default`** — `app.outdir / 'modules'` does not exist when
   `agentskills_split_modules` is False (the default).

9. **`test_split_modules`** — When `agentskills_split_modules = True` and there are more
   than `agentskills_split_threshold` documented objects, sub-files appear under
   `app.outdir / 'modules'`. For this test, set `agentskills_split_threshold = 0` via
   `confoverrides` to force splitting even with the small test root, then assert that
   `app.outdir / 'modules' / 'testproject' / 'SKILL.md'` exists.

   ```python
   @pytest.mark.sphinx(
       'agentskills',
       testroot='ext-agentskills',
       confoverrides={'agentskills_split_modules': True, 'agentskills_split_threshold': 0},
   )
   def test_split_modules(app: SphinxTestApp) -> None:
       app.build()
       assert (app.outdir / 'modules' / 'testproject' / 'SKILL.md').exists()
   ```

10. **`test_module_skill_front_matter`** — Sub-skill file contains `kind: module-doc-skill`
    and `parent: ../SKILL.md`.

11. **`test_exclude_pages`** — When `agentskills_exclude_pages = ['changes']`, the output
    does not contain a reference to `changes`.

    ```python
    @pytest.mark.sphinx(
        'agentskills',
        testroot='ext-agentskills',
        confoverrides={'agentskills_exclude_pages': ['changes']},
    )
    def test_exclude_pages(app: SphinxTestApp) -> None:
        app.build()
        content = (app.outdir / 'SKILL.md').read_text(encoding='utf-8')
        assert 'changes' not in content
    ```

12. **`test_page_hints`** — When `agentskills_page_hints = {'api': 'tutorial'}`, the
    `api` page is classified as tutorial, not api.

13. **`test_notes_section`** — `## Notes for agents` section exists and mentions version.

14. **`test_no_py_domain`** — A project with no Python domain objects still produces a
    valid `SKILL.md` without crashing. Create a second test root
    `tests/roots/test-ext-agentskills-nopy/` with no Python directives and test against
    it.

For **`test-ext-agentskills-nopy`** root:
- `conf.py`: `extensions = ['sphinx.ext.agentskills']; project = 'NoPI'; version = '0.1'; release = '0.1'`
- `index.rst`: simple one-page doc with a toctree

---

## Documentation: `doc/usage/extensions/agentskills.rst`

Follow the exact pattern of `doc/usage/extensions/todo.rst` and
`doc/usage/extensions/coverage.rst`. Use the following structure:

```rst
:mod:`sphinx.ext.agentskills` -- Generate agent-facing documentation maps
===========================================================================

.. module:: sphinx.ext.agentskills
   :synopsis: Generate SKILL.md agent documentation maps from a Sphinx build.

.. role:: code-py(code)
   :language: Python

.. versionadded:: <version>

This extension adds a builder that generates a compact, versioned :file:`SKILL.md`
artifact from an existing documentation build. The artifact is intended for LLM-based
agents: it provides a structured map of a project so an agent can quickly understand
what the project is, where the authoritative docs live, what the major modules are, and
what version the information applies to.

No inference occurs at build time. The builder reads data already collected by Sphinx
(project metadata, toctree hierarchy, and domain objects) and produces a deterministic
Markdown file.

Usage
-----

Add the extension to :file:`conf.py`::

   extensions = ['sphinx.ext.agentskills']

Then run::

   sphinx-build -M agentskills sourcedir builddir

The output is written to :file:`{builddir}/agentskills/SKILL.md`.

Builder
-------

.. py:class:: AgentSkillsBuilder

   Writes one or more :file:`SKILL.md` files to the output directory.

   Activate with ``-b agentskills`` or ``-M agentskills``.

Output structure
----------------

By default a single :file:`SKILL.md` is written.  When
:confval:`agentskills_split_modules` is enabled and the number of documented
objects exceeds :confval:`agentskills_split_threshold`, additional per-module
files are written under :file:`modules/{prefix}/SKILL.md`.

Configuration
-------------

.. confval:: agentskills_split_modules
   :type: :code-py:`bool`
   :default: :code-py:`False`

   When ``True``, documented Python objects are grouped by their top-level
   package prefix and a separate :file:`SKILL.md` is written per group under
   the :file:`modules/` subdirectory, in addition to the top-level
   :file:`SKILL.md`.

.. confval:: agentskills_split_threshold
   :type: :code-py:`int`
   :default: :code-py:`50`

   Minimum number of documented objects required before module splitting takes
   effect (only relevant when :confval:`agentskills_split_modules` is ``True``).

.. confval:: agentskills_max_objects
   :type: :code-py:`int`
   :default: :code-py:`30`

   Maximum number of documented objects to list in the ``Key documented
   objects`` section of a skill file.  Objects beyond this limit are
   indicated with a count line.

.. confval:: agentskills_include_private
   :type: :code-py:`bool`
   :default: :code-py:`False`

   When ``True``, documented objects whose names contain a component starting
   with an underscore are included in the output.

.. confval:: agentskills_exclude_pages
   :type: :code-py:`list[str]`
   :default: :code-py:`[]`

   A list of Python regular expressions.  Any page whose docname matches one
   of these patterns is excluded from the skill output entirely.

.. confval:: agentskills_page_hints
   :type: :code-py:`dict[str, str]`
   :default: :code-py:`{}`

   A mapping from docname to page kind, overriding the automatic heuristic
   classification.  Valid kind values are ``'api'``, ``'config'``,
   ``'tutorial'``, ``'install'``, ``'release_notes'``, and ``'other'``.

   Example::

      agentskills_page_hints = {
          'internals/design': 'other',
          'reference/api': 'api',
      }
```

---

## `doc/usage/extensions/index.rst` modification

Add `agentskills` to the toctree under Built-in extensions, in alphabetical order before
`autodoc`:

```rst
   agentskills
   autodoc
```

---

## `CHANGES.rst` entry

Under the appropriate version heading, add:

```rst
* Added :mod:`sphinx.ext.agentskills`, a new builder that generates agent-facing
  :file:`SKILL.md` documentation maps from the build-time documentation structure.
```

---

## Implementation notes for the subagent

### Accessing the Python domain

The attribute path `self.env.domains.python_domain` is the standard way to access
the Python domain (added as a typed attribute on `_DomainsContainer`). If it is not
reliably available, use `self.env.domains.get('py')` or access
`self.env.domaindata.get('py', {})` directly for the raw data. Follow the approach used
in `sphinx.ext.coverage` (`self.env.domaindata['py']['objects']`) to remain consistent.

### `env.config.root_doc`

This is the canonical attribute for the root/master document (called `master_doc` in
older versions). Use `self.env.config.root_doc`.

### `env.config.html_baseurl`

This is optional. Guard with `if cfg.html_baseurl:` before using it in the front
matter. Do not emit `docs-url` if unset.

### YAML front matter

Do not depend on a YAML library. Write the front matter as literal strings — the values
(project name, version, release) are simple identifiers that do not require YAML quoting
in practice. If any value could contain special characters, wrap it in double quotes.
Keep this simple: the front matter is a handful of known-safe string values from
`conf.py`.

### Markdown line ending

Use `'\n'.join(lines)` and ensure the final result ends with exactly one trailing
newline. Do not use `os.linesep`; write UTF-8 with Unix line endings.

### Error handling

Follow the `text.py` builder pattern: catch `OSError` when writing files, emit a
`logger.warning`, and continue. Do not let write errors stop the overall build.

### No `write_doc` implementation

Like `CoverageBuilder`, this builder does all its work in `write_documents`. There is no
per-document processing step. Do not implement `write_doc`.

### Type annotations

Use full Python 3.12+ annotations throughout (e.g., `list[str]`, `dict[str, Any]`,
`tuple[str, ...]`). Use `from __future__ import annotations` at the top and guard
TYPE_CHECKING imports accordingly.

### ruff / mypy compliance

Run `uv run ruff check sphinx/ext/agentskills.py` and `uv run mypy sphinx/ext/agentskills.py`
against the existing project config before submitting. Fix all lint and type errors.

### Tests: reading output

Read built files with:
```python
content = (app.outdir / 'SKILL.md').read_text(encoding='utf-8')
```
Then use `assert 'string' in content` or `assert content.startswith('---')`.

### Tests: fixture pattern

Use `@pytest.mark.sphinx` on each test function. Import `SphinxTestApp` only inside
`TYPE_CHECKING`. Do not use class-based test fixtures. Follow the pattern from
`test_build_text.py` exactly.

---

## What this spec intentionally omits

- Machine-readable JSON sidecar (can be added in a follow-up)
- A discovery/publishing mechanism for external tools (explicitly out of scope for v1)
- Custom Jinja2 templates for skill files (not needed; procedural string construction
  matches the coverage and gettext patterns)
- Support for non-Python domains in the "Key documented objects" section (can be
  extended later; start with py domain only)
- A dedicated Sphinx event (no event needed for v1; the builder is complete as-is)

---

## One-sentence summary

Implement `sphinx.ext.agentskills` as a builder-only Sphinx extension in
`sphinx/ext/agentskills.py` that reads `BuildEnvironment` metadata after the read phase
and writes deterministic `SKILL.md` files to the output directory, following the exact
structural and stylistic conventions of `sphinx.ext.coverage`.
