.PHONY: docs

env:
	pip install virtualenv && \
	virtualenv venv && \
	. venv/bin/activate && \
	make deps

deps:
	pip install -r requirements.txt
	pip install -r test-requirements.txt
	npm install

clean:
	find . -name '*.pyc' -exec rm -f {} \;
	find . -name '*.pyo' -exec rm -f {} \;
	find . -name '*~' -exec rm -f {} \;

release:
	rm -rf dist/*
	python setup.py bdist_egg
	python setup.py sdist
	twine upload dist/*
