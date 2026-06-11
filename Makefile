PYTHON ?= python3

.PHONY: demo test

demo:
	$(PYTHON) -m src.demo_collect_hot_topics

test:
	$(PYTHON) -m unittest discover -s tests -v
