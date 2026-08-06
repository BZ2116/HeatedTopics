"""Onboarding tests for new agents and developers picking up this project.

Two categories live here:

* ``test_sanity.py`` — environment self-check. Run first; failures tell
  you exactly which dependency is missing.
* ``test_how_to.py`` — executable documentation. Each test mirrors a
  README section; the docstring + code together are the docs.

Run everything::

    pytest tests/onboarding/ -v

Run only sanity::

    pytest -m sanity -v
"""