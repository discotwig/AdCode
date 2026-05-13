.PHONY: test validate-example smoke

test:
	pytest

validate-example:
	python scripts/validate_example.py

smoke: validate-example test
