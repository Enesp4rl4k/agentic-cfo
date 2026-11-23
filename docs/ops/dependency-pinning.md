# Backend dependency pinning

Every backend environment (CI, `e2e.yml`, `backend/Dockerfile`) installs with

    pip install -r requirements.txt -c constraints.txt

- `backend/requirements.txt` is the human-edited list of **direct** dependencies. Every line is `name==version`.
- `backend/constraints.txt` pins **every** package pip installs, direct and transitive. It is generated, never edited by hand.
- `backend/tests/test_dependency_pins.py` fails when a direct dependency is not an exact pin, when the two files disagree, when an install line in the workflows or the Dockerfile omits `-c constraints.txt`, and (in the Backend CI job, `CHECK_INSTALLED_PINS=1`) when the installed environment differs from the lock in either direction.

Why: this product handles companies' financial data. A numerical library that changes between two runs changes forecasts; a crypto library that changes between two runs changes behaviour. A dependency changes when a person decides it does, in a reviewed diff.

The lock is a plain version list for Python 3.12 on Linux (it includes `uvloop`, for example). It carries no hashes. Hash-pinning (`pip-compile --generate-hashes`, `--require-hashes`) is the next step if the owner wants it.

## Bump one dependency deliberately

1. Read the changelog. Do not take a major version here without a migration plan (Sentry 3.x, LangChain 0.3, Pillow 13 and WeasyPrint 70 are such cases).
2. Edit the one line in `backend/requirements.txt`.
3. Regenerate the lock on Linux with Python 3.12 (a throwaway `python:3.12-slim` container or a CI job; not a Windows or macOS environment, whose resolution differs). Install **without** `-c`, so pip resolves the new set, then freeze it:

       python -m venv /tmp/lock
       /tmp/lock/bin/pip install -r requirements.txt
       /tmp/lock/bin/pip freeze --all | grep -vi '^pip==' | tr 'A-Z_' 'a-z-' | sort

   (`tr` normalises names to lower case with hyphens; `pip freeze` writes `name==version` lines.) Replace the package lines of `constraints.txt`, keep its header, update the "Origin" line. Only the packages in your diff and their dependencies should change; if dozens of lines move, something floated and needs a look.
4. Run the suite: `pytest tests/`, `mypy --config-file mypy_strict.ini`, `ruff check app/`, and the pins test with `CHECK_INSTALLED_PINS=1`.
5. **Numerical libraries (`numpy`, `scipy`, `scikit-learn`, `statsmodels`, `pandas`, `patsy`, `joblib`):** also re-run the forecast and eval golden tests (`pytest -m eval` and the forecast/anomaly tests) and compare the outputs, not only pass or fail. A change in a forecast figure needs a human to say it is expected.
6. **Crypto and auth (`cryptography`, `bcrypt`, `passlib`, `python-jose`, `ecdsa`, `rsa`):** confirm login, token issue and verify, and the connector-secret decrypt of an existing ciphertext still work.
7. Commit `requirements.txt` and `constraints.txt` together, one dependency (or one coherent group) per PR.

## Frontend

`frontend/package-lock.json` is committed and every install uses `npm ci`. The ranges in `package.json` (`^`) are resolved by the lock; update with `npm install <pkg>@<version>` and commit both files.
