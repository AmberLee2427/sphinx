:mod:`sphinx.ext.agentskills` -- Generate agent-facing documentation maps
==========================================================================

.. module:: sphinx.ext.agentskills
   :synopsis: Generate SKILL.md agent documentation maps from a Sphinx build.

.. role:: code-py(code)
   :language: Python

.. versionadded:: 9.1

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
