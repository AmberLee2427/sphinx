"""Generate agent-facing documentation maps (SKILL.md) from a Sphinx build."""

from __future__ import annotations

import operator
import re
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

logger = logging.getLogger(__name__)

# Keyword patterns used to classify pages by docname and title.
# Order matters: first match wins.
_PAGE_KIND_PATTERNS: tuple[tuple[str, list[str]], ...] = (
    ('release_notes', ['changelog', 'changes', 'history', 'release', 'news', 'whatsnew']),
    ('tutorial', ['tutorial', 'guide', 'howto', 'example', 'quickstart',
                  'getting-started', 'getting_started']),
    ('install', ['install', 'installation', 'setup', 'requirements']),
    ('config', ['config', 'configuration', 'settings', 'options', 'reference']),
    ('api', ['api', 'library', 'autodoc', 'automodule', 'modules']),
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
            for children in self.env.toctree_includes.values():
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
        objects: list[dict[str, Any]] = []
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

        objects.sort(key=operator.itemgetter('objtype', 'name'))
        return objects

    def _collect_py_modules(self) -> list[dict[str, Any]]:
        """Return documented Python modules from the py domain's module index."""
        modules: list[dict[str, Any]] = []
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

        modules.sort(key=operator.itemgetter('name'))
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
        lines.extend(['---', f'name: {project}',
                       f'description: Agent-facing documentation map for {project}.',
                       f'version: {release}', 'kind: package-doc-skill',
                       'generated-by: sphinx'])
        if cfg.html_baseurl:
            lines.append(f'docs-url: {cfg.html_baseurl.rstrip("/")}/')
        lines.extend(['---', ''])

        # --- Overview ---
        lines.extend([f'# {project}', ''])
        if version:
            lines.extend([f'Version: {release}', ''])

        # --- Table of contents ---
        toc_pages = [p for p in pages if p['depth'] <= 1 and p['docname'] != cfg.root_doc]
        if toc_pages:
            lines.extend(['## Table of contents', ''])
            lines.extend(
                f'- [{p["title"]}]({p["docname"]}) — {p["kind"]}' for p in toc_pages
            )
            lines.append('')

        # --- Expand for docs (by kind) ---
        kind_groups: dict[str, list[dict[str, Any]]] = {}
        for page in pages:
            kind_groups.setdefault(page['kind'], []).append(page)

        section_map = {
            'api': ('## API reference',
                    'For object signatures, module layout, and documented symbols.'),
            'config': ('## Configuration reference',
                       'For configuration options and settings.'),
            'tutorial': ('## Tutorials and guides',
                         'For usage examples and getting started.'),
            'install': ('## Installation',
                        'For installation and setup.'),
            'release_notes': ('## Release notes',
                              'For version-specific behavior and changes.'),
        }
        for kind, (heading, note) in section_map.items():
            kind_pages = kind_groups.get(kind, [])
            if not kind_pages:
                continue
            lines.extend([heading, '', note, ''])
            lines.extend(f'- [{p["title"]}]({p["docname"]})' for p in kind_pages)
            lines.append('')

        # --- Documented modules ---
        if py_modules:
            lines.extend(['## Documented modules', ''])
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
            lines.extend(['## Key documented objects', ''])
            lines.extend(f'- `{obj["name"]}` ({obj["objtype"]})' for obj in shown)
            if len(py_objects) > max_objects:
                lines.append(f'- … and {len(py_objects) - max_objects} more')
            lines.append('')
        elif py_objects and has_splits:
            # Reference the module sub-skills instead.
            lines.extend(['## Module skills', '',
                           'This project is split into module-level skills.',
                           'See the `modules/` directory for per-module SKILL.md files.',
                           ''])

        # --- Notes for agents ---
        notes = [
            'Prefer the API reference section for object signatures and module layout.',
            'Prefer the configuration reference for option questions.',
            'Check the release notes for version-specific behavior.',
            f'All information applies to version {release}.',
        ]
        lines.extend(['## Notes for agents', ''])
        lines.extend(f'- {note}' for note in notes)
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

        desc = f'Agent-facing documentation map for {mod_prefix} ({project}).'
        lines.extend([
            '---',
            f'name: {mod_prefix}',
            f'description: {desc}',
            f'version: {release}',
            'kind: module-doc-skill',
            'generated-by: sphinx',
            'parent: ../SKILL.md',
            '---',
            '',
            f'# {mod_prefix}',
            '',
            f'Module group `{mod_prefix}` from `{project}` ({release}).',
            '',
        ])

        max_objects: int = self.config.agentskills_max_objects
        shown = objects[:max_objects]

        lines.extend(['## Documented objects', ''])
        lines.extend(f'- `{o["name"]}` ({o["objtype"]})' for o in shown)
        if len(objects) > max_objects:
            lines.append(f'- … and {len(objects) - max_objects} more')
        lines.append('')

        return '\n'.join(lines)

    def finish(self) -> None:
        pass


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
