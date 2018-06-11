#!/usr/bin/env bash
if [[ $TRAVIS_TAG != "" ]] && [[ $TRAVIS_PYTHON_VERSION == "3.6" ]]; then
    poetry publish --no-interactive --build --username malinoff --password "$PYPI_PASSWORD"
fi
